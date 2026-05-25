# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/time_metrics.py
"""
Time-domain HRV metrics.

Every function here is a standalone callable decorated with ``@hrv_metric``,
which registers it in ``spectHR.analysis.registry._REGISTRY``.

Each function accepts a single ``CardioSeriesLike`` argument (anything that
exposes ``.times``, ``.ibi``, and ``.labels`` arrays) and returns a ``float``
(or ``np.nan`` when the metric cannot be computed).

Usage:
    import spectHR.analysis as hrv
    hrv.rmssd(series)       # call a metric directly
    hrv.get_metrics()       # {name: fn} dict for automatic table building
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.registry import hrv_metric
from spectHR.analysis.ibi_helpers import (
    ibi_clean_ms,
    successive_diffs_ms,
)


# ---------------------------------------------------------------------------
# Magnitude-based statistics
# ---------------------------------------------------------------------------

@hrv_metric
def count(series) -> float:
    """Total number of valid inter-beat intervals."""
    return float(ibi_clean_ms(series).size)


@hrv_metric
def mean(series) -> float:
    """Mean IBI (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.mean(ibi_ms)) if ibi_ms.size else np.nan


@hrv_metric
def median(series) -> float:
    """Median IBI (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.median(ibi_ms)) if ibi_ms.size else np.nan


@hrv_metric
def min(series) -> float:
    """Minimum IBI (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.min(ibi_ms)) if ibi_ms.size else np.nan


@hrv_metric
def max(series) -> float:
    """Maximum IBI (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.max(ibi_ms)) if ibi_ms.size else np.nan


@hrv_metric
def stationarity(series) -> float:
    """Correlation of IBI vs. time - drift indicator."""
    ibi_ms = ibi_clean_ms(series)
    if ibi_ms.size <= 2:
        return np.nan
    # Use the same length prefix of times as the cleaned IBI vector.
    t = series.times[:ibi_ms.size]
    return float(np.corrcoef(ibi_ms, t)[0, 1])


# ---------------------------------------------------------------------------
# Variability
# ---------------------------------------------------------------------------

@hrv_metric
def rmssd(series) -> float:
    """Root mean square of successive differences (ms). Gap-safe."""
    d = successive_diffs_ms(series)
    return float(np.sqrt(np.mean(d * d))) if d.size else np.nan


@hrv_metric
def sdnn(series) -> float:
    """Standard deviation of all valid IBIs (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.std(ibi_ms)) if ibi_ms.size else np.nan


@hrv_metric
def sdsd(series) -> float:
    """Standard deviation of successive differences (ms). Gap-safe."""
    d = successive_diffs_ms(series)
    return float(np.std(d)) if d.size else np.nan


# ---------------------------------------------------------------------------
# Poincaré
# ---------------------------------------------------------------------------

@hrv_metric
def sd1(series) -> float:
    """Poincaré SD1 (minor axis, ms) = std(dIBI) / sqrt(2). Gap-safe."""
    d = successive_diffs_ms(series)
    return float(np.std(d) / np.sqrt(2.0)) if d.size else np.nan


@hrv_metric
def sd2(series) -> float:
    """Poincaré SD2 (major axis, ms) via Brennan's identity:
    ``SD2² = 2·Var(IBI) − 0.5·Var(dIBI)``."""
    ibi_ms = ibi_clean_ms(series)
    d = successive_diffs_ms(series)
    if ibi_ms.size < 2 or not d.size:
        return np.nan
    val = 2.0 * float(np.var(ibi_ms)) - 0.5 * float(np.var(d))
    return float(np.sqrt(val)) if val > 0.0 else np.nan


@hrv_metric
def sd_ratio(series) -> float:
    """SD1 / SD2 - short-term vs long-term variability balance.

    Guards against degenerate uniform-IBI series whose Brennan residual is
    float-precision noise rather than a meaningful SD2.
    """
    s1 = sd1(series)
    s2 = sd2(series)
    if np.isnan(s1) or np.isnan(s2) or s2 == 0:
        return np.nan
    sdnn_val = sdnn(series)
    if np.isnan(sdnn_val) or sdnn_val < 1e-9:
        return np.nan
    return float(s1 / s2)


@hrv_metric
def ellipse_area(series) -> float:
    """Area of the Poincaré ellipse, ``π · SD1 · SD2`` (ms²)."""
    s1 = sd1(series)
    s2 = sd2(series)
    if np.isnan(s1) or np.isnan(s2):
        return np.nan
    return float(np.pi * s1 * s2)
