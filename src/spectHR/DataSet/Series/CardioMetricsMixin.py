# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/DataSet/Series/CardioMetricsMixin.py
"""
Thin method-dispatch layer for ``CardioSeries`` and ``CardioSeriesView``.

Design role
-----------
This mixin contains **no algorithms**.  Every method is either:

* a one-line wrapper that calls a standalone function in
  ``spectHR.analysis`` or ``spectHR.Tools``; or
* a ``__getattr__`` hook that lazily dispatches named metric calls
  (``series.rmssd()``, ``series.sdnn()``, …) to the registry in
  ``spectHR.analysis``.

Separation of concerns
-----------------------
+-----------------------------+--------------------------------------+
| This file owns              | Lives elsewhere                      |
+=============================+======================================+
| Method signatures / API     | spectHR.analysis.time_metrics        |
| psd_method config attribute | spectHR.analysis.frequency_metrics   |
| METRIC_ORDER / _BAD_LABELS  | spectHR.analysis.ibi_helpers         |
| metric_table / epoch_table  | spectHR.Tools.PSD.*                  |
| __getattr__ lazy dispatch   | spectHR.Tools.Profile                |
+-----------------------------+--------------------------------------+

Re-exports
----------
``BandSpec``, ``PsdMethod``, ``PSDResult``, ``ProfileResult`` are
re-exported here so that UI code (workSpace.py, PSDPlotWidget.py,
ProfilePlotWidget.py) can import them from a single location without
reaching into the PSD sub-package directly.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

# Re-exported so UI code can do ``from CardioMetricsMixin import BandSpec``.
# Only names actually imported via this path are kept here.
from spectHR.Tools.PSD._psd_utils import PSDResult, ProfileResult  # noqa: F401
from spectHR.Tools.PSD._psd_config import (
    MeanConvention,   # needed by _mmi2_factor signature below
    BandSpec,         # noqa: F401
    PsdMethod,        # noqa: F401
    _DEFAULT_PSD_METHOD,
)
from spectHR.Tools.PSD._band_power import band_power_rectangular


__all__ = [
    "BandSpec",
    "PsdMethod",
    "PSDResult",
    "ProfileResult",
    "CardioMetricsMixin",
]


class CardioMetricsMixin:
    """Thin method-dispatch mixin for ``CardioSeries`` / ``CardioSeriesView``.

    Expects the host class to provide:

    - ``self.times``   : np.ndarray - R-peak timestamps (s)
    - ``self.ibi``     : np.ndarray - IBI series (s), trailing NaN
    - ``self.labels``  : np.ndarray - per-beat labels (``"N"``, ``"TL"``, …)
    - ``self.view(starttime, endtime)`` → CardioSeriesLike

    The UI assigns the active PSD configuration via ``series.psd_method``;
    an unset attribute falls back to the module default.
    """

    # ------------------------------------------------------------------
    # Class-level constants and fall-backs
    # ------------------------------------------------------------------

    psd_method: Optional[PsdMethod] = None

    METRIC_ORDER = [
        "count",
        "mean",
        "stationarity",
        "median",
        "min",
        "max",
        "rmssd",
        "sdnn",
        "sdsd",
        "sd1",
        "sd2",
        "sd_ratio",
        "ellipse_area",
        "fullrange_power",
        "vlf_power",
        "lf_power",
        "hf_power",
        "lf_hf_ratio",
    ]

    _BAD_LABELS: Tuple[str, ...] = ("TL", "T")

    # ------------------------------------------------------------------
    # Private data-accessor wrappers
    # (keep these explicit so PSDEngine's duck-typed protocol keeps working)
    # ------------------------------------------------------------------

    def _valid_label_mask(self, labels: np.ndarray) -> np.ndarray:
        from spectHR.analysis.ibi_helpers import valid_label_mask
        return valid_label_mask(labels, self._BAD_LABELS)

    def _ibi_clean_ms(self) -> np.ndarray:
        from spectHR.analysis.ibi_helpers import ibi_clean_ms
        return ibi_clean_ms(self)

    def _ibi_ms_full_with_mask(self) -> Tuple[np.ndarray, np.ndarray]:
        from spectHR.analysis.ibi_helpers import ibi_ms_full_with_mask
        return ibi_ms_full_with_mask(self)

    def _successive_diffs_ms(self) -> np.ndarray:
        from spectHR.analysis.ibi_helpers import successive_diffs_ms
        return successive_diffs_ms(self)

    def _ibi_clean_pairs(self) -> Tuple[np.ndarray, np.ndarray]:
        from spectHR.analysis.ibi_helpers import ibi_clean_pairs
        return ibi_clean_pairs(self)

    def _event_times_clean(self) -> np.ndarray:
        from spectHR.analysis.ibi_helpers import event_times_clean
        return event_times_clean(self)

    def _mean_ibi_ms(self) -> float:
        from spectHR.analysis.ibi_helpers import mean_ibi_ms
        return mean_ibi_ms(self)

    def _mean_ibi_ms_arithmetic(self) -> float:
        from spectHR.analysis.ibi_helpers import mean_ibi_ms_arithmetic
        return mean_ibi_ms_arithmetic(self)

    def _mmi2_factor(self, mean_convention: MeanConvention) -> float:
        from spectHR.analysis.ibi_helpers import mmi2_factor
        return mmi2_factor(self, mean_convention)

    # ------------------------------------------------------------------
    # Metric table - uses the registry, not class introspection
    # ------------------------------------------------------------------

    @classmethod
    def get_metric_functions(cls) -> Dict[str, object]:
        """Return all registered HRV metrics (``name → function``).

        """
        from spectHR.analysis import get_metrics
        return get_metrics()

    def metric_table(self) -> Dict[str, float]:
        """Compute all registered metrics on the full series."""
        from spectHR.analysis import get_metrics
        return {name: float(fn(self)) for name, fn in get_metrics().items()}

    def metric_table_epoch(self, starttime: float, endtime: float) -> Dict[str, float]:
        """Compute all registered metrics on the slice ``[starttime, endtime]``."""
        from spectHR.analysis import get_metrics
        view = self.view(starttime, endtime)
        return {name: float(fn(view)) for name, fn in get_metrics().items()}

    # ------------------------------------------------------------------
    # Lazy metric dispatch
    # ------------------------------------------------------------------

    def __getattr__(self, name: str):
        """Dispatch named metric calls to the analysis registry.

        Called only when normal attribute lookup fails (i.e. *name* is not
        defined on the class or instance).  If *name* is a registered metric,
        return a zero-argument lambda that applies the metric to ``self``.

        This is what makes ``series.rmssd()`` work without a method body on
        the class, while keeping the import of ``spectHR.analysis`` lazy -
        analysis code is loaded only on first metric access.
        """
        # Guard against infinite recursion during pickling / copying.
        if name.startswith("__"):
            raise AttributeError(name)
        from spectHR.analysis import get_metrics
        fn = get_metrics().get(name)
        if fn is not None:
            return lambda: fn(self)
        raise AttributeError(
            f"{type(self).__name__!r} has no attribute {name!r}"
        )

    # ------------------------------------------------------------------
    # Public PSD API - thin wrappers to PSDEngine / Profile
    # ------------------------------------------------------------------

    def psd(
        self,
        *,
        psd_method: Optional[PsdMethod] = None,
        with_ci: bool = True,
    ) -> PSDResult:
        """Compute the power spectral density, normalised to mMI²/Hz."""
        from spectHR.Tools.PSD.PSDEngine import PSDEngine
        method = self._resolve_method(psd_method)
        return PSDEngine(self).compute(method, with_ci=with_ci)

    def band_power(
        self,
        band_name: str,
        *,
        psd_method: Optional[PsdMethod] = None,
    ) -> float:
        """Integrated band power for one named band, in mMI²."""
        method = self._resolve_method(psd_method)
        if band_name not in method.bands:
            raise KeyError(
                f"Unknown band '{band_name}'. "
                f"Available: {list(method.bands.keys())}"
            )
        band = method.bands[band_name]
        result = self._psd_for_band_power(method)
        return band_power_rectangular(
            result.freqs, result.power, band.low, band.high
        )

    def band_powers(
        self,
        *,
        psd_method: Optional[PsdMethod] = None,
    ) -> Dict[str, float]:
        """Compute all configured band powers at once."""
        method = self._resolve_method(psd_method)
        result = self._psd_for_band_power(method)
        return {
            name: band_power_rectangular(
                result.freqs, result.power, band.low, band.high
            )
            for name, band in method.bands.items()
        }

    def band_power_profile(
        self,
        *,
        window_s: float,
        step_s: float,
        psd_method: Optional[PsdMethod] = None,
        adaptive_source: str = "respiration_channel",
        smooth_breath_freq: bool = False,
    ) -> ProfileResult:
        """Sliding-window band-power profile (CARSPAN ``RunProfileSommation``)."""
        from spectHR.Tools.Profile import compute_band_power_profile
        return compute_band_power_profile(
            self,
            window_s=window_s,
            step_s=step_s,
            psd_method=psd_method,
            adaptive_source=adaptive_source,
            smooth_breath_freq=smooth_breath_freq,
        )

    # ------------------------------------------------------------------
    # PSD configuration helpers
    # ------------------------------------------------------------------

    def _resolve_method(self, override: Optional[PsdMethod]) -> PsdMethod:
        """Pick the PsdMethod: override → instance attribute → default."""
        if override is not None:
            return override
        instance_attr = getattr(self, "psd_method", None)
        if instance_attr is not None:
            return instance_attr
        return _DEFAULT_PSD_METHOD

    def _psd_for_band_power(self, method: PsdMethod) -> PSDResult:
        """Return the spectrum grid for band-power integration (no CI, no MA)."""
        from spectHR.Tools.PSD.PSDEngine import PSDEngine
        return PSDEngine(self).for_band_power(method)
