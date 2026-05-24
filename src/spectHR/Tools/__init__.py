# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectHR.Tools - Signal-processing and infrastructure utilities.

PSD algorithms and profile computation have moved to spectHR.analysis.psd
and spectHR.analysis.profile. This module re-exports them for backward
compatibility (e.g. old pickle files that stored class paths under
spectHR.Tools.*).
"""

from spectHR.Tools.Logger import logger
from spectHR.analysis.psd import (  # noqa: F401
    PSDResult, ProfileResult,
    BandSpec, PsdMethod,
    WelchOptions, compute_welch_psd,
    LombscargleOptions, compute_lombscargle_psd,
    CarspanOptions, compute_carspan_psd, compute_carspan_psd_strict, carspan_strict_options,
    PSDEngine,
)
from spectHR.analysis.profile import compute_band_power_profile  # noqa: F401

__all__ = ["logger"]
