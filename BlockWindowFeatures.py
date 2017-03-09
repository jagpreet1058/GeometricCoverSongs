import numpy as np
import sys
import scipy.io as sio
import scipy.misc
from scipy.interpolate import interp1d
from scipy import signal
import time
import pickle
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from CSMSSMTools import *
from CurvatureTools import *
from SpectralMethods import *
from MusicFeatures import *
import librosa
import subprocess

#Need to specify hopSize as as parameter so that beat onsets
#Align with MFCC and chroma windows
def getBlockWindowFeatures(args):
    #Unpack parameters
    (XAudio, Fs, tempo, beats, hopSize, FeatureParams) = args
    NBeats = len(beats)-1
    winSize = int(np.round((60.0/tempo)*Fs))
    BlockFeatures = {}
    OtherFeatures = {}

    #########################
    #  MFCC-Based Features  #
    #########################
    #Step 1: Determine which features have been specified and allocate space
    usingMFCC = False
    [MFCCSamplesPerBlock, DPixels, NGeodesic, NJump, NCurv, NTors, NJumpSS, NCurvSS, NTorsSS, D2Samples, DiffusionKappa, tDiffusion] = [-1]*12
    #Default parameters
    GeodesicDelta = 10
    CurvSigmas = [40]
    NMFCC = 20
    MFCCBeatsPerBlock = 20
    sigmasSS = np.linspace(1, 40, 10) #Scale space sigmas
    NMFCCBlocks = 0
    lifterexp = 0.6
    if 'NMFCC' in FeatureParams:
        NMFCC = FeatureParams['NMFCC']
        usingMFCC = True
    if 'lifterexp' in FeatureParams:
        lifterexp = FeatureParams['lifterexp']
        usingMFCC = True
    if 'MFCCBeatsPerBlock' in FeatureParams:
        MFCCBeatsPerBlock = FeatureParams['MFCCBeatsPerBlock']
        usingMFCC = True

    NMFCCBlocks = NBeats - MFCCBeatsPerBlock

    if 'MFCCSamplesPerBlock' in FeatureParams:
        MFCCSamplesPerBlock = FeatureParams['MFCCSamplesPerBlock']
        BlockFeatures['MFCCs'] = np.zeros((NMFCCBlocks, MFCCSamplesPerBlock*NMFCC))
    if 'DPixels' in FeatureParams:
        DPixels = FeatureParams['DPixels']
        NPixels = DPixels*(DPixels-1)/2
        [I, J] = np.meshgrid(np.arange(DPixels), np.arange(DPixels))
        BlockFeatures['SSMs'] = np.zeros((NMFCCBlocks, NPixels), dtype = np.float32)
        if 'DiffusionKappa' in FeatureParams:
            DiffusionKappa = FeatureParams['DiffusionKappa']
            BlockFeatures['SSMsDiffusion'] = np.zeros((NMFCCBlocks, NPixels), dtype = np.float32)
        usingMFCC = True
    if 'tDiffusion' in FeatureParams:
        tDiffusion = FeatureParams['tDiffusion']
    if 'sigmasSS' in FeatureParams:
        sigmasSS = FeatureParams['sigmasSS']
        usingMFCC = True
    if 'CurvSigmas' in FeatureParams:
        CurvSigmas = FeatureParams['CurvSigmas']
        usingMFCC = True

    #Geodesic/jump/curvature/torsion
    if 'GeodesicDelta' in FeatureParams:
        GeodesicDelta = FeatureParams['GeodesicDelta']
        usingMFCC = True
    if 'NGeodesic' in FeatureParams:
        NGeodesic = FeatureParams['NGeodesic']
        BlockFeatures['Geodesics'] = np.zeros((NMFCCBlocks, NGeodesic))
        usingMFCC = True
    if 'NJump' in FeatureParams:
        NJump = FeatureParams['NJump']
        for sigma in CurvSigmas:
            BlockFeatures['Jumps%g'%sigma] = np.zeros((NMFCCBlocks, NJump), dtype = np.float32)
        usingMFCC = True
    if 'NCurv' in FeatureParams:
        NCurv = FeatureParams['NCurv']
        for sigma in CurvSigmas:
            BlockFeatures['Curvs%g'%sigma] = np.zeros((NMFCCBlocks, NCurv), dtype = np.float32)
        usingMFCC = True
    if 'NTors' in FeatureParams:
        NTors = FeatureParams['NTors']
        for sigma in CurvSigmas:
            BlockFeatures['Tors%g'%sigma] = np.zeros((NMFCCBlocks, NTors), dtype = np.float32)
        usingMFCC = True

    #Scale space stuff
    if 'NCurvSS' in FeatureParams:
        NCurvSS = FeatureParams['NCurvSS']
        BlockFeatures['CurvsSS'] = np.zeros((NMFCCBlocks, NCurvSS*len(sigmasSS)), dtype = np.float32)
        usingMFCC = True
    if 'NTorsSS' in FeatureParams:
        NTorsSS = FeatureParams['NTorsSS']
        BlockFeatures['TorsSS'] = np.zeros((NMFCCBlocks, NTorsSS*len(sigmasSS)), dtype = np.float32)
        usingMFCC = True
    if 'NJumpSS' in FeatureParams:
        NJumpSS = FeatureParams['NJumpSS']
        BlockFeatures['JumpsSS'] = np.zeros((NMFCCBlocks, NJumpSS*len(sigmasSS)), dtype = np.float32)
        usingMFCC = True


    if 'D2Samples' in FeatureParams:
        D2Samples = FeatureParams['D2Samples']
        BlockFeatures['D2s'] = np.zeros((NMFCCBlocks, D2Samples), dtype = np.float32)
        usingMFCC = True

    #Step 3: Compute Mel-Spaced log STFTs
    XMFCC = np.array([])
    if usingMFCC:
        XMFCC = getMFCCs(XAudio, Fs, winSize, hopSize, lifterexp = lifterexp, NMFCC = NMFCC)
    else:
        NMFCCBlocks = 0

    #Step 4: Compute MFCC-based features in z-normalized blocks
    for i in range(NMFCCBlocks):
        i1 = beats[i]
        i2 = beats[i+MFCCBeatsPerBlock]
        x = XMFCC[:, i1:i2].T
        #Mean-center x
        x = x - np.mean(x, 0)
        #Normalize x
        xnorm = np.sqrt(np.sum(x**2, 1))[:, None]
        xnorm[xnorm == 0] = 1
        xn = x / xnorm

        #Straight block-windowed MFCC
        if MFCCSamplesPerBlock > -1:
            xnr = scipy.misc.imresize(xn, (MFCCSamplesPerBlock, xn.shape[1]))
            BlockFeatures['MFCCs'][i, :] = xnr.flatten()

        #Compute SSM and D2 histogram
        SSMRes = xn.shape[0]
        if DPixels > -1:
            SSMRes = DPixels
        if DPixels > -1 or D2Samples > -1:
            (DOrig, D) = getSSM(xn, SSMRes)
        if DPixels > -1:
            BlockFeatures['SSMs'][i, :] = D[I < J]
            if DiffusionKappa > -1:
                xDiffusion = getDiffusionMap(DOrig, DiffusionKappa, tDiffusion)
                (_, SSMDiffusion) = getSSM(xDiffusion, SSMRes)
                BlockFeatures['SSMsDiffusion'][i, :] = SSMDiffusion[I < J]

        if D2Samples > -1:
            [IO, JO] = np.meshgrid(np.arange(DOrig.shape[0]), np.arange(DOrig.shape[0]))
            BlockFeatures['D2s'][i, :] = np.histogram(DOrig[IO < JO], bins = D2Samples, range = (0, 2))[0]
            BlockFeatures['D2s'][i, :] = BlockFeatures['D2s'][i, :]/np.sum(BlockFeatures['D2s'][i, :]) #Normalize

        #Compute geodesic distance
        if NGeodesic > -1:
            jump = xn[1::, :] - xn[0:-1, :]
            jump = np.sqrt(np.sum(jump**2, 1))
            jump = np.concatenate(([0], jump))
            geodesic = np.cumsum(jump)
            geodesic = geodesic[GeodesicDelta*2::] - geodesic[0:-GeodesicDelta*2]
            BlockFeatures['Geodesics'][i, :] = signal.resample(geodesic, NGeodesic)

        #Compute velocity/curvature/torsion
        MaxOrder = 0
        if NTors > -1:
            MaxOrder = 3
        elif NCurv > -1:
            MaxOrder = 2
        elif NJump > -1:
            MaxOrder = 1
        if MaxOrder > 0:
            for sigma in CurvSigmas:
                curvs = getCurvVectors(xn, MaxOrder, sigma)
                if MaxOrder > 2 and NTors > -1:
                    tors = np.sqrt(np.sum(curvs[3]**2, 1))
                    BlockFeatures['Tors%g'%sigma][i, :] = signal.resample(tors, NTors)
                if MaxOrder > 1 and NCurv > -1:
                    curv = np.sqrt(np.sum(curvs[2]**2, 1))
                    BlockFeatures['Curvs%g'%sigma][i, :] = signal.resample(curv, NCurv)
                if NJump > -1:
                    jump = np.sqrt(np.sum(curvs[1]**2, 1))
                    BlockFeatures['Jumps%g'%sigma][i, :] = signal.resample(jump, NJump)

        #Compute curvature/torsion scale space
        MaxOrder = 0
        if NTorsSS > -1:
            MaxOrder = 3
        elif NCurvSS > -1:
            MaxOrder = 2
        elif NJumpSS > -1:
            MaxOrder = 1
        if MaxOrder > 0:
            SSImages = getMultiresCurvatureImages(xn, MaxOrder, sigmasSS)
            if len(SSImages) >= 3 and NTorsSS > -1:
                TSS = SSImages[2]
                TSS = scipy.misc.imresize(TSS, (len(sigmasSS), NTorsSS))
                BlockFeatures['TorsSS'][i, :] = TSS.flatten()
            if len(SSImages) >= 2 and NCurvSS > -1:
                CSS = SSImages[1]
                CSS = scipy.misc.imresize(CSS, (len(sigmasSS), NCurvSS))
                #plt.imshow(CSS, interpolation = 'none', aspect = 'auto')
                #plt.show()
                BlockFeatures['CurvsSS'][i, :] = CSS.flatten()
            if len(SSImages) >= 1 and NJumpSS > -1:
                JSS = SSImages[0]
                JSS = scipy.misc.imresize(JSS, (len(sigmasSS), NJumpSS))
                BlockFeatures['JumpsSS'][i, :] = JSS.flatten()


    ###########################
    #  Chroma-Based Features  #
    ###########################
    #Step 1: Figure out which features are requested and allocate space
    usingChroma = False
    NChromaBlocks = 0
    ChromaBeatsPerBlock = 20
    ChromasPerBlock = 40
    NChromaBins = 12
    if 'ChromaBeatsPerBlock' in FeatureParams:
        ChromaBeatsPerBlock = FeatureParams['ChromaBeatsPerBlock']
        NChromaBlocks = NBeats - ChromaBeatsPerBlock
        usingChroma = True
    if 'ChromasPerBlock' in FeatureParams:
        ChromasPerBlock = FeatureParams['ChromasPerBlock']
        usingChroma = True
    if 'NChromaBins' in FeatureParams:
        NChromaBins = FeatureParams['NChromaBins']
    XChroma = np.array([])
    if usingChroma:
        BlockFeatures['Chromas'] = np.zeros((NChromaBlocks, ChromasPerBlock*NChromaBins))
        #XChroma = getCensFeatures(XAudio, Fs, hopSize)
        XChroma = getHPCPEssentia(XAudio, Fs, hopSize*4, hopSize, NChromaBins = NChromaBins)
        #librosa.display.specshow(XChroma, y_axis='chroma', x_axis='time')
        #plt.show()
        OtherFeatures['ChromaMean'] = np.mean(XChroma, 1)
    for i in range(NChromaBlocks):
        i1 = beats[i]
        i2 = beats[i+ChromaBeatsPerBlock]
        x = XChroma[:, i1:i2].T
        x = scipy.misc.imresize(x, (ChromasPerBlock, x.shape[1]))
        xnorm = np.sqrt(np.sum(x**2, 1))
        xnorm[xnorm == 0] = 1
        x = x/xnorm[:, None]
        BlockFeatures['Chromas'][i, :] = x.flatten()

    return (BlockFeatures, OtherFeatures)

def plotSongLabels(song1, song2, k = 3):
    for i in range(k):
        plt.subplot(1, k, i+1)
        plt.xlabel("%s Beat Index"%song2)
        plt.ylabel("%s Beat Index"%song1)

def makeColorbar(k = 3):
    plt.subplot(1, k, k)
    ax = plt.gca()
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad = 0.05)
    plt.colorbar(cax = cax)

def compareTwoSongs(filename1, TempoBias1, filename2, TempoBias2, hopSize, FeatureParams, CSMTypes, Kappa, fileprefix, song1name = 'Song 1', song2name = 'Song 2'):
    print "Getting features for %s..."%filename1
    (XAudio, Fs) = getAudio(filename1)
    (tempo, beats) = getBeats(XAudio, Fs, TempoBias1, hopSize)
    (Features1, O1) = getBlockWindowFeatures((XAudio, Fs, tempo, beats, hopSize, FeatureParams))

    print "Getting features for %s..."%filename2
    (XAudio, Fs) = getAudio(filename2)
    (tempo, beats) = getBeats(XAudio, Fs, TempoBias2, hopSize)
    (Features2, O2) = getBlockWindowFeatures((XAudio, Fs, tempo, beats, hopSize, FeatureParams))

    print "Feature Types: ", Features1.keys()

    Results = {'filename1':filename1, 'filename2':filename2, 'TempoBias1':TempoBias1, 'TempoBias2':TempoBias2, 'hopSize':hopSize, 'FeatureParams':FeatureParams, 'CSMTypes':CSMTypes, 'Kappa':Kappa}
    plt.figure(figsize=(18, 5))

    #Do each feature individually
    for FeatureName in Features1:
        plt.clf()
        score = getCSMSmithWatermanScores([Features1[FeatureName], O1, Features2[FeatureName], O2, Kappa, CSMTypes[FeatureName]], True)
        plotSongLabels(song1name, song2name)
        makeColorbar()
        plt.subplot(131)
        plt.title("CSM %s"%FeatureName)
        plt.savefig("%s_CSMs_%s.svg"%(fileprefix, FeatureName), dpi=200, bbox_inches='tight')

    #Do OR Merging
    plt.clf()
    res = getCSMSmithWatermanScoresORMerge([Features1, O1, Features2, O2, Kappa, CSMTypes], True)
    plt.subplot(131)
    plt.imshow(1-res['DBinary'], interpolation = 'nearest', cmap = 'gray')
    plt.title("CSM Binary OR Fused, $\kappa$=%g"%Kappa)
    plt.subplot(132)
    plt.imshow(res['D'], interpolation = 'nearest', cmap = 'afmhot')
    plt.title("Smith Waterman Score = %g"%res['maxD'])
    plotSongLabels(song1name, song2name)
    plt.savefig("%s_CSMs_ORMerged.svg"%fileprefix, dpi=200, bbox_inches='tight')

    #Do cross-similarity fusion
    plt.clf()
    K = 20
    NIters = 3
    res = getCSMSmithWatermanScoresEarlyFusionFull([Features1, O1, Features2, O2, Kappa, K, NIters, CSMTypes], True)
    plt.clf()
    Results['CSMFused'] = res['CSM']
    plt.subplot(131)
    plt.imshow(res['CSM'], interpolation = 'nearest', cmap = 'afmhot')
    plt.title('W Similarity Network Fusion')
    plt.subplot(132)
    plt.imshow(1-res['DBinary'], interpolation = 'nearest', cmap = 'gray')
    plt.title("CSM Binary, $\kappa$=%g"%Kappa)
    plt.subplot(133)
    plt.imshow(res['D'], interpolation = 'nearest', cmap = 'afmhot')
    plt.title("Smith Waterman Score = %g"%res['maxD'])
    plotSongLabels(song1name, song2name)
    makeColorbar()
    plt.savefig("%s_CSMs_Fused.svg"%fileprefix, dpi=200, bbox_inches='tight')

    sio.savemat("%s.mat"%fileprefix, Results)
