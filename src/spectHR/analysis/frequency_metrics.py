# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/frequency_metrics.py
"""
Frequency-domain HRV metrics.

These are the five band-power metrics that appear in the epoch table.
They delegate to the explicit ``band_power(name)`` method that
``CardioMetricsMixin`` keeps as a thin wrapper to ``PSDEngine``.

Like the time-domain metrics, each function is a standalone callable
registered via ``@hrv_metric`` and accessed either directly
(``hrv.lf_power(series)``) or through ``CardioMetricsMixin.__getattr__``
(``series.lf_power()``).
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.registry import hrv_metric


@hrv_metric
def fullrange_power(series) -> float:
    """Power across the FullRange band (mMI²)."""
    try:
        return float(series.band_power("FullRange"))
    except (KeyError, AttributeError, ValueError):
        return np.nan


@hrv_metric
def vlf_power(series) -> float:
    """Power in the very-low-frequency band (mMI²)."""
    try:
        return float(series.band_power("VLF"))
    except (KeyError, AttributeError, ValueError):
        return np.nan


@hrv_metric
def lf_power(series) -> float:
    """Power in the low-frequency band (mMI²)."""
    try:
        return float(series.band_power("LF"))
    except (KeyError, AttributeError, ValueError):
        return np.nan


@hrv_metric
def hf_power(series) -> float:
    """Power in the high-frequency band (mMI²)."""
    try:
        return float(series.band_power("HF"))
    except (KeyError, AttributeError, ValueError):
        return np.nan


@hrv_metric
def lf_hf_ratio(series) -> float:
    """LF/HF ratio (dimensionless)."""
    lf = lf_power(series)
    hf = hf_power(series)
    if np.isnan(lf) or np.isnan(hf) or hf == 0:
        return np.nan
    return float(lf / hf)
