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


def _compute_RSP_signal(
    acc: np.ndarray,
    fs: float,
    *,
    # Gravity / orientation tracking (very low frequency)
    gravity_cutoff_hz: float = 0.04,
    gravity_order: int = 2,
    # Respiration band (typical adult: ~0.1–0.7 Hz; tune to your paradigm)
    rsp_band_hz: tuple[float, float] = (0.10, 0.70),
    rsp_order: int = 4,
    # Robustness
    winsorize_z: float | None = 8.0,
    nan_policy: str = "interp",
    # Output scaling
    zscore: bool = True,
    return_diagnostics: bool = False,
) -> np.ndarray | tuple[np.ndarray, dict]:
    """
    Extract a respiration surrogate signal from Nx3 chest-belt accelerometer data.

    Pipeline
    --------
    1) Robust cleanup (NaNs, extreme spikes)
    2) Estimate gravity via low-pass and subtract (linear acceleration)
    3) Bandpass linear acceleration to respiration band
    4) PCA (first principal component) on bandpassed 3D signal to obtain a 1D respiration surrogate
    5) Optional z-score normalization

    Parameters
    ----------
    acc:
        Array shaped (N, 3). Units do not matter (g or m/s^2) as long as consistent.
    fs:
        Sampling rate in Hz.
    gravity_cutoff_hz:
        Low-pass cutoff for gravity/orientation estimate. Lower => smoother orientation tracking.
        0.02–0.08 Hz are typical for chest belts.
    rsp_band_hz:
        Bandpass (low, high) in Hz for respiration motion.
    gravity_order, rsp_order:
        Butterworth filter orders. We use SOS + filtfilt for stability/zero-phase.
    winsorize_z:
        If not None: clip each axis to median ± winsorize_z * MAD-based sigma (robust).
        Helps with bumps/impacts.
    nan_policy:
        "interp" to linearly interpolate NaNs per axis; "raise" to error; "omit" to fill with 0.
    zscore:
        If True, return a standardized signal (mean 0, std 1).
    return_diagnostics:
        If True, also return a dict with intermediate info (PC vector, explained variance, etc.).

    Returns
    -------
    rsp:
        1D numpy array (N,) respiration surrogate.
    diagnostics (optional):
        Dict with keys: "pc1", "explained_var", "gravity", "lin_acc", "band3".

    Notes
    -----
    - If the belt orientation changes slowly, gravity removal + PCA is generally robust.
    - If there are large posture changes, consider segment-wise PCA (e.g., per epoch) using the same code.
    """
    acc = np.asarray(acc, dtype=float)
    if acc.ndim != 2 or acc.shape[1] != 3:
        raise ValueError(f"`acc` must have shape (N, 3). Got {acc.shape}.")
    if fs <= 0:
        raise ValueError("`fs` must be > 0.")

    # ---------- helpers ----------
    def _interp_nans(x: np.ndarray) -> np.ndarray:
        if not np.isnan(x).any():
            return x
        n = x.size
        idx = np.arange(n)
        good = ~np.isnan(x)
        if good.sum() < 2:
            # not enough data to interpolate meaningfully
            return np.zeros_like(x)
        return np.interp(idx, idx[good], x[good])

    def _robust_winsorize_axis(x: np.ndarray, z: float) -> np.ndarray:
        # robust sigma via MAD
        med = np.median(x)
        mad = np.median(np.abs(x - med))
        # 1.4826 * MAD ≈ std for normal
        sigma = 1.4826 * mad if mad > 0 else np.std(x)
        if sigma <= 0:
            return x
        lo = med - z * sigma
        hi = med + z * sigma
        return np.clip(x, lo, hi)

    def _butter_sos(kind: str, cutoff, order: int):
        from scipy.signal import butter

        nyq = 0.5 * fs
        if kind == "low":
            wn = float(cutoff) / nyq
            if not (0 < wn < 1):
                raise ValueError("gravity_cutoff_hz must be between 0 and Nyquist.")
            return butter(order, wn, btype="low", output="sos")
        elif kind == "band":
            lo, hi = cutoff
            lo = float(lo) / nyq
            hi = float(hi) / nyq
            if not (0 < lo < hi < 1):
                raise ValueError(
                    "rsp_band_hz must be within (0, Nyquist) and low < high."
                )
            return butter(order, [lo, hi], btype="bandpass", output="sos")
        else:
            raise ValueError("Unsupported filter kind.")

    def _sos_filtfilt(sos, x: np.ndarray) -> np.ndarray:
        from scipy.signal import sosfiltfilt

        # sosfiltfilt will complain if too short; fail gracefully
        if x.size < max(3 * (sos.shape[0] * 2 + 1), 15):
            # fallback: no filtering (or you could do sosfilt)
            return x.copy()
        return sosfiltfilt(sos, x)

    # ---------- 1) NaNs + winsorize ----------
    acc2 = acc.copy()
    for k in range(3):
        if nan_policy == "interp":
            acc2[:, k] = _interp_nans(acc2[:, k])
        elif nan_policy == "omit":
            acc2[:, k] = np.nan_to_num(acc2[:, k], nan=0.0)
        elif nan_policy == "raise":
            if np.isnan(acc2[:, k]).any():
                raise ValueError(
                    "NaNs present in acc; set nan_policy='interp' or 'omit'."
                )
        else:
            raise ValueError("nan_policy must be 'interp', 'omit', or 'raise'.")

    if winsorize_z is not None:
        z = float(winsorize_z)
        for k in range(3):
            acc2[:, k] = _robust_winsorize_axis(acc2[:, k], z)

    # ---------- 2) gravity estimate + removal ----------
    sos_g = _butter_sos("low", gravity_cutoff_hz, gravity_order)
    gravity = np.column_stack([_sos_filtfilt(sos_g, acc2[:, k]) for k in range(3)])
    lin_acc = acc2 - gravity

    # ---------- 3) bandpass to respiration band ----------
    sos_rsp = _butter_sos("band", rsp_band_hz, rsp_order)
    band3 = np.column_stack([_sos_filtfilt(sos_rsp, lin_acc[:, k]) for k in range(3)])

    # ---------- 4) PCA on bandpassed 3D signal ----------
    # Center
    X = band3 - band3.mean(axis=0, keepdims=True)

    # Covariance + eigendecomposition (3x3 => cheap, stable)
    C = (X.T @ X) / max(X.shape[0] - 1, 1)
    evals, evecs = np.linalg.eigh(C)  # ascending
    order = np.argsort(evals)[::-1]
    evals = evals[order]
    evecs = evecs[:, order]
    pc1 = evecs[:, 0]

    rsp = X @ pc1

    # Optional: enforce consistent sign (purely cosmetic)
    # Make rsp positively correlated with the axis that has largest loading magnitude
    main_axis = int(np.argmax(np.abs(pc1)))
    if np.corrcoef(rsp, X[:, main_axis])[0, 1] < 0:
        rsp = -rsp
        pc1 = -pc1

    # ---------- 5) scale ----------
    if zscore:
        s = np.std(rsp)
        rsp = (rsp - np.mean(rsp)) / (s if s > 0 else 1.0)

    if not return_diagnostics:
        return rsp

    explained = float(evals[0] / evals.sum()) if evals.sum() > 0 else 0.0
    diag = {
        "pc1": pc1,  # 3-vector loadings
        "explained_var": explained,  # fraction of variance explained by PC1 in band
        "gravity": gravity,  # Nx3
        "lin_acc": lin_acc,  # Nx3
        "band3": band3,  # Nx3
        "main_axis": main_axis,
        "rsp_band_hz": rsp_band_hz,
        "gravity_cutoff_hz": gravity_cutoff_hz,
    }
    return rsp, diag


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
        - stype contains "markers" or "event"
        - skip if name starts with "cam"
        - normalize "end <label>" → "stop <label>"

    """

    logger.info(f"Loading XDF: {filename}")
    streams, _ = pyxdf.load_xdf(filename)

    device_counter = {}  # device_prefix → index starting at 1

    for stream in streams:
        info = stream.get("info", {})
        name = str(info.get("name", [""])[0])
        stype = str(info.get("type", [""])[0])
        logger.debug(f"{name} (type={stype})")
        try:
            srate = float(info.get("nominal_srate", [0])[0])
        except Exception:
            srate = 0.0

        name_lower = name.lower()
        is_polar = name_lower.startswith("polar")

        # ------------------------------------------------------------
        # MARKER STREAMS
        # ------------------------------------------------------------
        if (
            "event" in stype.lower() or "marker" in stype.lower()
        ) and not name_lower.startswith("cam"):
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
        data = np.asarray(stream["time_series"], dtype=float)
        physiodata.has_ecg = True
        # Ensure 2-D shape
        if data.ndim == 1:
            data = data[:, None]

        # Device prefix: everything before _ecg / _acc
        device_prefix = name.rsplit("_", 1)[0]

        # Assign index
        if device_prefix not in device_counter:
            device_counter[device_prefix] = len(device_counter) + 1

        # idx = device_counter[device_prefix]
        # suffix = "" if idx == 1 else f"-{idx}"
        suffix = f"-[{device_prefix[-8:]}]"

        # ------------------------------------------------------------
        # ECG STREAM
        # ------------------------------------------------------------
        if not name_lower.endswith("_acc"):
            values = data[:, 0] if data.ndim == 2 else data
            ecg_name = f"ecg{suffix}"
            physiodata.timeseries[ecg_name] = TimeSeries(times, values)
            polarity = physiodata.timeseries[ecg_name].detect_ecg_polarity()
            if polarity == "inverted":
                physiodata.timeseries[ecg_name].flip()
                logger.info(
                    f"Loaded ECG → {ecg_name}, detected polarity: {polarity}, corrected polarity"
                )
            else:
                logger.info(f"Loaded ECG → {ecg_name}, detected polarity: {polarity}")
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
            bp_name = f"RSP{suffix}"
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
