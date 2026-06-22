# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/psd/_engine.py
"""
PSD dispatch, unit conversion, and band-mask logic.

Public surface
--------------
PSDEngine(series)
    Accepts any series-like (times, labels, ibi arrays plus view()).
    Exposes:

    compute(method, *, with_ci) -> PSDResult
        Full PSD computation with unit conversion and optional CI.
    for_band_power(method) -> PSDResult
        Same as compute(..., with_ci=False). Used for band-power
        integration where confidence intervals are not needed.

The engine calls helper functions from spectHR.analysis.ibi_helpers
directly; it does not rely on any methods on the series object beyond
the three data arrays.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, Optional, Tuple

import numpy as np

from spectHR.analysis.ibi_helpers import (
    event_times_clean,
    ibi_clean_pairs,
    mean_ibi_ms,
    mean_ibi_ms_arithmetic,
    mmi2_factor,
)
from spectHR.analysis.psd._carspan import (
    CarspanOptions,
    carspan_strict_options,
)
from spectHR.analysis.psd._carspan import (
    compute_carspan_psd as _compute_carspan_psd,
)
from spectHR.analysis.psd._config import (
    BandSpec,
    MeanConvention,
    PsdMethod,
)
from spectHR.analysis.psd._lombscargle import compute_lombscargle_psd as _compute_lombscargle_psd
from spectHR.analysis.psd._utils import PSDResult
from spectHR.analysis.psd._welch import compute_welch_psd as _compute_welch_psd

__all__ = ["PSDEngine"]


class PSDEngine:
    """Encapsulates PSD dispatch, unit conversion, and band masking.

    Construct with any object that satisfies the data-accessor protocol
    described in the module docstring, then call :meth:`compute` or
    :meth:`for_band_power`.

    Example
    -------
    >>> method = PsdMethod()
    >>> result = PSDEngine(series).compute(method)
    """

    def __init__(self, series) -> None:
        self._series = series

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def compute(
        self,
        method: PsdMethod,
        *,
        with_ci: bool = True,
    ) -> PSDResult:
        """Compute PSD using *method*, normalised to the configured unit.

        Parameters
        ----------
        method : PsdMethod
            Fully resolved method object (algorithm, band table, options).
        with_ci : bool
            Include confidence-interval arrays in the result. Set to
            ``False`` when the caller will only integrate band power.
        """
        algo = method.algorithm
        if algo == "welch":
            return self._psd_welch(method, with_ci=with_ci)
        if algo == "lombscargle":
            return self._psd_lombscargle(method, with_ci=with_ci)
        if algo == "carspan_strict":
            return self._psd_carspan_strict(method, with_ci=with_ci)
        if algo == "carspan":
            return self._psd_carspan(method, with_ci=with_ci)
        raise ValueError(
            f"Unknown PSD algorithm '{algo}'. "
            "Choose from: welch, lombscargle, carspan, carspan_strict."
        )

    def for_band_power(self, method: PsdMethod) -> PSDResult:
        """Return the spectrum grid for band-power integration.

        Equivalent to :meth:`compute` with ``with_ci=False``.  Skipping CI
        computation is a meaningful speed-up for profile runs that call
        this once per window.
        """
        return self.compute(method, with_ci=False)

    # ------------------------------------------------------------------
    # Frequency-range helpers
    # ------------------------------------------------------------------

    def _f_max(self, bands: Dict[str, BandSpec]) -> float:
        """Upper frequency limit: max ``high`` across all configured bands."""
        return max(b.high for b in bands.values())

    def _f_min(self, bands: Dict[str, BandSpec]) -> float:
        """Lower frequency limit: min ``low`` across all bands except FullRange.

        Defensive against configurations where ``FullRange.low`` is far
        below the physiological bands of interest (e.g. 0.001 Hz). Near-DC
        bins would inflate VLF power estimates and distort Lomb-Scargle
        frequency grids. The asymmetry with ``_f_max`` is intentional:
        extending the grid upward is cheap; extending it downward is not.
        """
        named = [b.low for n, b in bands.items() if n != "FullRange"]
        if not named:
            return min(b.low for b in bands.values())
        return min(named)

    def _band_mask(
        self, freqs: np.ndarray, bands: Dict[str, BandSpec]
    ) -> np.ndarray:
        """Boolean mask restricting *freqs* to the configured band range."""
        return (freqs >= self._f_min(bands)) & (freqs <= self._f_max(bands))

    # ------------------------------------------------------------------
    # Result assembly and unit conversion
    # ------------------------------------------------------------------

    def _finalise(
        self,
        raw: PSDResult,
        *,
        convert: float,
        with_ci: bool,
        mask: Optional[np.ndarray] = None,
        unit: str = "mMI²/Hz",
    ) -> PSDResult:
        """Trim, unit-convert, and stamp a raw PSDResult into display form.

        1. Optionally restrict all arrays to *mask* (band-range trimming).
        2. Multiply power (and CIs) by *convert*.
        3. Replace the ``unit`` field and honour the ``with_ci`` flag.

        The ``method`` field from *raw* is carried through unchanged.
        """
        freqs = raw.freqs
        power = raw.power
        ci_lo = raw.ci_lower
        ci_hi = raw.ci_upper

        if mask is not None:
            freqs = freqs[mask]
            power = power[mask]
            if ci_lo is not None:
                ci_lo = ci_lo[mask]
            if ci_hi is not None:
                ci_hi = ci_hi[mask]

        return PSDResult(
            freqs=freqs,
            power=power * convert,
            unit=unit,
            method=raw.method,
            ci_lower=(ci_lo * convert) if (with_ci and ci_lo is not None) else None,
            ci_upper=(ci_hi * convert) if (with_ci and ci_hi is not None) else None,
        )

    def _ibi_psd_display(self, units: str) -> Tuple[float, str]:
        """Return ``(convert, unit_label)`` for IBI-based PSD methods.

        Welch and Lomb-Scargle produce ms²/Hz natively. The ``"units"``
        setting selects the display unit: ``"ms"`` → ms²/Hz (factor 1),
        otherwise mMI²/Hz (factor ``10⁶ / mean_ibi_ms²``).
        """
        if units.lower().startswith("ms"):
            return 1.0, "ms²/Hz"
        # mMI²/Hz = ms²/Hz × 10⁶ / mean_ibi_ms². Always uses T/N here;
        # the arithmetic-mean convention is CARSPAN-strict only.
        return 1e6 / mmi2_factor(self._series, "harmonic"), "mMI²/Hz"

    def _carspan_display(
        self,
        carspan_opts: CarspanOptions,
        mean_convention: MeanConvention,
    ) -> Tuple[float, str]:
        """Return ``(convert, unit)`` for the CARSPAN display path.

        Dispatch is driven by ``carspan_opts.signal``:

        * ``"ibi_amplitude"`` (manual Eq. 3.21) - raw spectrum is in
          ms²/Hz. Multiply by ``10⁶ / mean_ms²`` to get mMI²/Hz
          (Eq. 3.20 + milli²).
        * ``"events"`` (manual Eq. 3.19) - raw spectrum is in
          events²/Hz (unit-impulse DFT). Legacy mapping uses
          ``mean_ms²`` (kept for back-compat).
        """
        units = str(carspan_opts.plot_units)
        if mean_convention == "arithmetic":
            mean_ibi_ms_val = mean_ibi_ms_arithmetic(self._series)
        else:
            mean_ibi_ms_val = mean_ibi_ms(self._series)

        if getattr(carspan_opts, "signal", "events") == "ibi_amplitude":
            # IBI-amplitude raw spectrum is already in ms²/Hz (Eq. 3.21).
            if units.lower().startswith("ms"):
                return 1.0, "ms²/Hz"
            # mMI²/Hz = ms²/Hz × 10⁶ / mean_ms² (Eq. 3.20 + milli²).
            return 1.0e6 / (mean_ibi_ms_val ** 2), "mMI²/Hz"

        # Unit-impulse SOC path - legacy conversion.
        if units.lower().startswith("ms"):
            return (mean_ibi_ms_val ** 4) * 1e-6, "ms²/Hz"
        return mean_ibi_ms_val ** 2, "mMI²/Hz"

    # ------------------------------------------------------------------
    # Back-end dispatchers (one per algorithm)
    # ------------------------------------------------------------------

    def _maybe_detrend(self, method: PsdMethod, ibi_values_ms: np.ndarray) -> np.ndarray:
        """Optionally smoothness-priors-detrend the IBI tachogram.

        Applied only to the tachogram-based PSD methods (Welch,
        Lomb-Scargle) and only when ``method.detrend_lambda > 0``. The
        zero-mean residual has the original mean added back so cubic
        interpolation in the back-ends stays numerically well-behaved; the
        DC term is removed again inside the spectral estimator. The CARSPAN
        paths never call this, they keep the faithful manual pipeline.
        """
        lam = float(getattr(method, "detrend_lambda", 0.0) or 0.0)
        if lam <= 0 or ibi_values_ms.size < 4:
            return ibi_values_ms
        from spectHR.analysis.detrend import smoothness_priors_detrend
        residual = smoothness_priors_detrend(ibi_values_ms, lam)
        return residual + float(np.mean(ibi_values_ms))

    def _psd_welch(self, method: PsdMethod, *, with_ci: bool = True) -> PSDResult:
        ibi_times_s, ibi_values_ms = ibi_clean_pairs(self._series)
        ibi_values_ms = self._maybe_detrend(method, ibi_values_ms)
        convert, unit = self._ibi_psd_display(method.welch.units)
        raw = _compute_welch_psd(
            ibi_times_s,
            ibi_values_ms,
            alpha_ci=method.alpha_ci,
            options=method.welch,
        )
        return self._finalise(
            raw,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(raw.freqs, method.bands),
            unit=unit,
        )

    def _psd_lombscargle(
        self, method: PsdMethod, *, with_ci: bool = True
    ) -> PSDResult:
        ibi_times_s, ibi_values_ms = ibi_clean_pairs(self._series)
        ibi_values_ms = self._maybe_detrend(method, ibi_values_ms)
        convert, unit = self._ibi_psd_display(method.lombscargle.units)
        raw = _compute_lombscargle_psd(
            ibi_times_s,
            ibi_values_ms,
            alpha_ci=method.alpha_ci,
            f_max=self._f_max(method.bands),
            options=method.lombscargle,
        )
        return self._finalise(
            raw,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(raw.freqs, method.bands),
            unit=unit,
        )

    def _psd_carspan(
        self, method: PsdMethod, *, with_ci: bool = True
    ) -> PSDResult:
        """Dispatch through the unified CARSPAN compute path.

        Used for both ``algorithm="carspan"`` (configurable, any
        ``CarspanOptions``) and ``algorithm="carspan_strict"`` (which first
        forces ``method.carspan`` to :func:`carspan_strict_options`).
        """
        convert, unit = self._carspan_display(method.carspan, method.mean_convention)
        raw = _compute_carspan_psd(
            event_times_clean(self._series),
            alpha_ci=method.alpha_ci,
            options=method.carspan,
        )
        return self._finalise(
            raw,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(raw.freqs, method.bands),
            unit=unit,
        )

    def _psd_carspan_strict(
        self, method: PsdMethod, *, with_ci: bool = True
    ) -> PSDResult:
        """Force the strict-preset options bundle, then dispatch to the
        unified :meth:`_psd_carspan` path.

        The strict variant is, by design, just :func:`carspan_strict_options`
        applied through the same compute pipeline as configurable CARSPAN.
        Only ``smooth_for_display``, ``f_max``, and ``plot_units`` are
        carried over from the caller's ``method.carspan``; every other field
        is overridden by the strict preset to match Pascal's
        ``IsRPDataCol=False`` branch (IBI-amplitude DFT, Eq. 3.21). The
        ``method`` field on the returned PSDResult is rebranded to
        ``"carspan_strict"`` so downstream code can tell the two apart.
        """
        strict_opts = carspan_strict_options(
            smooth_for_display=bool(method.carspan.smooth_for_display),
            f_max=float(method.carspan.f_max),
            plot_units=str(method.carspan.plot_units),
        )
        strict_method = replace(method, carspan=strict_opts)
        result = self._psd_carspan(strict_method, with_ci=with_ci)
        return replace(result, method="carspan_strict")
