# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/frequency_metrics.py
"""
Frequency-domain HRV metrics.

These are the five band-power metrics that appear in the epoch table.
Each function receives a CardioSeriesView (or any object satisfying the
data-accessor protocol) and calls the PSD layer directly, with no
intermediate wrapper methods on the view.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.registry import hrv_metric
from spectHR.analysis.psd._engine import PSDEngine
from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.psd._config import _DEFAULT_PSD_METHOD


def _band_power(series, band_name: str) -> float:
    """Integrate one named band from the default PSD method.

    Uses ``_DEFAULT_PSD_METHOD`` because frequency-domain metrics in the
    epoch table are always computed without a caller-supplied PsdMethod.
    The UI passes psd_method explicitly when it wants a different method;
    the metric registry does not.
    """
    method = _DEFAULT_PSD_METHOD
    if band_name not in method.bands:
        raise KeyError(f"Unknown band '{band_name}'.")
    band = method.bands[band_name]
    result = PSDEngine(series).for_band_power(method)
    return band_power_rectangular(result.freqs, result.power, band.low, band.high)


@hrv_metric
def fullrange_power(series) -> float:
    """Power across the FullRange band (mMI²)."""
    try:
        return float(_band_power(series, "FullRange"))
    except (KeyError, AttributeError, ValueError):
        return np.nan


@hrv_metric
def vlf_power(series) -> float:
    """Power in the very-low-frequency band (mMI²)."""
    try:
        return float(_band_power(series, "VLF"))
    except (KeyError, AttributeError, ValueError):
        return np.nan

