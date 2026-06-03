# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/frequency_metrics.py
"""
Frequency-domain HRV helpers.

Band-power values (``lf_power``, ``hf_power``, etc.) are **no longer
registered as individual** ``@hrv_metric`` **functions**.  They are computed
directly inside :func:`~spectHR.DataSet.PhysioData.PhysioData.epoched_parameters_table`
from the configured :class:`~spectHR.analysis.psd._config.PsdMethod` so the
table always reflects the workspace band configuration (any name, any edges)
rather than the four CARSPAN-default hardcoded names.

This module still exports ``_band_power`` as an internal helper called by
``epoched_parameters_table``, and keeps the named functions as plain (non-registered)
callables so external scripts that imported them directly continue to work.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.psd._engine import PSDEngine
from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.psd._config import _DEFAULT_PSD_METHOD


def _band_power(series, band_name: str, psd_method=None) -> float:
    """Integrate one named band using *psd_method* (or the default if None).

    Internal helper shared by :func:`~spectHR.DataSet.PhysioData.epoched_parameters_table`
    and any external callers that want a single-band scalar.
    """
    method = psd_method if psd_method is not None else _DEFAULT_PSD_METHOD
    if band_name not in method.bands:
        raise KeyError(f"Unknown band '{band_name}'.")
    band   = method.bands[band_name]
    result = PSDEngine(series).for_band_power(method)
    return band_power_rectangular(result.freqs, result.power, band.low, band.high)


# ---------------------------------------------------------------------------
# Plain (non-registered) convenience functions kept for backward compatibility
# ---------------------------------------------------------------------------

def fullrange_power(series, psd_method=None) -> float:
    """Power across the FullRange band."""
    try:
        return float(_band_power(series, "FullRange", psd_method))
    except (KeyError, AttributeError, ValueError):
        return np.nan


def vlf_power(series, psd_method=None) -> float:
    """Power in the very-low-frequency band."""
    try:
        return float(_band_power(series, "VLF", psd_method))
    except (KeyError, AttributeError, ValueError):
        return np.nan


def lf_power(series, psd_method=None) -> float:
    """Power in the low-frequency band."""
    try:
        return float(_band_power(series, "LF", psd_method))
    except (KeyError, AttributeError, ValueError):
        return np.nan


def hf_power(series, psd_method=None) -> float:
    """Power in the high-frequency band."""
    try:
        return float(_band_power(series, "HF", psd_method))
    except (KeyError, AttributeError, ValueError):
        return np.nan


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
