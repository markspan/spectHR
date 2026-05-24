# spectHR/Tools/RespirationSegmentation.py
"""
Standalone respiration-phase segmentation algorithm.

The segmentation logic was previously embedded in
``RespirationSeries.from_timeseries``.  Extracting it here makes the
algorithm independently testable and importable without constructing a
``RespirationSeries`` object or pulling in the full DataSet layer.

Public surface
--------------
segment_respiration(rsp, *, ...) -> tuple[np.ndarray, np.ndarray, np.ndarray]
    Detect INH/EXH phases from a respiration TimeSeries-like.

``RespirationSeries.from_timeseries`` is a thin wrapper that calls this
function and wraps the result in a ``RespirationSeries``; existing call
sites need no changes.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from scipy.signal import butter, sosfiltfilt, savgol_filter, find_peaks, buttord

from spectHR.Tools.Logger import logger


__all__ = ["segment_respiration"]


def segment_respiration(
    rsp,
    *,
    prefilter_cutoff_hz: float = 2.0,
    prefilter_order: Optional[int] = None,
    min_phase_duration: float = 2.0,
    smooth: bool = True,
    smoothing_window: int = 31,
    polyorder: int = 3,
    prominence: Optional[float] = None,
    prominence_rel: float = 0.55,
    min_amplitude: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Detect respiration phases (INH/EXH) from a respiration signal.

    Parameters
    ----------
    rsp : TimeSeries-like
        Object with ``.times`` and ``.values`` attributes, both 1-D float
        arrays of the same length.
    prefilter_cutoff_hz : float
        Low-pass filter cutoff in Hz applied before smoothing (default 2 Hz).
    prefilter_order : int or None
        Butterworth filter order.  Auto-estimated via ``buttord`` when None.
    min_phase_duration : float
        Minimum duration of an accepted INH or EXH phase in seconds (default 2 s).
    smooth : bool
        Whether to apply Savitzky-Golay smoothing after low-pass filtering.
    smoothing_window : int
        Savitzky-Golay window length in samples (must be odd, ≥ 5).
    polyorder : int
        Savitzky-Golay polynomial order.
    prominence : float or None
        Peak prominence threshold for ``scipy.signal.find_peaks``.  When None,
        estimated from the signal's MAD: ``prominence_rel × 1.4826 × MAD``.
    prominence_rel : float
        Multiplier applied to the MAD-based sigma when ``prominence`` is None.
    min_amplitude : float or None
        Minimum peak-to-trough amplitude for a phase to be retained.  None
        disables the amplitude gate.

    Returns
    -------
    starts : np.ndarray, dtype float
        Phase start times (seconds).
    ends : np.ndarray, dtype float
        Phase end times (seconds).
    labels : np.ndarray, dtype object
        Phase labels: ``"INH"`` (trough → peak) or ``"EXH"`` (peak → trough).

    All three arrays are empty when the signal is too short, degenerate, or
    no phases survive the duration / amplitude thresholds.

    Algorithm
    ---------
    0. Low-pass filter the raw signal at *prefilter_cutoff_hz*.
    1. Optional Savitzky-Golay smoothing (preserves extrema well).
    2. Detect peaks and troughs using ``find_peaks`` with the prominence
       threshold; both arrays share the same ``min_phase_duration`` distance.
    3. Merge into a time-sorted extrema sequence and enforce strict
       peak/trough alternation (keep the dominant extremum when two of the
       same type appear consecutively).
    4. Build phases: trough → peak = INH, peak → trough = EXH.  Reject
       any phase shorter than *min_phase_duration* or below *min_amplitude*.
    """
    _empty: Tuple[np.ndarray, np.ndarray, np.ndarray] = (
        np.asarray([], dtype=float),
        np.asarray([], dtype=float),
        np.asarray([], dtype=object),
    )

    times  = np.asarray(rsp.times,  dtype=float)
    values = np.asarray(rsp.values, dtype=float)

    n = times.size
    if n < 5:
        logger.warning("RSP TimeSeries too short for respiration phase extraction.")
        return _empty

    dt = np.diff(times)
    dt = dt[(dt > 0) & np.isfinite(dt)]
    if dt.size == 0:
        logger.warning("Invalid timestamps (non-increasing or non-finite).")
        return _empty

    fs  = 1.0 / float(np.median(dt))
    nyq = 0.5 * fs

    # Step 0 — low-pass prefilter
    if prefilter_order is None:
        prefilter_order, _ = buttord(
            prefilter_cutoff_hz * 0.9,
            prefilter_cutoff_hz * 1.1,
            1.0,
            7,
            analog=False,
            fs=fs,
        )

    y0 = values.astype(float, copy=True)
    fc = min(float(prefilter_cutoff_hz), 0.95 * nyq)
    if fc <= 0:
        raise ValueError("prefilter_cutoff_hz must be > 0.")
    sos = butter(int(prefilter_order), fc / nyq, btype="low", output="sos")
    min_filtfilt_len = max(3 * (2 * sos.shape[0] + 1), 15)
    y_lp = sosfiltfilt(sos, y0) if y0.size >= min_filtfilt_len else y0

    # Step 1 — Savitzky-Golay smoothing
    if smooth:
        w = int(smoothing_window)
        w = max(w, 5)
        if w % 2 == 0:
            w += 1
        if w >= y_lp.size:
            w = y_lp.size - 1 if (y_lp.size - 1) % 2 == 1 else y_lp.size - 2
        w = max(w, 5)
        if w != smoothing_window:
            logger.debug(
                "Savitzky-Golay smoothing_window adjusted: %d → %d "
                "(signal length %d).",
                smoothing_window, w, y_lp.size,
            )
        p = max(2, min(int(polyorder), w - 2))
        y = savgol_filter(y_lp, window_length=w, polyorder=p, mode="interp")
    else:
        y = y_lp

    # Step 2 — peak / trough detection
    min_dist = int(max(1, round(min_phase_duration * fs)))
    if prominence is None:
        med   = np.median(y)
        mad   = np.median(np.abs(y - med))
        sigma = 1.4826 * mad if mad > 0 else float(np.std(y))
        if sigma <= 0:
            logger.warning("RSP signal is near-constant; cannot extract phases.")
            return _empty
        prominence = float(prominence_rel * sigma)

    peaks,   _ = find_peaks( y, distance=min_dist, prominence=prominence)
    troughs, _ = find_peaks(-y, distance=min_dist, prominence=prominence)

    if peaks.size == 0 or troughs.size == 0:
        logger.warning("No reliable peaks/troughs detected for respiration segmentation.")
        return _empty

    # Step 3 — merge and enforce strict peak/trough alternation
    extrema_idx = np.concatenate([peaks, troughs])
    extrema_typ = np.concatenate([
        np.ones(peaks.size,   dtype=int),
        -np.ones(troughs.size, dtype=int),
    ])
    order = np.argsort(extrema_idx)
    extrema_idx = extrema_idx[order]
    extrema_typ = extrema_typ[order]

    keep = [0]
    for k in range(1, extrema_idx.size):
        prev = keep[-1]
        if extrema_typ[k] != extrema_typ[prev]:
            keep.append(k)
        else:
            i_prev, i_cur = int(extrema_idx[prev]), int(extrema_idx[k])
            is_peak = extrema_typ[k] == 1
            better  = (y[i_cur] > y[i_prev]) if is_peak else (y[i_cur] < y[i_prev])
            if better:
                keep[-1] = k
    extrema_idx = extrema_idx[keep]
    extrema_typ = extrema_typ[keep]

    if extrema_idx.size < 2:
        return _empty

    # Step 4 — build phases
    starts_list: list = []
    ends_list:   list = []
    labels_list: list = []

    for i in range(extrema_idx.size - 1):
        i0, i1 = int(extrema_idx[i]), int(extrema_idx[i + 1])
        t0, t1 = float(times[i0]), float(times[i1])
        if t1 - t0 < min_phase_duration:
            continue
        if min_amplitude is not None and abs(y[i1] - y[i0]) < float(min_amplitude):
            continue
        if extrema_typ[i] == -1 and extrema_typ[i + 1] == 1:
            lab = "INH"
        elif extrema_typ[i] == 1 and extrema_typ[i + 1] == -1:
            lab = "EXH"
        else:
            continue
        starts_list.append(t0)
        ends_list.append(t1)
        labels_list.append(lab)

    if not starts_list:
        logger.warning(
            "All detected respiration phases rejected (duration/amplitude thresholds)."
        )
        return _empty

    return (
        np.asarray(starts_list, dtype=float),
        np.asarray(ends_list,   dtype=float),
        np.asarray(labels_list, dtype=object),
    )
