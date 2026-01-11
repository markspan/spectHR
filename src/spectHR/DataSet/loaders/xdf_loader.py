from __future__ import annotations

import numpy as np
import pyxdf

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.loaders.registry import register_loader
from spectHR.Tools.Logger import logger

# ------------------------------------------------------------
# INTERNAL: 3-axis Respiration signal computation
# ------------------------------------------------------------

def _compute_RSP_signal(acc: np.ndarray, fs: float) -> np.ndarray:
    """
    Extract a respiratory signal from Nx3 accelerometer data.
    Identical to your previous implementation.
    """
    from scipy.signal import butter, filtfilt

    NYQUIST = 0.5 * fs
    GRAVITY_CUTOFF = 0.04   # Hz
    NOISE_CUTOFF   = 0.5    # Hz
    ORDER = 2

    # Gravity filtering
    b_grav, a_grav = butter(ORDER, GRAVITY_CUTOFF / NYQUIST, btype="low")
    acc = acc.copy()
    for axis in range(3):
        acc[:, axis] -= filtfilt(b_grav, a_grav, acc[:, axis])

    # Dynamic norm
    dyn = np.linalg.norm(acc, axis=1)

    # Noise filtering
    b_noise, a_noise = butter(ORDER, NOISE_CUTOFF / NYQUIST, btype="low")
    return filtfilt(b_noise, a_noise, dyn)


# ------------------------------------------------------------
# XDF LOADER
# ------------------------------------------------------------

@register_loader(".xdf")
def load_xdf(physiodata, filename: str, **kwargs) -> None:
    """
    Timeseries:
        - Only load streams whose name.lower().startswith("polar")
        - *_ecg → ECG time series
        - *_acc → compute RSP + store ACC raw

    Markers:
        - stype contains "markers"
        - skip if name starts with "cam"
        - normalize "end <label>" → "stop <label>"

    """

    logger.info(f"Loading XDF: {filename}")
    streams, _ = pyxdf.load_xdf(filename)

    device_counter = {}  # device_prefix → index starting at 1

    for stream in streams:
        info  = stream.get("info", {})
        name  = str(info.get("name", [""])[0])
        stype = str(info.get("type", [""])[0])
        logger.debug(f"{name} (type={stype})")
        try:
            srate = float(info.get("nominal_srate", [0])[0])
        except Exception:
            srate = 0.0

        name_lower = name.lower()
        is_polar   = name_lower.startswith("polar")

        # ------------------------------------------------------------
        # MARKER STREAMS
        # ------------------------------------------------------------
        if ("markers" in stype.lower()) and not name_lower.startswith("cam"):
            raw_times = np.asarray(stream["time_stamps"], dtype=float)
            raw_labels = []

            for row in stream["time_series"]:
                label = str(row[0])
                # normalize
                if label.lower().startswith("end "):
                    label = "stop " + label[4:]
                raw_labels.append(label)

            physiodata.events[name] = EventSeries(raw_times, raw_labels)
            logger.info(f"Loaded EventSeries: {name}")
            continue

        # ------------------------------------------------------------
        # NON-POLAR or NON-TIMESERIES
        # ------------------------------------------------------------
        if not is_polar or srate <= 0:
            continue

        # Now we know: this is POLAR data
        times = np.asarray(stream["time_stamps"], dtype=float)
        data  = np.asarray(stream["time_series"], dtype=float)
        physiodata.has_ecg = True
        # Ensure 2-D shape
        if data.ndim == 1:
            data = data[:, None]

        # Device prefix: everything before _ecg / _acc
        device_prefix = name.rsplit("_", 1)[0]

        # Assign index
        if device_prefix not in device_counter:
            device_counter[device_prefix] = len(device_counter) + 1

        #idx = device_counter[device_prefix]
        #suffix = "" if idx == 1 else f"-{idx}"
        suffix = f"-[{device_prefix[-8:]}]"

        # ------------------------------------------------------------
        # ECG STREAM
        # ------------------------------------------------------------
        if not name_lower.endswith("_acc"):
            values = data[:, 0] if data.ndim == 2 else data
            ecg_name = f"ecg{suffix}"
            physiodata.timeseries[ecg_name] = TimeSeries(times, values)
            logger.info(f"Loaded ECG → {ecg_name}")
            continue

        # ------------------------------------------------------------
        # ACC STREAM → RSP
        # ------------------------------------------------------------
        if name_lower.endswith("_acc"):
            if data.shape[1] != 3:
                logger.warning(f"ACC stream {name} does not have 3 channels. Skipped.")
                continue

            diffs = np.diff(times)
            diffs = diffs[diffs > 0]
            if len(diffs) == 0:
                logger.warning(f"ACC stream {name} has invalid timestamps.")
                continue

            fs = 1.0 / np.mean(diffs)

            RSP = _compute_RSP_signal(data, fs)
            bp_name   = f"RSP{suffix}"
            physiodata.timeseries[bp_name] = TimeSeries(times, RSP)
            logger.info(f"Loaded Respiration signal → {bp_name}")


    if not physiodata.timeseries:
        logger.warning("No usable Polar time series found.")
    else:
        _index_polar_bands(physiodata)
        logger.info("indexed the bands")

def _index_polar_bands(dataset):
    bands = {}

    for name in dataset.timeseries:
        if name.startswith(("ecg-[", "RSP-[")):
            band = name.split("[")[-1].rstrip("]")
            bands.setdefault(band, {})

            if name.startswith("ecg"):
                bands[band]["ecg"] = name
            elif name.startswith("RSP"):
                bands[band]["rsp"] = name

    dataset.band_map = bands
    dataset.active_band = next(iter(bands), None)
