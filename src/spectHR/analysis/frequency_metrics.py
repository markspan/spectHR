# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/frequency_metrics.py
"""
Frequency-domain HRV metrics.

These are the band-power metrics that appear in the epoch table.
Each function receives a CardioSeriesLike object and calls the PSD
layer directly, with no intermediate wrapper methods on the series.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.registry import hrv_metric
from spectHR.analysis.psd._engine import PSDEngine
from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.psd._config import _DEFAULT_PSD_METHOD


def _band_power(series, band_name: str, psd_method=None) -> float:
    """Integrate one named band using *psd_method* (or the default if None).

    The *psd_method* argument lets callers supply the workspace-configured
    method so the values here match what the PSD plot displays.  When
    ``None`` the module-level ``_DEFAULT_PSD_METHOD`` is used as a
    safe fallback (e.g. when called without a workspace, from tests).
    """
    method = psd_method if psd_method is not None else _DEFAULT_PSD_METHOD
    if band_name not in method.bands:
        raise KeyError(f"Unknown band '{band_name}'.")
    band = method.bands[band_name]
    result = PSDEngine(series).for_band_power(method)
    return band_power_rectangular(result.freqs, result.power, band.low, band.high)


@hrv_metric
def fullrange_power(series, psd_method=None) -> float:
    """Power across the FullRange band."""
    try:
        return float(_band_power(series, "FullRange", psd_method))
    except (KeyError, AttributeError, ValueError):
        return np.nan


@hrv_metric
def vlf_power(series, psd_method=None) -> float:
    """Power in the very-low-frequency band."""
    try:
        return float(_band_power(series, "VLF", psd_method))
    except (KeyError, AttributeError, ValueError):
        return np.nan


@hrv_metric
def lf_power(series, psd_method=None) -> float:
    """Power in the low-frequency band."""
    try:
        return float(_band_power(series, "LF", psd_method))
    except (KeyError, AttributeError, ValueError):
        return np.nan


@hrv_metric
def hf_power(series, psd_method=None) -> float:
    """Power in the high-frequency band."""
    try:
        return float(_band_power(series, "HF", psd_method))
    except (KeyError, AttributeError, ValueError):
        return np.nan


@hrv_metric
def lf_hf_ratio(series, psd_method=None) -> float:
    """LF/HF ratio."""
    try:
        lf = _band_power(series, "LF", psd_method)
        hf = _band_power(series, "HF", psd_method)
        if hf == 0.0:
            return np.nan
        return float(lf / hf)
    except (KeyError, AttributeError, ValueError):
        return np.nan
