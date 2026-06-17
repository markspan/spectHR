# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/_beat_sampling.py
"""
Shared low-level helpers for sampling a waveform at R-peak boundaries.

These are used by every "beat-by-beat" parameter pass that gates a waveform
(blood pressure, respiration, …) on the cardiac R-peaks, so they live in one
place rather than being duplicated per series module:

* :func:`median_dt`, the waveform's uniform sample interval.
* :func:`rpeak_sample_indices`, map R-peak times onto sample indices.
* :func:`nanmean`, NaN-safe mean (no warning for all-NaN).

This module is series-agnostic on purpose, it knows nothing about pressure,
respiration or RSA, only about turning ``(times, values, rpeak_times)`` into
indexable beat windows.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def median_dt(times: np.ndarray) -> Optional[float]:
    """Median positive sample interval of *times* (seconds), or None."""
    if times.size < 2:
        return None
    dt = np.diff(times)
    dt = dt[(dt > 0) & np.isfinite(dt)]
    if dt.size == 0:
        return None
    return float(np.median(dt))


def rpeak_sample_indices(sig_times: np.ndarray, rpeak_times: np.ndarray) -> np.ndarray:
    """Map R-peak times onto the nearest sample index of *sig_times*.

    ``np.searchsorted`` gives the insertion point; we clamp it to the valid
    index range so callers can slice ``values`` safely.
    """
    idx = np.searchsorted(sig_times, rpeak_times)
    return np.clip(idx, 0, sig_times.size - 1)


def nanmean(arr: np.ndarray) -> float:
    """``np.nanmean`` that returns NaN (not a warning) for an all-NaN array."""
    a = np.asarray(arr, dtype=float)
    if a.size == 0 or not np.any(np.isfinite(a)):
        return float("nan")
    return float(np.nanmean(a))
