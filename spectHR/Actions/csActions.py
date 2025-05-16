import copy

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
        'fSample': 130,          # Sampling frequency (Hz)
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
    par['MinPeakHeight'] = np.nanmedian(DS.ecg.level) + (1.5 * np.nanstd(DS.ecg.level))

    # Step 2: Convert MinPeakDistance from milliseconds to samples using the sampling frequency
    MinPeakDistance = ((par['MinPeakDistance'] / 1000) * par['fSample'])

    # Step 3: Detect peaks in the ECG signal using scipy's find_peaks method
    # 'height' specifies the minimum peak height, and 'distance' ensures peaks are spaced apart
    locs, props = signal.find_peaks(DS.ecg.level, height=par['MinPeakHeight'], distance=MinPeakDistance)
    
    # Step 4: Store the values of the ECG signal at the detected peak locations
    vals = DS.ecg.level.iloc[locs].array
    pre  = DS.ecg.level.iloc[locs-1].array
    post = DS.ecg.level.iloc[locs+1].array
    # Step 5: Calculate the rate of change (rc) before and after each peak
    # This gives insight into the sharpness of the peak (the difference between the peak and neighboring points)
    rc_before = np.abs(vals - pre)  # Difference with previous point
    rc_after = np.abs(post - vals)   # Difference with next point
    rc = np.maximum(rc_before, rc_after)  # Take the maximum of the two rates of change

    # Step 6: Optionally apply corrections to the peak times (uncomment if needed)
    correction = (post - pre) / par['fSample'] / 2.0 / np.abs(rc)
    
    # Print the number of detected R-tops for logging purposes
    logger.info(f"Found {len(locs)} r-tops")

    # Step 7: Update the DataSet's RTopTimes with the time stamps corresponding to the detected peaks
    DS.RTops = pd.DataFrame({'time': (DS.ecg.time.iloc[locs] + correction).tolist()})
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

def loadEVT(DataSet, filename):
    """
    Loads RTops from a CARSPAN .evt file and generates structured events for epochs.

    Args:
        filename (str): Path to the evt file.
        DataSet (CarspanDataSet): The DataSet object to be updated.
    """
    logger.info('Loading CARSPAN EVT RTops')
    DataSet.has_ecg = False

    # Step 1: Read only [Data] section
    with open(filename, 'r') as f:
        lines = f.readlines()

    data_section = False
    event_codes = []
    times = []

    for line in lines:
        if line.strip() == "[Data]":
            data_section = True
            continue
        if not data_section:
            continue

        parts = line.strip().split()
        if len(parts) >= 2:
            try:
                code = int(parts[0])
                time = float(parts[1])
                event_codes.append(code)
                times.append(time)
            except ValueError:
                continue  # Skip malformed lines

    df = pd.DataFrame({'event_code': event_codes, 'time': times})

    # Step 2: Extract RTops (event_code == 1)
    rtops = df[df['event_code'] == 1].copy()
    rtops.reset_index(drop=True, inplace=True)
    rtops['ibi'] = np.append(np.diff(rtops['time']), np.nan)
    rtops['epoch'] = [set([''])] * len(rtops)

    DataSet.RTops = rtops[['time', 'ibi']]
    DataSet.RTops['ID'] = 'N'

    # Step 3: Extract start and end codes (11 and 21)
    start_times = df[df['event_code'] == 11]['time'].tolist()
    end_times = df[df['event_code'] == 21]['time'].tolist()

    if len(start_times) != len(end_times):
        raise ValueError("Mismatched number of start (11) and end (21) codes.")

    # Step 4: Build structured events
    event_timestamps = []
    event_labels = []
    # Create events for each epoch
    for i, (start, end) in enumerate(zip(start_times, end_times), 1):
        event_timestamps.extend([start, end])
        event_labels.extend([f'start series {i}', f'stop series {i}'])

    DataSet.events = pd.DataFrame({
        'time': pd.Series(event_timestamps),
        'label': pd.Series(event_labels)
    })

    if rtops.empty:
        raise ValueError("No RTops found in file.")

    ecg_timestamps = rtops['time']
    ecg_levels = 1000.0 / rtops['ibi']

    DataSet.ecg = cs.TimeSeries(ecg_timestamps, ecg_levels)
   
    # Step 5: Classify the RTops
    classify(DataSet)

    # Initialize epochs
    DataSet.create_epochs()
 

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
    logger.info(f'creating a filter with order {N} , passband at {passband*nyquist}')
    # Example: lowpass or highpass filter
    if par['filterType'] == 'lowpass':
        #b, a = signal.butter(par['order'], normal_cutoff, btype='low', analog=False)
        b, a = signal.butter(N, wn, btype='low', analog=False)
    elif par['filterType'] == 'highpass':
        #b, a = signal.butter(par['order'], normal_cutoff, btype='high', analog=False)
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
    logger.info(f"Data filtered with a {par['filterType']} filter (cutoff = {par['cutoff']} Hz).")
    return DS



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
        mask = (DS.ecg.time >= first_event_time) & (DS.ecg.time <= last_event_time)

        if DS.ecg is not None:
            DS.ecg = DS.ecg.slicetime(first_event_time, last_event_time)

        if DS.br is not None:
            DS.br = DS.br.slicetime(first_event_time, last_event_time)
        
        if hasattr(DS, 'epoch'):
            DS.epoch = DS.epoch[mask]
            # Log the action
        DS.log_action('borderData', par)
        logger.info(f"Data sliced to the first and last events: {first_event_time} - {last_event_time}")

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
    avIBIr = pd.Series(IBI).rolling(window=par["Tw"]).mean().to_numpy()
    SDavIBIr = pd.Series(IBI).rolling(window=par["Tw"]).std().to_numpy()

    lower = avIBIr - (par["Nsd"] * SDavIBIr)
    higher = avIBIr + (par["Nsd"] * SDavIBIr)

    # Classifications based on thresholds
    for i in range(len(IBI)):
        if IBI[i] > higher[i]:
            data.RTops.at[i,'ID'] = "L"  # Long IBI
        elif IBI[i] < lower[i]:
            data.RTops.at[i,'ID'] = "S"  # Short IBI
        elif IBI[i] > par["Tmax"]:
            data.RTops.at[i,'ID'] = "TL"  # Too Long

    # Short followed by long
    for i in range(len(data.RTops['ID']) - 1):
        if data.RTops.at[i,'ID'] == "S" and data.RTops.at[i + 1,'ID'] == "L":
            data.RTops.at[i,'ID'] = "SL"  # Short-long sequence
        if i < len(data.RTops['ID']) - 2:
            if data.RTops.at[i,'ID'] == "S" and data.RTops.at[i + 1,'ID'] == "N" and data.RTops.at[i + 2,'ID'] == "S":
                data.RTops.at[i,'ID'] = "SNS"  # Short-normal-short sequence

    # Count occurrences of each ID
    id_counts = data.RTops['ID'].value_counts()
    for ids, count in id_counts.items():
        logger.info(f"Found {count} {ids} rtops")
    
    return data

