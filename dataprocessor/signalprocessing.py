#!/usr/bin/env python

# dependencies
from scipy.interpolate import UnivariateSpline
from scipy.optimize import fmin

# local dependencies
from signalprocessing import *
from dtk.process import *

def find_bump(accelSignal, sampleRate, speed, wheelbase, bumpLength):
    '''Returns the indices that surround the bump in the acceleration signal.

    Parameters
    ----------
    accelSignal : ndarray, shape(n,)
        This is an acceleration signal with a single distinctive large
        acceleration that signifies riding over the bump.
    sampleRate : float
        This is the sample rate of the signal.
    speed : float
        Speed of travel (or treadmill) in meters per second.
    wheelbase : float
        Wheelbase of the bicycle in meters.
    bumpLength : float
        Length of the bump in meters.

    Returns
    -------
    indices : tuple
        The first and last indice of the bump section.

    '''
    # get the indice of the larger of the max and min
    maxmin = (np.nanmax(accelSignal), np.nanmin(accelSignal))
    if np.abs(maxmin[0]) > np.abs(maxmin[1]):
        indice = np.nanargmax(accelSignal)
    else:
        indice = np.nanargmin(accelSignal)

    print 'Bump indice:', indice
    print 'Bump time:', indice / sampleRate

    # give a warning if the bump doesn't seem to be at the beginning of the run
    if indice > len(accelSignal) / 3.:
        print "This signal's max value is not in the first third of the data"
        print("It is at %f seconds out of %f seconds" %
            (indice / sampleRate, len(accelSignal) / sampleRate))

    bumpDuration = (wheelbase + bumpLength) / speed
    print "Bump duration:", bumpDuration
    bumpSamples = int(bumpDuration * sampleRate)
    # make the number divisible by four
    bumpSamples = int(bumpSamples / 4) * 4

    # get the first quarter before the tallest spike and whatever is after
    indices = (indice - bumpSamples / 4, indice, indice + 3 * bumpSamples / 4)

    if np.isnan(accelSignal[indices[0]:indices[1]]).any():
        print 'There is at least one NaN in this bump'

    return indices

def split_around_nan(sig):
    '''
    Returns the sections of an array not polluted with nans.

    Parameters
    ----------
    sig : ndarray, shape(n,)
        A one dimensional array that may or may not contain m nan values where
        0 <= m <= n.

    Returns
    -------
    indices : list, len(indices) = k
        List of tuples containing the indices for the sections of the array.
    arrays : list, len(indices) = k
        List of section arrays. All arrays of nan values are of dimension 1.

    k = number of non-nan sections + number of nans

    sig[indices[k][0]:indices[k][1]] == arrays[k]

    '''
    # if there are any nans then split the signal
    if np.isnan(sig).any():
        firstSplit = np.split(sig, np.nonzero(np.isnan(sig))[0])
        arrays = []
        for arr in firstSplit:
            # if the array has nans, then split it again
            if np.isnan(arr).any():
                arrays = arrays + np.split(arr, np.nonzero(np.isnan(arr))[0] + 1)
            # if it doesn't have nans, then just add it as is
            else:
                arrays.append(arr)
        # remove any empty arrays
        emptys = [i for i, arr in enumerate(arrays) if arr.shape[0] == 0]
        arrays = [arr for i, arr in enumerate(arrays) if i not in emptys]
        # build the indices list
        indices = []
        count = 0
        for i, arr in enumerate(arrays):
            count += len(arr)
            if np.isnan(arr).any():
                indices.append((count - 1, count))
            else:
                indices.append((count - len(arr), count))
    else:
        arrays, indices = [sig], [(0, len(sig))]

    return indices, arrays

def steer_torque(steerRate, steerAccel, steerTubeTorque, handlebarInertia,
        damping, friction):
    '''Returns the steer torque applied by the rider.

    Parameters
    ----------
    steerRate : ndarray, shape(n,)
        The steer rate, i.e. rate of rotation of the fork/handlebars relative
        to the bicycle frame.
    steerAccel : ndarray, shape(n,)
        The angular acceleration of the fork/handlebars relative to the bicycle
        frame.
    steerTubeTorque : ndarray, shape(n,)
        The torque measured in the steer tube between the handlebars and the
        fork.
    handlebarInertia : float
        The inertia of the handlebars. Includes everything above and including
        the steer tube torque sensor.
    damping : float
        The damping coefficient associated with the bearing friction.
    friction : float
        The columb friction associated with the bearing friction.

    Returns
    -------
    steerTorque : ndarray, shape(n,)
        The steer torque applied by the rider.

    '''
    return (handlebarInertia * steerAccel - damping * steerRate -
            np.sign(steerRate) * friction + steerTubeTorque)

def sync_error(tau, signal1, signal2, time):
    '''Returns the error between two signal time histories.

    Parameters
    ----------
    tau : float
        The time shift.
    signal1 : ndarray, shape(n, )
        The signal that will be interpolated. This signal is
        typically "cleaner" that signal2 and/or has a higher sample rate.
    signal2 : ndarray, shape(n, )
        The signal that will be shifted to syncronize with signal 1.
    time : ndarray
        Time

    Returns
    -------
    error : float
        Error between the two signals for the given tau.

    '''
    # make sure tau isn't too large
    if np.abs(tau) >= time[-1]:
        raise ValueError(('abs(tau), {0}, must be less than or equal to ' +
                         '{1}').format(str(np.abs(tau)), str(time[-1])))

    # this is the time for the second signal which is assumed to lag the first
    # signal
    shiftedTime = time + tau

    # create time vector where the two signals overlap
    if tau > 0:
        intervalTime = shiftedTime[np.nonzero(shiftedTime < time[-1])]
    else:
        intervalTime = shiftedTime[np.nonzero(shiftedTime > time[0])]

    # interpolate between signal 1 samples to find points that correspond in
    # time to signal 2 on the shifted time
    sig1OnInterval = np.interp(intervalTime, time, signal1);

    # truncate signal 2 to the time interval
    if tau > 0:
        sig2OnInterval = signal2[np.nonzero(shiftedTime <= intervalTime[-1])]
    else:
        sig2OnInterval = signal2[np.nonzero(shiftedTime >= intervalTime[0])]

    # calculate the error between the two signals
    error = np.linalg.norm(sig1OnInterval - sig2OnInterval)

    return error

def find_timeshift(niAcc, vnAcc, sampleRate, speed):
    '''Returns the timeshift, tau, of the VectorNav [VN] data relative to the
    National Instruments [NI] data.

    Parameters
    ----------
    NIacc : ndarray, shape(n, )
        The acceleration of the NI accelerometer in its local Y direction.
    VNacc : ndarray, shape(n, )
        The acceleration of the VN-100 in its local Z direction. Should be the
        same length as NIacc and contains the same signal albiet time shifted.
        The VectorNav signal should be leading the NI signal.
    sampleRate : integer
        Sample rate of the signals. This should be the same for each signal.
    speed : float
        The approximate forward speed of the bicycle.

    Returns
    -------
    tau : float
        The timeshift.

    '''
    # raise an error if the signals are not the same length
    N = len(niAcc)
    if N != len(vnAcc):
        raise StandardError('Signals are not the same length!')

    # make a time vector
    time = time_vector(N, sampleRate)

    # the signals are opposite sign of each other
    niSig = -niAcc
    vnSig = vnAcc

    # some constants for find_bump
    wheelbase = 1.02
    bumpLength = 1.
    cutoff = 50.
    # filter the NI Signal
    filNiSig = butterworth(niSig, cutoff, sampleRate)
    # find the bump in the filtered NI signal
    niBump =  find_bump(filNiSig, sampleRate, speed, wheelbase, bumpLength)

    # remove the nan's in the VN signal and the time
    v = vnSig[np.nonzero(np.isnan(vnSig) == False)]
    t = time[np.nonzero(np.isnan(vnSig) == False)]
    # fit a spline through the data
    vn_spline = UnivariateSpline(t, v, k=3, s=0)
    # and filter it
    filVnSig = butterworth(vn_spline(time), cutoff, sampleRate)
    # and find the bump in the filtered VN signal
    vnBump = find_bump(filVnSig, sampleRate, speed, wheelbase, bumpLength)

    # get an initial guess for the time shift based on the bump indice
    guess = (niBump[1] - vnBump[1]) / float(sampleRate)

    # find the section that the bump belongs to
    indices, arrays = split_around_nan(vnSig)
    for pair in indices:
        if pair[0] <= vnBump[1] < pair[1]:
            bSec = pair

    # subtract the mean and normalize both signals
    niSig = normalize(subtract_mean(niSig))
    vnSig = normalize(subtract_mean(vnSig))

    niBumpSec = niSig[bSec[0]:bSec[1]]
    vnBumpSec = vnSig[bSec[0]:bSec[1]]
    timeBumpSec = time[bSec[0]:bSec[1]]

    if len(niBumpSec) < 200:
        raise Warning('The bump section is mighty small.')

    # set up the error landscape, error vs tau
    # The NI lags the VectorNav and the time shift is typically between 0 and
    # 0.5 seconds
    tauRange = np.linspace(0., .5, num=500)
    error = np.zeros_like(tauRange)
    for i, val in enumerate(tauRange):
        error[i] = sync_error(val, niBumpSec, vnBumpSec, timeBumpSec)

    # find initial condition from landscape
    tau0 = tauRange[np.argmin(error)]

    print "The minimun of the error landscape is %f and the provided guess is %f" % (tau0, guess)

    # if tau is not close to the other guess then say something
    isNone = guess == None
    isInRange = 0. < guess < 1.
    isCloseToTau = guess - .1 < tau0 < guess + .1

    if not isNone and isInRange and not isCloseToTau:
        print("This tau0 may be a bad guess, check the error function!" +
              " Using guess instead.")
        tau0 = guess

    print "Using %f as the guess for minimization." % tau0

    tau  = fmin(sync_error, tau0, args=(niBumpSec, vnBumpSec, timeBumpSec))[0]

    print "This is what came out of the minimization:", tau

    # if the minimization doesn't do a good job, just use the tau0
    if np.abs(tau - tau0) > 0.01:
        tau = tau0
        print "Bad minimizer!! Using the guess, %f, instead." % tau

    return tau

def truncate_data(signal, tau):
    '''
    Returns the truncated vectors with respect to the timeshift tau.

    Parameters
    ---------
    signal : Signal(ndarray), shape(n, )
        A time signal from the NIData or the VNavData.
    tau : float
        The time shift.

    Returns
    -------
    truncated : ndarray, shape(m, )
        The truncated time signal.

    '''
    t = time_vector(len(signal), signal.sampleRate)

    # shift the ni data cause it is the cleaner signal
    tni = t - tau
    tvn = t

    # make the common time interval
    tcom = tvn[np.nonzero(tvn < tni[-1])]

    if signal.source == 'NI':
        truncated = np.interp(tcom, tni, signal)
    elif signal.source == 'VN':
        truncated = signal[np.nonzero(tvn <= tcom[-1])]
    else:
        raise ValueError('No source was defined in this signal.')

    return truncated

def yaw_roll_pitch_rate(angularRateX, angularRateY, angularRateZ,
                        lam, rollAngle=0.):
    '''Returns the bicycle frame yaw, roll and pitch rates based on the body
    fixed rate data taken with the VN-100 and optionally the roll angle
    measurement.

    Parameters
    ----------
    angularRateX : ndarray, shape(n,)
        The body fixed rate perpendicular to the headtube and pointing forward.
    angularRateY : ndarray, shape(n,)
        The body fixed rate perpendicular to the headtube and pointing to the
        right of the bicycle.
    angularRateZ : ndarray, shape(n,)
        The body fixed rate aligned with the headtube and pointing downward.
    lam : float
        The steer axis tilt.
    rollAngle : ndarray, shape(n,), optional
        The roll angle of the bicycle frame.

    Returns
    -------
    yawRate : ndarray, shape(n,)
        The yaw rate of the bicycle frame.
    rollRate : ndarray, shape(n,)
        The roll rate of the bicycle frame.
    pitchRate : ndarray, shape(n,)
        The pitch rate of the bicycle frame.

    '''
    yawRate = -(angularRateX*np.sin(lam) -
                angularRateZ * np.cos(lam)) / np.cos(rollAngle)
    rollRate = angularRateX * np.cos(lam) + angularRateZ * np.sin(lam)
    pitchRate = (angularRateY + angularRateX * np.sin(lam) * np.tan(rollAngle) -
                 angularRateZ * np.cos(lam) * np.tan(rollAngle))

    return yawRate, rollRate, pitchRate

def steer_rate(forkRate, angularRateZ):
    '''Returns the steer rate.'''
    return forkRate - angularRateZ
