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
    load_lombscargle_params,
)
from spectHR.Tools.PSD.WelchPSD import (
    compute_welch_psd,
    load_welch_params,
)
from spectHR.Tools.PSD.CarspanPSD import (
    compute_carspan_psd,
    compute_carspan_psd_strict,
    load_carspan_params,
)

__all__ = [
    "logger",
    "compute_welch_psd",
    "load_welch_params",
    "compute_lombscargle_psd",
    "load_lombscargle_params",
    "compute_carspan_psd",
    "compute_carspan_psd_strict",
    "load_carspan_params",
]
