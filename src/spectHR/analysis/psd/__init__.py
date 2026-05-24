# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/psd/__init__.py
"""
Public API for PSD analysis.

All algorithm implementations live in the private submodules (_welch,
_lombscargle, _carspan, _engine, _config, _utils, _band_power).
This __init__ re-exports the names that callers need.
"""

from spectHR.analysis.psd._utils import PSDResult, ProfileResult          # noqa: F401
from spectHR.analysis.psd._config import BandSpec, PsdMethod               # noqa: F401
from spectHR.analysis.psd._config import (                                  # noqa: F401
    Algorithm,
    MeanConvention,
    _DEFAULT_PSD_METHOD,
    respiration_min,
    respiration_max,
)
from spectHR.analysis.psd._band_power import band_power_rectangular        # noqa: F401
from spectHR.analysis.psd._welch import WelchOptions, compute_welch_psd   # noqa: F401
from spectHR.analysis.psd._lombscargle import (                             # noqa: F401
    LombscargleOptions,
    compute_lombscargle_psd,
)
from spectHR.analysis.psd._carspan import (                                 # noqa: F401
    CarspanOptions,
    compute_carspan_psd,
    compute_carspan_psd_strict,
    carspan_strict_options,
)
from spectHR.analysis.psd._engine import PSDEngine                         # noqa: F401

__all__ = [
    "PSDResult",
    "ProfileResult",
    "BandSpec",
    "PsdMethod",
    "Algorithm",
    "MeanConvention",
    "_DEFAULT_PSD_METHOD",
    "respiration_min",
    "respiration_max",
    "band_power_rectangular",
    "WelchOptions",
    "compute_welch_psd",
    "LombscargleOptions",
    "compute_lombscargle_psd",
    "CarspanOptions",
    "compute_carspan_psd",
    "compute_carspan_psd_strict",
    "carspan_strict_options",
    "PSDEngine",
]
