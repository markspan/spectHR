"""
spectHR.Tools – Utility modules for spectHR.

Exports
-------
Logger          Logging utility.
WelchPSD        Welch PSD estimation for IBI series (ms²/Hz).
LombScarglePSD  Lomb-Scargle PSD for IBI series (ms²/Hz).
CarspanPSD      CARSPAN event-series spectral analysis (Hz).
"""

from spectHR.Tools.Logger import logger
from spectHR.Tools.PSD.LombScarglePSD import (
    compute_lombscargle_psd,
    LombscargleOptions,
)
from spectHR.Tools.PSD.WelchPSD import (
    compute_welch_psd,
    WelchOptions,
)
from spectHR.Tools.PSD.CarspanPSD import (
    compute_carspan_psd,
    compute_carspan_psd_strict,
    CarspanOptions,
    carspan_strict_options,
)

__all__ = [
    "logger",
    "compute_welch_psd",
    "WelchOptions",
    "compute_lombscargle_psd",
    "LombscargleOptions",
    "compute_carspan_psd",
    "compute_carspan_psd_strict",
    "CarspanOptions",
    "carspan_strict_options",
]
