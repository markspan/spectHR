import copy
from collections import Counter

import numpy as np
import pandas as pd
import scipy.signal as signal

import spectHR as cs
from spectHR.Tools.Logger import logger


def calcPeaks(DataSet, par=None):
    """
    Detects R-tops (peaks) in an ECG signal and calculates the Inter-Beat Interval (IBI).

    Args:
        DataSet (CarspanDataSet): The DataSet object containing ECG data.
        par (dict): Parameter dictionary for peak detection and filtering.

    Returns:
        DataSet (CarspanDataSet): The DataSet with updated RTopTimes.
        par (dict): The parameter dictionary, updated if necessary.
    """

    default_par = {
        'MinPeakDistance': 300,  # ms
        'fSample': DataSet.ecg.srate,          # Sampling frequency (Hz)
        'MinPeakHeight': None,    # This will be computed during calcPeaks
        'Classify': True
    }

    # Merge passed par with default if any
    par = {**default_par, **(par or {})}

    DS = copy.deepcopy(DataSet)

    # Store the final par used in the DataSet
    DS.par['calcPeaks'] = par

    # Step 1: Estimate a minimum peak height based on the median and standard deviation of the signal
    # This avoids detecting small noise fluctuations as peaks.
    par['MinPeakHeight'] = np.nanmedian(
        DS.ecg.level) + (1.5 * np.nanstd(DS.ecg.level))

    # Step 2: Convert MinPeakDistance from milliseconds to samples using the sampling frequency
    MinPeakDistance = ((par['MinPeakDistance'] / 1000) * par['fSample'])

    # Step 3: Detect peaks in the ECG signal using scipy's find_peaks method
    # 'height' specifies the minimum peak height, and 'distance' ensures peaks are spaced apart
    locs, props = signal.find_peaks(
        DS.ecg.level, height=par['MinPeakHeight'], distance=MinPeakDistance)

    # Step 4: Store the values of the ECG signal at the detected peak locations
    vals = DS.ecg.level.iloc[locs].array
    pre = DS.ecg.level.iloc[locs-1].array
    post = DS.ecg.level.iloc[locs+1].array
    # Step 5: Calculate the rate of change (rc) before and after each peak
    # This gives insight into the sharpness of the peak (the difference between the peak and neighboring points)
    rc_before = np.abs(vals - pre)  # Difference with previous point
    rc_after = np.abs(post - vals)   # Difference with next point
    # Take the maximum of the two rates of change
    rc = np.maximum(rc_before, rc_after)

    # Step 6: Optionally apply corrections to the peak times (uncomment if needed)
    correction = (post - pre) / par['fSample'] / 2.0 / np.abs(rc)

    # Print the number of detected R-tops for logging purposes
    logger.info(f"Found {len(locs)} r-tops")

    # Step 7: Update the DataSet's RTopTimes with the time stamps corresponding to the detected peaks
    DS.RTops = pd.DataFrame(
        {'time': (DS.ecg.time.iloc[locs] + correction).tolist()})
    # Step 8: If warrented: classify and label the peaks
    # Calculate the IBIs
    IBI = np.append(np.diff(DS.RTops['time']), float('nan'))
    DS.RTops['ibi'] = IBI

    DS.RTops['ID'] = 'N'
    if par['Classify']:
        classify(DS)
    # Log the action
    DS.log_action('calcPeaks', par)
    # Step 9: Return the updated DataSet and the parameters
    return DS


def filterECGData(DataSet, par=None):
    """
    Placeholder function for filtering ECG data, which can be customized.
    Possible filtering techniques could include low-pass or band-pass filters 
    to clean the ECG signal.

    Args:
        DataSet (CarspanDataSet): The DataSet object containing ECG data.
        par (dict): Parameter dictionary for filtering configurations.

    Returns:
        DataSet (CarspanDataSet): The filtered DataSet (when implemented).
    """
    # Example filtering logic could go here
    # You could apply a band-pass filter using scipy or another library

    # Step 1: Choose filter parameters (this is just a placeholder for now)
    # e.g., highpass = 0.5, lowpass = 45.0, order = 4
    # Use default parameters if par is None
    default_par = {
        'channel': 'ecg',
        'filterType': 'highpass',  # Example: filter type (lowpass, highpass)
        'cutoff': .1,               # Hz: Cutoff frequency for the filter
        'fSample': DataSet.ecg.srate            # Sampling frequency (Hz)
    }

    # Merge passed par with default if any
    par = {**default_par, **(par or {})}

    # Create a deep copy of the DataSet to avoid modifying the original object
    DS = copy.deepcopy(DataSet)

    # Store the final par used in the DataSet
    DS.par['filterData'] = par

    # Apply the filter using SciPy's signal package
    nyquist = 0.5 * par['fSample']
    normal_cutoff = par['cutoff'] / nyquist

    passband = normal_cutoff * 1.1
    stopband = normal_cutoff / 1.5

    N, wn = signal.buttord(passband, stopband, 1, 5)
    logger.info(
        f'creating a filter with order {N} , passband at {passband*nyquist}')
    # Example: lowpass or highpass filter
    if par['filterType'] == 'lowpass':
        # b, a = signal.butter(par['order'], normal_cutoff, btype='low', analog=False)
        b, a = signal.butter(N, wn, btype='low', analog=False)
    elif par['filterType'] == 'highpass':
        # b, a = signal.butter(par['order'], normal_cutoff, btype='high', analog=False)
        b, a = signal.butter(N, wn, btype='high', analog=False)

    channel = par['channel']
    # Apply the filter to the signal
    if channel == 'ecg':
        DS.ecg.level = pd.Series(signal.filtfilt(b, a, DS.ecg.level))
    if channel == 'br':
        DS.br.level = pd.Series(signal.filtfilt(b, a, DS.br.level))
    if channel == 'bp':
        DS.bp.level = pd.Series(signal.filtfilt(b, a, DS.bp.level))

    # Log the action
    DS.log_action('filterData', par)
    logger.info(
        f"Data filtered with a {par['filterType']} filter (cutoff = {par['cutoff']} Hz).")
    return DS


def ecgArtifactDetection(Data, par={}):
    """
    Detect and suppress artifact-laden segments in an ECG time series using dynamic time warping (DTW)
    against a template QRS complex derived from a clean middle segment of the signal.

    Parameters
    ----------
    ts : pd.DataFrame or object with attribute 'level' (pd.Series)
        The ECG time series. The 'level' attribute should be a pandas Series containing the ECG signal,
        indexed by timestamps.

    par : dict, optional
        Dictionary of parameters:
        - 'dtw_thresh' (float): DTW distance threshold for rejection. Default is 100000.
        - 'fs' (int): Sampling frequency of the ECG signal in Hz. Default is 130.
        - 'norm' (bool): Whether to z-score normalize ECG segments before comparison. Default is False.
        - 'max_extension_secs' (float): Maximum duration (in seconds) by which to extend an epoch
          if no R-peaks are initially detected. Default is 2 seconds.

    Returns
    -------
    ts_cleaned : same type as input ts
        A deep copy of `ts`, with 'level' replaced by a version in which artifact epochs have been
        zeroed out based on DTW distance to the template beat.

    Notes
    -----
    - Each 1-second epoch is examined for R-peaks. If none are found, the epoch is extended by up
      to `max_extension_secs` in both directions to allow for delayed beats.
    - The middle 5 seconds of the signal are used to extract a template QRS complex from a clean beat.
    - DTW distance is calculated between this template and each beat in the epoch.
    - If any beat in the epoch exceeds the `dtw_thresh`, the entire epoch is rejected.
    """
    import copy

    import neurokit2 as nk
    import numpy as np
    import pandas as pd
    from fastdtw import fastdtw

    DataSet = copy.deepcopy(Data)

    if not hasattr(DataSet, 'ecg'):
        return

    ts = DataSet.ecg
    dtw_thresh = par.get('dtw_thresh', 100000)
    fs = par.get('fs', 130)
    norm = par.get('norm', False)
    max_extension_secs = par.get('max_extension_secs', 2)

    # Create deep copy to preserve original data
    ts_cleaned = copy.deepcopy(ts)

    # Convert input ECG signal to numpy array
    ecg = np.array(ts.level)
    n_samples = len(ecg)
    epoch_len = fs  # 1-second epochs
    epochs_cleared = 0
    # Create template from a clean 5-second middle segment
    mid_center = n_samples // 2
    five_sec_len = 5 * fs
    seg_start = max(0, mid_center - five_sec_len // 2)
    seg_end = min(n_samples, seg_start + five_sec_len)
    middle_segment = ecg[seg_start:seg_end]

    # Extract R-peaks from the middle segment
    _, rpeaks_dict = nk.ecg_peaks(middle_segment, sampling_rate=fs)
    rpeaks = list(rpeaks_dict["ECG_R_Peaks"])
    if len(rpeaks) == 0:
        raise RuntimeError(
            "No R-peaks found in middle segment for template creation.")

    # Extract one beat around a well-positioned R-peak to use as template
    template = None
    half_win = fs // 2
    for r in rpeaks:
        t_start = r - half_win
        t_end = t_start + fs
        if t_start >= 0 and t_end <= len(middle_segment):
            template = middle_segment[t_start:t_end]
            break
    if template is None:
        raise RuntimeError(
            "No suitable R-peak found in middle segment with enough margin for template window.")

    if norm:
        template = (template - np.mean(template)) / np.std(template)

    def detect_rpeaks_with_extension(start, end):
        """
        Attempt to detect R-peaks within an epoch.
        If no R-peaks are found, extend the window in both directions
        up to `max_extension_secs` and try again.
        """
        window_start, window_end = start, end
        extension = int(fs * max_extension_secs)
        while True:
            epoch = ecg[window_start:window_end]
            _, rpeaks_dict = nk.ecg_peaks(epoch, sampling_rate=fs)
            rpeaks = list(rpeaks_dict["ECG_R_Peaks"])
            if len(rpeaks) > 0:
                return rpeaks, window_start, window_end
            # Try to extend the window
            new_start = max(0, window_start - extension)
            new_end = min(n_samples, window_end + extension)
            if new_start == window_start and new_end == window_end:
                return [], window_start, window_end  # No further extension possible
            window_start, window_end = new_start, new_end

    ecg_cleaned = np.array(ecg, copy=True)

    # Full 1-second epochs
    n_full_epochs = n_samples // epoch_len
    remainder = n_samples % epoch_len
    last_epoch_index = n_full_epochs - 1 if remainder > 0 else n_full_epochs

    for i in range(last_epoch_index):
        start = i * epoch_len
        end = start + epoch_len

        rpeaks, r_start, r_end = detect_rpeaks_with_extension(start, end)
        if len(rpeaks) == 0:
            # Still no R-peaks after extension: zero out original (unextended) epoch
            ecg_cleaned[start:end] = 0
            epochs_cleared += 1
            continue

        reject_epoch = False
        for r_peak in rpeaks:
            global_r = r_peak + r_start  # Shift local to global index
            sub_start = global_r - fs // 2
            sub_end = sub_start + fs
            if sub_start < 0 or sub_end > n_samples:
                continue  # Skip if beat would exceed bounds
            sub_segment = ecg[sub_start:sub_end]
            if norm:
                sub_segment = (sub_segment - np.mean(sub_segment)
                               ) / np.std(sub_segment)
            dist, _ = fastdtw(sub_segment, template)
            if dist > dtw_thresh:
                reject_epoch = True
                break

        if reject_epoch:
            ecg_cleaned[start:end] = 0
            epochs_cleared += 1

    # Handle final partial epoch (if any)
    if remainder > 0:
        if n_full_epochs == 0:
            start = 0
            end = n_samples
        else:
            start = last_epoch_index * epoch_len
            end = n_samples

        rpeaks, r_start, r_end = detect_rpeaks_with_extension(start, end)
        if len(rpeaks) == 0:
            ecg_cleaned[start:end] = 0
            epochs_cleared += 1
        else:
            reject_epoch = False
            for r_peak in rpeaks:
                global_r = r_peak + r_start
                sub_start = global_r - fs // 2
                sub_end = sub_start + fs
                if sub_start < 0 or sub_end > n_samples:
                    continue
                sub_segment = ecg[sub_start:sub_end]
                if norm:
                    sub_segment = (
                        sub_segment - np.mean(sub_segment)) / np.std(sub_segment)
                dist, _ = fastdtw(sub_segment, template)
                if dist > dtw_thresh:
                    reject_epoch = True
                    break
            if reject_epoch:
                ecg_cleaned[start:end] = 0
                epochs_cleared += 1

    # Replace 'level' with cleaned signal as Series with original metadata
    logger.info(f'Cleared {epochs_cleared} epochs')
    ts_cleaned.level = pd.Series(
        ecg_cleaned, index=ts.level.index, name=ts.level.name)
    DataSet.log_action('ecgArtifactDetection', par)
    return DataSet


def borderData(DataSet, par=None):
    """
    Creates a modified version of the provided DataSet by slicing TimeSeries based on the first and last events.

    Args:
        DataSet: The original DataSet to be modified.
        par (dict, optional): Parameters for additional configurations. Defaults to None.

    Returns:
        CarspanDataSet: A new instance of CarspanDataSet with TimeSeries sliced.
    """
    default_par = {
        # Define any default parameters if needed
    }

    # Merge passed par with default if any
    par = {**default_par, **(par or {})}

    # Create a deep copy of the DataSet to avoid modifying the original object
    DS = copy.deepcopy(DataSet)
    # Ensure that events exist in the DataSet
    if DS.events is not None and not DS.events.empty:
        # Get the first and last event timestamps
        first_event_time = DS.events['time'].iloc[0]-1
        last_event_time = DS.events['time'].iloc[-1]+1

        # Slice TimeSeries based on the first and last event times
        mask = (DS.ecg.time >= first_event_time) & (
            DS.ecg.time <= last_event_time)

        if DS.ecg is not None:
            DS.ecg = DS.ecg.slicetime(first_event_time, last_event_time)

        if DS.br is not None:
            DS.br = DS.br.slicetime(first_event_time, last_event_time)

        if hasattr(DS, 'epoch'):
            DS.epoch = DS.epoch[mask]
            # Log the action
        DS.log_action('borderData', par)
        logger.info(
            f"Data sliced to the first and last events: {first_event_time} - {last_event_time}")

    return DS


def classify(data, par=None):
    """Performs the classification of IBIs based on the input R-top times.
    Classifies Inter-Beat Intervals (IBIs) based on statistical thresholds.

    Args:
        DataSet: The DataSet containing the ECG data and R-top times.
        par (dict, optional): Parameters for classification.

    Returns:
        classID (list): Classification of IBIs ('N', 'L', 'S', 'TL', 'SL', 'SNS').
    """
    default_par = {
        "Tw": 51,
        "Nsd": 4,
        "Tmax": 5
    }

    # Merge passed par with default if any
    par = {**default_par, **(par or {})}
    data.RTops = data.RTops.reset_index(drop=True)
    IBI = data.RTops['ibi'].reset_index(drop=True)

    # Calculate moving average and standard deviation
    avIBIr = pd.Series(IBI).rolling(
        window=par["Tw"], min_periods=1).mean().to_numpy()
    SDavIBIr = pd.Series(IBI).rolling(
        window=par["Tw"], min_periods=1).std().to_numpy()

    lower = avIBIr - (par["Nsd"] * SDavIBIr)
    higher = avIBIr + (par["Nsd"] * SDavIBIr)

    # Classifications based on thresholds
    for i in range(len(IBI)):
        if IBI[i] > higher[i]:
            data.RTops.at[i, 'ID'] = "L"  # Long IBI
        elif IBI[i] < lower[i]:
            data.RTops.at[i, 'ID'] = "S"  # Short IBI
        elif IBI[i] > par["Tmax"]:
            data.RTops.at[i, 'ID'] = "TL"  # Too Long

    # Short followed by long
    for i in range(len(data.RTops['ID']) - 1):
        if data.RTops.at[i, 'ID'] == "S" and data.RTops.at[i + 1, 'ID'] == "L":
            data.RTops.at[i, 'ID'] = "SL"  # Short-long sequence
        if i < len(data.RTops['ID']) - 2:
            if data.RTops.at[i, 'ID'] == "S" and data.RTops.at[i + 1, 'ID'] == "N" and data.RTops.at[i + 2, 'ID'] == "S":
                data.RTops.at[i, 'ID'] = "SNS"  # Short-normal-short sequence

    # Count occurrences of each ID
    id_counts = data.RTops['ID'].value_counts()
    for ids, count in id_counts.items():
        logger.info(f"Found {count} {ids} rtops")

    return data
