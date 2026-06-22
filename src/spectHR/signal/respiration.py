# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/signal/respiration.py
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
from numpy.linalg import eigh
from scipy.signal import butter, sosfiltfilt, savgol_filter, find_peaks, buttord

from spectHR.logger import logger


__all__ = [
    "segment_respiration",
    "mean_breath_frequency_hz",
    "accel_to_respiration",
]


def accel_to_respiration(acc: np.ndarray, fs: float) -> np.ndarray:
    """Return a 1-D z-scored respiration surrogate from ``Nx3`` accelerometer data.

    Gravity is removed with a 0.04 Hz low-pass, the linear acceleration is
    band-passed to the respiration band (0.10–0.70 Hz), and the first principal
    component of the band-passed 3-axis signal is the respiration surrogate.

    Because the principal axis that captures chest expansion depends on
    posture, running this **per epoch** (rather than once over the whole
    recording) gives a cleaner surrogate when posture changes between epochs,
    see ``apply_breath_phases(..., per_epoch=True)``.
    """
    acc = np.asarray(acc, dtype=float)
    if acc.ndim != 2 or acc.shape[1] != 3 or acc.shape[0] < 8:
        return np.zeros(acc.shape[0] if acc.ndim else 0, dtype=float)
    nyq = 0.5 * fs

    # Gravity removal (very low-pass), leaving linear acceleration.
    wn_g = min(0.04 / nyq, 0.999)
    sos_g = butter(2, wn_g, btype="low", output="sos")
    gravity = np.column_stack([sosfiltfilt(sos_g, acc[:, k]) for k in range(3)])
    lin = acc - gravity

    # Respiration bandpass.
    lo = max(0.10 / nyq, 0.001)
    hi = min(0.70 / nyq, 0.999)
    if lo < hi:
        sos_b = butter(4, [lo, hi], btype="band", output="sos")
        band = np.column_stack([sosfiltfilt(sos_b, lin[:, k]) for k in range(3)])
    else:
        band = lin

    # PCA: project onto the largest-variance eigenvector.
    X = band - band.mean(0)
    C = (X.T @ X) / max(X.shape[0] - 1, 1)
    _, evecs = eigh(C)            # ascending eigenvalues
    rsp = X @ evecs[:, -1]
    s = rsp.std()
    return (rsp - rsp.mean()) / (s if s > 0 else 1.0)


def segment_respiration(
    rsp,
    *,
    prefilter_cutoff_hz: float = 2.0,
    prefilter_order: Optional[int] = None,
    min_phase_duration: float = 0.5,
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
        Minimum duration of an accepted INH or EXH phase in seconds (default 0.5 s,
        which accepts breathing up to ~60 bpm while still blocking cardiac-period
        artifacts at ~1 s).  The old default of 2.0 s rejected normal breathing
        above ~12 bpm.
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

    # Step 0 - low-pass prefilter
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

    # Step 1 - Savitzky-Golay smoothing
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

    # Step 2 - peak / trough detection
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

    # Step 3 - merge and enforce strict peak/trough alternation
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

    # Step 4 - build phases
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


def mean_breath_frequency_hz(view) -> "Optional[float]":
    """Mean breathing frequency for the phases in *view*, in Hz.

    Pairs each phase with its successor (INH -> EXH or EXH -> INH) into a
    full breath cycle and averages ``1 / cycle_period``.  With ``N`` phases
    in the view this produces ``N-1`` cycle estimates, which is the most
    data-efficient unbiased estimator on the alternating phase sequence built
    by :func:`segment_respiration`.

    Equivalent to CARSPAN's ``1 / LProfile.MeanIn`` used in
    ``RunProfileSommation`` (``T_AnaFunctions.pas`` 2944-2952) when the
    input signal is ``RespPeriod``.  spectHR does not carry a ``RespPeriod``
    series, so we derive the same number directly from the phase-segmented
    respiration signal.

    Parameters
    ----------
    view : RespirationSeriesView
        An epoch or time-range slice of a RespirationSeries.  Must expose
        ``.starts`` and ``.ends`` as 1-D float arrays of equal length.

    Returns
    -------
    float or None
        Mean breath frequency in Hz, or ``None`` when fewer than two phases
        fall inside the view (no full cycle could be reconstructed) or when
        every paired cycle duration is non-positive (degenerate data).
    """
    starts = np.asarray(view.starts, dtype=float)
    ends   = np.asarray(view.ends,   dtype=float)
    if starts.size < 2:
        return None
    # One cycle per adjacent (INH+EXH) or (EXH+INH) pair.
    # Cycle duration = end of the second phase - start of the first.
    cycle_periods = ends[1:] - starts[:-1]
    cycle_periods = cycle_periods[cycle_periods > 0]
    if cycle_periods.size == 0:
        return None
    return float(1.0 / np.mean(cycle_periods))
