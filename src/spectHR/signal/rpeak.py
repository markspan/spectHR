# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/signal/rpeak.py
"""
Standalone R-peak detection algorithm.

The peak-detection and sub-sample-correction logic, kept as a pure function so
it is independently testable.  :meth:`spectHR.session.Events.detect` (and the
preprocessing beat-detection transform) call it with an ECG signal.

Public surface
--------------
detect_rpeaks(ts, *, min_peak_distance_ms, ...) -> np.ndarray
    Detect R-peak timestamps from an ECG TimeSeries.
"""
from __future__ import annotations

import numpy as np
import scipy.signal as signal

from spectHR.logger import logger

__all__ = ["detect_rpeaks"]


def detect_rpeaks(
    ts,
    *,
    min_peak_distance_ms: float = 300.0,
) -> np.ndarray:
    """Detect R-peak timestamps from an ECG TimeSeries.

    Parameters
    ----------
    ts : TimeSeries-like
        Object with ``.times`` and ``.values`` attributes, both 1-D
        float arrays of the same length.
    min_peak_distance_ms : float
        Minimum distance between successive R-peaks in milliseconds.
        Acts as a physiological refractory period equivalent to
        CARSPAN's ``Trefr`` (default 300 ms → max ~200 bpm).

    Returns
    -------
    peak_times : np.ndarray
        Sub-sample-corrected R-peak timestamps in the same time base as
        ``ts.times``.  Empty array when no peaks are detected or the
        input is too short.

    Algorithm
    ---------
    1. Estimate sampling rate from ``ts.times``.
    2. Detect candidate peaks with :func:`scipy.signal.find_peaks`
       using a height threshold of ``median + 1.5 × std`` and the
       converted ``min_peak_distance`` in samples.
    3. Apply a lightweight sub-sample timing correction using the
       amplitude of the two neighbours to shift each peak index by
       up to ±0.5 samples.
    """
    times  = np.asarray(ts.times,  dtype=float)
    values = np.asarray(ts.values, dtype=float)

    if times.size < 2 or values.size < 2:
        logger.warning("ECG TimeSeries too short for peak detection.")
        return np.array([], dtype=float)

    time_deltas = np.diff(times)
    time_deltas = time_deltas[time_deltas > 0]
    if time_deltas.size == 0:
        raise ValueError(
            "Cannot estimate sampling rate from ECG times (no positive deltas)."
        )

    sampling_rate_hz = 1.0 / float(np.mean(time_deltas))
    min_distance_samples = max(
        1, int((min_peak_distance_ms / 1000.0) * sampling_rate_hz)
    )
    peak_height_threshold = float(np.median(values) + 1.5 * np.std(values))

    peak_indices, _ = signal.find_peaks(
        values,
        height=peak_height_threshold,
        distance=min_distance_samples,
    )

    if peak_indices.size == 0:
        logger.warning("No R-peaks detected.")
        return np.array([], dtype=float)

    # Sub-sample timing correction.
    # For each detected peak, the amplitude asymmetry between the left and
    # right neighbours gives a fractional-sample offset estimate.
    pre_values  = values[np.clip(peak_indices - 1, 0, values.size - 1)]
    post_values = values[np.clip(peak_indices + 1, 0, values.size - 1)]
    peak_values = values[peak_indices]

    local_contrast = np.maximum(
        np.abs(peak_values - pre_values),
        np.abs(post_values - peak_values),
    )
    local_contrast[local_contrast == 0] = 1e-12

    correction_sec = (
        (post_values - pre_values) / sampling_rate_hz / (2.0 * local_contrast)
    )
    peak_times = times[peak_indices] + correction_sec

    return np.asarray(peak_times, dtype=float)
