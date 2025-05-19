import os
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyxdf
import scipy

import spectHR as cs
from spectHR.Actions.csActions import classify
from spectHR.Actions.csBreathing import calculate_breathing_signal
from spectHR.Tools.Logger import logger
from spectHR.Tools.Webdav import copyWebdav


class TimeSeries:
    """
    A class to represent a time series with time and level data, along with optional sampling rate.

    Attributes:
    ----------
    time : pd.Series
        Timestamps of the time series.
    level : pd.Series
        Values corresponding to each timestamp.
    srate : float
        Sampling rate, calculated if not provided.

    Methods:
    -------
    slicetime(time_min, time_max):
        Returns a subset of the TimeSeries between specified time bounds.
    to_dataframe():
        Converts the TimeSeries to a Pandas DataFrame.
    """

    def __init__(self, x, y, srate=None):
        """
        Initializes the TimeSeries object.

        Args:
            x (iterable): Time values of the time series.
            y (iterable): Level values corresponding to each time value.
            srate (float, optional): Sampling rate. If not provided, it is calculated automatically.
        """
        self.time = pd.Series(x)
        self.level = pd.Series(y)

        # Automatically calculate sampling rate if not provided
        self.srate = srate if srate is not None else round(1.0 / self.time.diff().mean())

    def slicetime(self, time_min, time_max):
        """
        Returns a subset of the TimeSeries between specified time bounds.

        Args:
            time_min (float): Start of the time range.
            time_max (float): End of the time range.

        Returns:
            TimeSeries: A new TimeSeries object with data between the specified times.
            or the original series if slicing was not possible.
        """
        mask = (self.time >= time_min) & (self.time <= time_max)
        try:
            sliced = TimeSeries(self.time[mask], self.level[mask], self.srate)
        except Exception:  # noqa: E722
            sliced = TimeSeries(self.time, self.level, self.srate)
        return sliced

    def to_dataframe(self):
        """
        Converts the TimeSeries to a Pandas DataFrame.

        Returns:
            pd.DataFrame: DataFrame containing time, level, and sampling rate.
        """
        return pd.DataFrame({"time": self.time, "level": self.level, "srate": [self.srate] * len(self.time)})

class SpectHRDataset:
    """
    A class to represent a dataset containing ECG, breathing, and event data.

    Attributes:
    ----------
    ecg : TimeSeries
        The ECG data as a TimeSeries object.
    br : TimeSeries
        The breathing data as a TimeSeries object.
    events : pd.DataFrame
        A DataFrame containing event timestamps and labels.
    history : list
        A list of actions performed on the dataset.
    par : dict
        Parameters associated with various actions.
    starttime : float
        The start time of the dataset.

    Methods:
    -------
    loadData(filename, ecg_index=None, br_index=None, event_index=None):
        Loads data from an XDF file and initializes the dataset.
    log_action(action_name, params):
        Logs an action with its parameters into the dataset history.
    """

    def __init__(self, workspace, filename, ecg_index=None, br_index=None, event_index=None, par=None, reset=False, use_webdav=False, flip=False):
        """
        Initializes the SpectHRDataset by loading physiological data from a file.

        The constructor handles loading data from an XDF or raw text file, using cached pickle files when available.
        It also manages dataset parameters, directory structures, and optional WebDAV-based file retrieval.

        Args:
            filename (str):
                Path to the input file, which can be an XDF file containing multiple streams
                or a raw text file from a Polar device.
            ecg_index (int, optional):
                Index of the ECG (Electrocardiogram) stream in the XDF file. Defaults to None.
            br_index (int, optional):
                Index of the breathing (BR) stream in the XDF file. Defaults to None.
            event_index (int, optional):
                Index of the event stream in the XDF file. Defaults to None.
            par (dict, optional):
                Dictionary of initial parameters for the dataset. Defaults to an empty dictionary if None.
            reset (bool, optional):
                If True, forces reloading the data from the original source file instead of using a cached pickle file. Defaults to False.
            use_webdav (bool, optional):
                If True, attempts to download the file using WebDAV if it is not found locally. Defaults to False.
            flip (bool, optional):
                If True, flips the signal orientation for compatibility with certain data sources. Defaults to False.
        """
        # Initialize dataset attributes
        self.ecg = None  # ECG data
        
        if workspace == None:
            cwd = os.getcwd()
            workspace = {
                "DataDirectory": cwd,
                "CacheDirectory": os.path.join(cwd, "cache"),
                "OutputDirectory": cwd
            }
            
        self.workspace = workspace
        self.has_ecg = True
        self.br = None  # Breathing data
        self.bp = None  # Blood pressure data (if applicable)
        self.events = None  # Event markers: pandas dataframe with time and label as columns
        self.epochs = None  # Epochs from start and end events
        self.history = []  # History of processing steps
        self.par = par if par is not None else {}  # Dataset parameters
        self.starttime = None  # Start time of the recording
        
        self.toMatlab = False
        # Set up file paths and directories

        self.datadir = self.workspace['DataDirectory']  # Directory of the input file
        self.filename = os.path.basename(filename)  # Extract filename
        self.pkl_filename = os.path.splitext(self.filename)[0] + ".pkl"  # Name for cached pickle file
        self.file_path = os.path.join(self.datadir, self.filename)  # Full path to the input file

        # TODO this should be put in workspace code
        # Ensure a valid data directory
        if not self.datadir:
            self.datadir = os.getcwd()

        # Create a cache directory for storing preprocessed data
        cache_dir = self.workspace['CacheDirectory']

        if not os.path.isdir(cache_dir):
            logger.info(f'Creating cache dir: {cache_dir}')
            os.makedirs(cache_dir)
        # Path to the cached pickle file
        self.pkl_path = os.path.join(cache_dir, self.pkl_filename)
        # upto here
        # Fetch the file via WebDAV if needed
        if use_webdav:
            if not Path(self.file_path).exists():
                copyWebdav(self.file_path)

        # Load dataset from cache or process raw data (Real Raw (.txt) or XDF)
        if Path(self.pkl_path).exists() and not reset:
            logger.info(f"Loading dataset from pickle: {self.pkl_path}")
            self.load_from_pickle()
        elif self.file_path.endswith('.xdf') and Path(self.file_path).exists():
            logger.info(f"Loading dataset from XDF: {self.file_path}")
            self.loadData(self.file_path, ecg_index, br_index, event_index, flip=flip)
            self.save()
        elif self.file_path.endswith('.txt') and Path(self.file_path).exists():
            logger.info(f"Loading dataset from Raw Polar File: {self.file_path}")
            self.loadRawPolar(self.file_path, flip=flip)
            self.save()
        elif self.file_path.endswith('._csv') and Path(self.file_path).exists():
            logger.info(f"Loading dataset from Raw Harness File: {self.file_path}")
            self.loadRawHarness(self.file_path, flip=flip)
            self.save()
        elif self.file_path.endswith('.evt') and Path(self.file_path).exists():
            logger.info(f"Loading dataset from CARSPAN evt File: {self.file_path}")
            self.loadEVT(self.file_path)
            self.save()
        else:
            logger.error(f"File {self.file_path} was not found")

    def save(self):
        """
        Saves the current state of the dataset as a pickle file and optionally as a .mat file.
        """
        try:
            with open(self.pkl_path, "wb") as pkl_file:
                pickle.dump(self, pkl_file)
            logger.info(f"Dataset saved as pickle: {self.pkl_path}")
        except Exception as e:
            logger.error(f"Failed to save pickle file: {e}")

        if self.toMatlab:
            data_fields = {}

            # Save self.RTops
            if hasattr(self, 'RTops') and self.RTops is not None:
                rtops_data = self.RTops.copy()
                # Convert lists to arrays and ensure no None values
                if 'epoch' in rtops_data.columns:
                    rtops_data['epoch'] = rtops_data['epoch'].apply(lambda x: np.array([str(v) for v in x if v is not None]) if isinstance(x, (list, set)) else x)
                data_fields['RTops'] = rtops_data

            try:
                scipy.io.savemat(self.pkl_path + '.mat', data_fields)
                logger.info(f"Dataset saved as .mat file: {self.pkl_path}.mat")
            except Exception as e:
                logger.error(f"Failed to save .mat file: {e}")

    def loadEVT(self, filename):
        """
        Loads RTops from a CARSPAN .evt file and generates structured events for epochs.

        Args:
            filename (str): Path to the evt file.
        """
        cs.loadEVT(self, filename)
        self.create_epochs()
        
    def load_from_pickle(self):
        """
        Loads the dataset from a pickle file.
        """
        try:
            with open(self.pkl_path, "rb") as pkl_file:
                data = pickle.load(pkl_file)
            self.__dict__.update(data.__dict__)
            logger.info("Dataset loaded successfully from pickle")
        except Exception as e:
            logger.error(f"Failed to load pickle file: {e}")

    def loadRawPolar(self, filename, flip='auto'):
        """
        Loads raw Polar data from a CSV file into the dataset.

        Args:
            filename (str): Path to the Polar data file (CSV).
            flip (str or bool, optional): Determines whether to flip the ECG signal.
                'auto' will flip if the signal appears inverted based on a heuristic.
                True forces flipping, and False prevents it. Defaults to 'auto'.
        """
        logger.info('Loading Raw Polar Data')

        # Read raw data from CSV file
        rawdata = pd.read_csv(filename, sep=';')

        # Extract ECG levels and timestamps
        ecg_levels = rawdata.loc[:, "ecg [uV]"]
        ecg_timestamps = rawdata.loc[:, "timestamp [ms]"] / 1000.0  # Convert ms to seconds

        # Set the start time based on the 130th sample
        self.starttime = ecg_timestamps.iloc[0]
        ecg_timestamps -= self.starttime  # Normalize timestamps

        # Determine if the ECG signal needs to be flipped based on signal characteristics
        l = len(ecg_levels) // 3  # noqa: E741
        ml = ecg_levels.loc[l:2*l]
        magic = abs(np.mean(ml) - np.min(ml)) / (abs(np.mean(ml) - np.max(ml)))
        if (magic > 1.5 and flip == 'auto') or flip is True:
            ecg_levels = -ecg_levels

        # Store ECG data as a TimeSeries object
        self.ecg = TimeSeries(ecg_timestamps, ecg_levels)

        # Create event timestamps and labels
        event_timestamps = pd.Series([ecg_timestamps.iloc[0], ecg_timestamps.iloc[-1]])
        event_labels = pd.Series(['start series', 'stop series'])

        # Create DataFrame for events: this creates an epoch as large as the dataset
        eventlist = []
        ievents = pd.DataFrame({
            'time': event_timestamps,
            'label': event_labels
        })
        eventlist.append(ievents)

        # Concatenate events and store them
        self.events = pd.concat(eventlist, ignore_index=True)
        self.create_epochs()

    def loadRawHarness(self, filename, flip='auto'):
        """
        Loads raw data from a CSV file into the dataset.
        ref the Harness

        Args:
            filename (str): Path to the Polar data file (CSV).
            flip (str or bool, optional): Determines whether to flip the ECG signal.
                'auto' will flip if the signal appears inverted based on a heuristic.
                True forces flipping, and False prevents it. Defaults to 'auto'.
        """
        logger.info('Loading Raw New Harness Data')
        # Read raw data from CSV file
        rawdata = pd.read_csv(filename, sep=',')
        rawdata.columns = rawdata.columns.str.strip()  # This will remove any leading/trailing spaces
        # Extract ECG levels and timestamps
        ecg_levels = rawdata.loc[:, "ECG Data"].replace(-1, pd.NA).astype("float32") * 40
        rawdata['ms'] = rawdata['ms'].replace(-1, pd.NA).astype(float)
        rawdata['ms'] = rawdata['ms'].interpolate(method='linear')
        ecg_timestamps = rawdata.loc[:, "ms"] / 1000.0  # Convert ms to seconds
        self.starttime = ecg_timestamps.iloc[0]
        ecg_timestamps -= self.starttime  # Normalize timestamps

        # autodistance the time.
        timestamp_diff = np.diff(ecg_timestamps.dropna())  # Drop NA values for diff calculation

        # Calculate the median difference
        median_diff = np.median(timestamp_diff)
        n = len(ecg_timestamps)
        start = 0
        end = start + median_diff * (n - 1)

        ecg_timestamps = pd.Series(np.arange(start, end + median_diff, median_diff))

        # Determine if the ECG signal needs to be flipped based on signal characteristics
        l = len(ecg_levels) // 3  # noqa: E741
        ml = ecg_levels.loc[l:2*l]
        magic = abs(np.mean(ml) - np.min(ml)) / (abs(np.mean(ml) - np.max(ml)))
        if (magic > 1.5 and flip == 'auto') or flip is True:
            ecg_levels = -ecg_levels

        # Store ECG data as a TimeSeries object
        self.ecg = TimeSeries(ecg_timestamps, ecg_levels - ecg_levels.mean())

        # Create event timestamps and labels
        event_timestamps = pd.Series([ecg_timestamps.iloc[0], ecg_timestamps.iloc[-1]])
        event_labels = pd.Series(['start series', 'stop series'])

        # Create DataFrame for events: this creates an epoch as large as the dataset
        eventlist = []
        ievents = pd.DataFrame({
            'time': event_timestamps,
            'label': event_labels
        })
        eventlist.append(ievents)

        # Concatenate events and store them
        self.events = pd.concat(eventlist, ignore_index=True)
        self.create_epochs()

    def loadData(self, filename, ecg_index=None, br_index=None, bp_index=None, event_index=None, flip='auto'):
        """
        Loads data from an XDF file into the dataset.

        Args:
            filename (str): Path to the XDF file.
            ecg_index (int, optional): Index of the ECG stream in the XDF file. Defaults to None.
            br_index (int, optional): Index of the breathing stream in the XDF file. Defaults to None.
            event_index (int, optional): Index of the event stream in the XDF file. Defaults to None.
        """
        rawdata, _ = pyxdf.load_xdf(filename)

        # Identify ECG stream automatically if not provided:
        if ecg_index is None:
            ecg_index = next((i for i, d in enumerate(rawdata) if d['info']['type'][0].startswith('ECG') and d['info']['effective_srate'] > 0), None)
            if ecg_index is None:
                logger.info("There is no stream named 'Polar'")

        # Identify accelerometer stream for breathing automatically if not provided
        if br_index is None:
            br_index = next((i for i, d in enumerate(rawdata) if d['info']['type'][0].startswith('Acc') and d['info']['effective_srate'] > 0), None)
            if br_index is None:
                logger.info("There is no stream named 'Accelerometer'")

        # Identify event stream automatically if not provided
        if event_index is None:
            event_index = [i for i, d in enumerate(rawdata) if 'Markers' in d['info']['type']]
            if event_index is None:
                logger.info("There is no stream of type 'Markers'")

        # Load ECG data
        if ecg_index is not None:
            ecg_timestamps = pd.Series(rawdata[ecg_index]["time_stamps"])
            self.starttime = ecg_timestamps[0]  # Set dataset start time

            ecg_levels = pd.Series(rawdata[ecg_index]["time_series"].flatten())
            ecg_timestamps -= self.starttime
            # Pragmatic approach. Might do better. This flips the signal if it thinks it needs to...
            magic = abs(np.mean(ecg_levels) - np.min(ecg_levels)) / (abs(np.mean(ecg_levels) - np.max(ecg_levels)))
            if (magic > 1.5 and flip == 'auto') or flip:
                ecg_levels = -ecg_levels

            self.ecg = TimeSeries(ecg_timestamps, ecg_levels)

        # Load breathing data
        if br_index is not None:
            logger.info("Expecting Breathing data")
            br_timestamps = pd.Series(rawdata[br_index]["time_stamps"])
            br_data = rawdata[br_index]["time_series"]
            br_levels = calculate_breathing_signal(br_data, 200)
            br_timestamps -= self.starttime
            self.br = TimeSeries(br_timestamps, br_levels)

        # Load bloodpressure data
        if bp_index is not None:
            logger.info("Expecting Bloodpressure data")
            bp_timestamps = pd.Series(rawdata[bp_index]["time_stamps"])
            bp_levels = pd.Series(rawdata[bp_index]["time_series"].flatten())
            bp_timestamps -= self.starttime

            self.bp = TimeSeries(bp_timestamps, bp_levels)

        # Load event data
        if event_index is not None:
            eventlist = []
            for index in event_index:
                event_timestamps = pd.Series(rawdata[index]["time_stamps"])
                event_labels = pd.Series(rawdata[index]["time_series"])
                event_labels = event_labels.apply(lambda x: x[0])
                ievents = pd.DataFrame({
                    'time': event_timestamps - self.starttime,
                    'label': event_labels
                })
                eventlist.append(ievents)
            self.events = pd.concat(eventlist, ignore_index=True)
            self.create_epochs()
            
        if self.epochs.empty:
            eventlist = [pd.DataFrame({
                'time': [ecg_timestamps.iloc[1]],
                'label': ['start All']
            })]
            eventlist.append(pd.DataFrame({
                'time': [ecg_timestamps.iloc[-1]],
                'label': ['stop All']
            }))
            self.events = pd.concat(eventlist, ignore_index=True)
            self.create_epochs()

    @staticmethod
    def log_error(message):
        """
        Logs an error message.

        Args:
            message (str): The error message to log.
        """
        logger.error(message)

    def create_epochs(self):
        """
        Creates a DataFrame of epochs based on the start and stop events in the dataset.
        The DataFrame contains the following columns:
        - 'label': The name of the epoch.
        - 'starttime': The start time of the epoch.
        - 'endtime': The end time of the epoch.
        """

        # Check for no events and then return
        if self.events is None:
            self.log_error('No events available for epoch generation')
            return

        # Replace 'end ' with 'stop ' in the 'label' column (case-insensitive)
        self.events['label'] = self.events['label'].str.replace('^end ', 'stop ', case=False, regex=True)

        # Separate start and stop events (case-insensitive)
        start_events = self.events[self.events['label'].str.lower().str.startswith('start')].copy()
        stop_events = self.events[self.events['label'].str.lower().str.startswith('stop')].copy()

        # Extract epoch names (case-insensitive)
        start_events.loc[:, 'label'] = start_events['label'].str.replace('^start ', '', case=False, regex=True)
        stop_events.loc[:, 'label'] = stop_events['label'].str.replace('^stop ', '', case=False, regex=True)

        # Initialize epochs list
        epochs = []

        # Iterate over start events
        for _, start_event in start_events.iterrows():
            epoch = start_event['label']
            start_time = start_event['time']

            # Find corresponding stop event
            stop_event = stop_events[stop_events['label'].str.lower() == epoch.lower()]

            if not stop_event.empty:
                end_time = stop_event.iloc[0]['time']
            else:
                # Find the next event's start time
                next_event = self.events[self.events['time'] > start_time].sort_values('time').iloc[0]
                end_time = next_event['time']

            epochs.append({'label': epoch.lower(), 'starttime': start_time, 'endtime': end_time})

        # Create epochs DataFrame
        self.epochs = pd.DataFrame(epochs)

 
    def add_epoch_to_dataset(self, epoch_label, start_time, end_time):
        """
        Add a new epoch to the dataset.

        Args:
            epoch_label (str): The label for the new epoch.
            start_time (float): The start time for the new epoch.
            end_time (float): The end time for the new epoch.
        """
        self.epochs.loc[len(self.epochs)] = [epoch_label.lower(), start_time, end_time]

    def log_action(self, action_name, params):
        """
        Logs an action performed on the dataset.

        Args:
            action_name (str): Name of the action.
            params (dict): Parameters associated with the action.
        """
        self.history.append({'action': action_name, 'timestamp': datetime.now(), 'parameters': params})
        logger.info(f"Action logged: {action_name} with parameters {params}")