"""
CardioFrequencyMetricsMixin.py – Unified frequency-domain HRV interface.

This mixin provides a single entry point (``psd()``) that dispatches to
one of three PSD back-ends — Welch, Lomb-Scargle, or CARSPAN — and
normalises every result to a common unit: **mMI²/Hz** (milli-modulation-
index squared per Hz).

It is designed to be mixed into a ``CardioSeries`` class that provides:

    self.times      np.ndarray of R-peak timestamps (seconds)
    self.ibi        np.ndarray property (np.diff(times) with trailing NaN)
    self.labels     np.ndarray of per-beat labels ("N", "TL", "T", …)

Configuration is **not** loaded from any global state in this module.
The UI (spectUI) builds a :class:`PsdMethod` dataclass from the
workspace JSON and assigns it to each series instance::

    series.psd_method = PsdMethod(algorithm="welch", bands={...}, ...)

Subsequent calls to ``series.psd()`` / ``series.band_power()`` /
``series.band_powers()`` read from that instance attribute. An
explicit ``psd_method=`` keyword on the call overrides the instance
attribute for a single computation.

Data classes
------------
``PSDResult``  — immutable container returned by every PSD method, holding
                 frequencies, power, optional confidence bounds, unit string,
                 and algorithm name.
``BandSpec``   — one row of the band table (low, high, color, alpha).
``PsdMethod``  — full PSD configuration: algorithm name, band table,
                 alpha_ci, mean-rate convention, and the three back-end
                 option bundles (WelchOptions, LombscargleOptions,
                 CarspanOptions).

Unit conversion
---------------
CARSPAN outputs Hz (events²/Hz).  Welch and Lomb-Scargle output ms²/Hz.
To convert both to mMI²/Hz (Modulation Index, CARSPAN Eq. 3.20):

    CARSPAN (Hz)  → mMI²/Hz:  multiply by mean_ibi_ms²
                               (because MI = S_xx / x̄² and x̄ = N/T in Hz,
                                so S'_xx [mMI²] = S_xx × (T/N)² × 10⁶
                                                = S_xx × mean_ibi_s² × 10⁶
                                                = S_xx × mean_ibi_ms²)

    Welch / L-S (ms²/Hz) → mMI²/Hz:  divide by mean_ibi_ms² then × 10⁶
                               (MI² = Var / mean² → ms²/Hz / ms² → 1/Hz,
                                then × 10⁶ for mMI² display)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional, Tuple

import numpy as np

# PSD back-ends (located in spectHR.Tools)
from spectHR.Tools.PSD import WelchPSD
from spectHR.Tools.PSD import LombScarglePSD
from spectHR.Tools.PSD import CarspanPSD
from spectHR.Tools.PSD.WelchPSD import WelchOptions
from spectHR.Tools.PSD.LombScarglePSD import LombscargleOptions
from spectHR.Tools.PSD.CarspanPSD import CarspanOptions


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Algorithm = Literal["welch", "lombscargle", "carspan", "carspan_strict"]
MeanConvention = Literal["harmonic", "arithmetic"]


# ---------------------------------------------------------------------------
# PSDResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PSDResult:
    """Immutable container for a PSD computation result."""

    freqs: np.ndarray
    power: np.ndarray
    unit: str = "mMI²/Hz"
    method: str = ""
    ci_lower: Optional[np.ndarray] = None
    ci_upper: Optional[np.ndarray] = None


# ---------------------------------------------------------------------------
# BandSpec + PsdMethod
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BandSpec:
    """One HRV band: edges (Hz) plus display attributes."""

    low: float
    high: float
    color: str = "gray"
    alpha: Optional[float] = None
    """Optional display alpha for the band fill (None → widget default)."""


def _default_bands() -> Dict[str, BandSpec]:
    """Fallback band table used when no PsdMethod is supplied.

    Matches the spectUI workspace defaults.
    """
    return {
        "FullRange": BandSpec(low=0.02, high=0.5, color="gray", alpha=0.05),
        "VLF": BandSpec(low=0.02, high=0.06, color="blue"),
        "LF": BandSpec(low=0.07, high=0.14, color="darkgreen"),
        "HF": BandSpec(low=0.15, high=0.40, color="red"),
    }


@dataclass(frozen=True)
class PsdMethod:
    """Full PSD configuration: which algorithm, with which options.

    Built by the spectUI layer from a workspace dict and assigned to
    each series instance via ``series.psd_method = …``.
    """

    algorithm: Algorithm = "carspan"
    bands: Dict[str, BandSpec] = field(default_factory=_default_bands)
    alpha_ci: float = 0.05
    mean_convention: MeanConvention = "harmonic"
    """Mean rate convention used to convert events²/Hz → mMI²/Hz. ``"harmonic"``
    (= ``T/N``) is the manual definition; ``"arithmetic"`` (= ``Σ 1/IBI / N``)
    is what the reference CARSPAN Pascal SOC uses and is picked automatically
    by the UI for ``algorithm == "carspan_strict"``."""

    welch: WelchOptions = field(default_factory=WelchOptions)
    lombscargle: LombscargleOptions = field(default_factory=LombscargleOptions)
    carspan: CarspanOptions = field(default_factory=CarspanOptions)


_DEFAULT_PSD_METHOD = PsdMethod()


# ---------------------------------------------------------------------------
# Band-power integration (CARSPAN Eq. 3.28)
# ---------------------------------------------------------------------------


def _band_power_rectangular(
    freqs: np.ndarray,
    power: np.ndarray,
    f_low: float,
    f_high: float,
) -> float:
    """Rectangular-rule band power integration (CARSPAN Eq. 3.28).

    ``B = Σ S_xx(fₖ) · Δf`` for ``f_low ≤ fₖ ≤ f_high``, both endpoints
    inclusive. Per-bin Δf is the centred neighbour spacing, so the
    integration adapts to both uniform (Welch, L-S) and native-CARSPAN
    grids.
    """
    mask = (freqs >= f_low) & (freqs <= f_high)
    band_freqs = freqs[mask]
    band_power = power[mask]

    if band_freqs.size == 0:
        return 0.0

    if band_freqs.size == 1:
        if freqs.size > 1:
            delta_f = float(freqs[1] - freqs[0])
        else:
            delta_f = float(band_freqs[0])
        return float(band_power[0] * delta_f)

    spacings = np.diff(band_freqs)
    delta_f_per_bin = np.empty_like(band_freqs)
    delta_f_per_bin[0] = spacings[0]
    delta_f_per_bin[-1] = spacings[-1]
    delta_f_per_bin[1:-1] = (spacings[:-1] + spacings[1:]) / 2.0

    return float(np.sum(band_power * delta_f_per_bin))


# ---------------------------------------------------------------------------
# Mixin class
# ---------------------------------------------------------------------------


class CardioFrequencyMetricsMixin:
    """Mixin that adds frequency-domain HRV methods to a CardioSeries.

    Expects the host class to provide:

    - ``self.times``   : np.ndarray — R-peak timestamps (s)
    - ``self.ibi``     : np.ndarray — inter-beat intervals (s), trailing NaN
    - ``self.labels``  : np.ndarray — per-beat labels

    The UI assigns the active configuration via
    ``series.psd_method = PsdMethod(...)``; an unset attribute is
    treated as the default ``PsdMethod()``.
    """

    # Per-instance configuration. The class-level default acts as a
    # safety net; the UI overrides it for every loaded series. Frozen
    # dataclass means it is safe to share a single PsdMethod across
    # many series.
    psd_method: Optional[PsdMethod] = None

    # ---------------------------------------------------------------
    #  Label filtering
    # ---------------------------------------------------------------

    _BAD_LABELS = ("TL", "T")
    """Beat labels treated as artefacts and excluded from all PSD computations."""

    def _valid_label_mask(self, labels: np.ndarray) -> np.ndarray:
        """Boolean mask that is True for every beat *not* tagged as an artefact.

        Labels ``"TL"`` (too long) and ``"T"`` (technical artefact) are
        excluded.  All other labels (``"N"``, ``"S"``, …) are kept.
        """
        valid = np.ones(len(labels), dtype=bool)
        for bad in self._BAD_LABELS:
            valid &= labels != bad
        return valid

    def _ibi_clean_pairs(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return aligned (times, ibi_ms) arrays with invalid intervals removed."""
        ibi_s = self.ibi  # np.diff(times) + trailing NaN, in seconds
        labels = self.labels

        valid = ~np.isnan(ibi_s)
        if labels is not None and len(labels) == len(ibi_s):
            valid &= self._valid_label_mask(labels)

        times_s = self.times[valid]
        values_ms = ibi_s[valid] * 1000.0  # seconds → milliseconds

        return times_s, values_ms

    def _event_times_clean(self) -> np.ndarray:
        """Return R-peak timestamps excluding beats labelled as artefacts."""
        labels = self.labels
        times = self.times

        if labels is None or len(labels) == 0:
            return times.copy()

        return times[self._valid_label_mask(labels)]

    # ---------------------------------------------------------------
    #  Mean-IBI helpers (used by the mMI² conversion factor)
    # ---------------------------------------------------------------

    def _mean_ibi_ms(self) -> float:
        """Mean IBI in milliseconds under the manual's ``x̄ = N/T`` convention.

        Used by every method except ``carspan_strict``. ``T/N × 1000``.
        """
        times = self._event_times_clean()
        N = times.size
        if N < 2:
            raise ValueError("Need at least 2 R-peak events to compute mean IBI.")
        T = float(times[-1] - times[0])
        return (T / N) * 1000.0

    def _mean_ibi_ms_arithmetic(self) -> float:
        """Mean IBI in ms under CARSPAN's strict arithmetic-mean-of-rate convention.

        ``1000 / mean(1/IBI_i)`` over the cleaned IBI series. Matches the
        reference Pascal ``SOC`` exactly. Used by ``carspan_strict``.
        """
        _, ibi_values_ms = self._ibi_clean_pairs()
        if ibi_values_ms.size == 0:
            raise ValueError(
                "Need at least one IBI to compute the arithmetic-mean rate."
            )
        ibi_values_s = ibi_values_ms.astype(np.float64) * 1e-3
        valid = np.isfinite(ibi_values_s) & (ibi_values_s > 0)
        if not np.any(valid):
            raise ValueError("All cleaned IBI values are non-positive or NaN.")
        am_rate_hz = float(np.mean(1.0 / ibi_values_s[valid]))
        return 1000.0 / am_rate_hz

    def _mmi2_factor(self, mean_convention: MeanConvention) -> float:
        """Conversion factor from Hz (events²/Hz) to mMI²/Hz.

        With ``x̄`` = mean rate in Hz::

            S'_xx [mMI²/Hz] = S_xx × mean_ibi_ms²

        Returns the ``mean_ibi_ms²`` factor using the chosen mean
        convention. See :func:`_mean_ibi_ms` and
        :func:`_mean_ibi_ms_arithmetic` for the two conventions.
        """
        if mean_convention == "arithmetic":
            mean_ibi = self._mean_ibi_ms_arithmetic()
        else:
            mean_ibi = self._mean_ibi_ms()
        return mean_ibi ** 2

    # ---------------------------------------------------------------
    #  Public API — PSD
    # ---------------------------------------------------------------

    def psd(
        self,
        *,
        psd_method: Optional[PsdMethod] = None,
        with_ci: bool = True,
    ) -> PSDResult:
        """Compute the power spectral density, normalised to **mMI²/Hz**.

        Parameters
        ----------
        psd_method : PsdMethod, optional
            Explicit configuration override. Falls back to
            ``self.psd_method`` and then to ``PsdMethod()``.
        with_ci : bool
            If True (default), include confidence-interval bounds.
        """
        method = self._resolve_method(psd_method)

        if method.algorithm == "welch":
            return self._psd_welch(method, with_ci=with_ci)
        if method.algorithm == "lombscargle":
            return self._psd_lombscargle(method, with_ci=with_ci)
        if method.algorithm == "carspan_strict":
            return self._psd_carspan_strict(method, with_ci=with_ci)
        if method.algorithm == "carspan":
            return self._psd_carspan(method, with_ci=with_ci)
        raise ValueError(
            f"Unknown PSD algorithm '{method.algorithm}'. "
            "Choose from: welch, lombscargle, carspan, carspan_strict."
        )

    def band_power(
        self,
        band_name: str,
        *,
        psd_method: Optional[PsdMethod] = None,
    ) -> float:
        """Integrated band power for one named band, in **mMI²**."""
        method = self._resolve_method(psd_method)
        if band_name not in method.bands:
            raise KeyError(
                f"Unknown band '{band_name}'. "
                f"Available: {list(method.bands.keys())}"
            )
        band = method.bands[band_name]

        # CARSPAN integrates on the unsmoothed native grid (manual §3.2).
        # Welch / Lomb-Scargle have no separate display grid.
        if method.algorithm in ("carspan", "carspan_strict"):
            result = self._psd_carspan_native(method)
        else:
            result = self.psd(psd_method=method, with_ci=False)

        return _band_power_rectangular(result.freqs, result.power, band.low, band.high)

    def band_powers(
        self,
        *,
        psd_method: Optional[PsdMethod] = None,
    ) -> Dict[str, float]:
        """Compute all configured band powers at once."""
        method = self._resolve_method(psd_method)

        if method.algorithm in ("carspan", "carspan_strict"):
            result = self._psd_carspan_native(method)
        else:
            result = self.psd(psd_method=method, with_ci=False)

        return {
            name: _band_power_rectangular(
                result.freqs, result.power, band.low, band.high
            )
            for name, band in method.bands.items()
        }

    # ---------------------------------------------------------------
    #  Resolve psd_method with sensible fall-backs
    # ---------------------------------------------------------------

    def _resolve_method(self, override: Optional[PsdMethod]) -> PsdMethod:
        """Pick which :class:`PsdMethod` to use for this call.

        Order of preference: explicit override → ``self.psd_method``
        → module-level default.
        """
        if override is not None:
            return override
        instance_attr = getattr(self, "psd_method", None)
        if instance_attr is not None:
            return instance_attr
        return _DEFAULT_PSD_METHOD

    # ---------------------------------------------------------------
    #  Frequency bounds (used to mask the PSD output)
    # ---------------------------------------------------------------

    def _f_max(self, bands: Dict[str, BandSpec]) -> float:
        """Upper frequency limit = max ``high`` across all configured bands."""
        return max(b.high for b in bands.values())

    def _f_min(self, bands: Dict[str, BandSpec]) -> float:
        """Lower frequency limit = min ``low`` across all bands except FullRange.

        With the default configuration FullRange.low == VLF.low (both 0.02 Hz),
        so the exclusion makes no practical difference.  It is a defensive
        guard for the case where FullRange.low is configured below all other
        bands (e.g. 0.001 Hz): admitting near-DC bins into the PSD grid
        would inflate VLF power estimates and distort the Lomb-Scargle
        frequency axis. Extending the grid too far upward has no downside
        (see _f_max), but extending it too far downward does — hence the
        asymmetry.
        """
        named = [b.low for n, b in bands.items() if n != "FullRange"]
        if not named:
            return min(b.low for b in bands.values())
        return min(named)

    def _band_mask(
        self, freqs: np.ndarray, bands: Dict[str, BandSpec]
    ) -> np.ndarray:
        """Mask restricting *freqs* to the configured band range."""
        return (freqs >= self._f_min(bands)) & (freqs <= self._f_max(bands))

    # ---------------------------------------------------------------
    #  Result assembly + unit conversion
    # ---------------------------------------------------------------

    def _as_result(
        self,
        algorithm: str,
        freqs: np.ndarray,
        power: np.ndarray,
        ci_lo: np.ndarray,
        ci_hi: np.ndarray,
        *,
        convert: float,
        with_ci: bool,
        mask: Optional[np.ndarray] = None,
        unit: str = "mMI²/Hz",
    ) -> PSDResult:
        """Trim, unit-convert, and package a PSD computation into a PSDResult."""
        if mask is not None:
            freqs = freqs[mask]
            power = power[mask]
            ci_lo = ci_lo[mask]
            ci_hi = ci_hi[mask]
        return PSDResult(
            freqs=freqs,
            power=power * convert,
            unit=unit,
            method=algorithm,
            ci_lower=ci_lo * convert if with_ci else None,
            ci_upper=ci_hi * convert if with_ci else None,
        )

    def _ibi_psd_display(self, units: str) -> Tuple[float, str]:
        """Return ``(convert, unit_label)`` for IBI-based PSD methods.

        Both Welch and Lomb-Scargle produce power in ms²/Hz. Maps the
        ``"units"`` workspace string to the correct scale factor and
        display label.
        """
        if units.lower().startswith("ms"):
            return 1.0, "ms²/Hz"
        # Note: this path uses the harmonic mean (T/N). IBI methods do
        # not use the arithmetic-mean convention — that's CARSPAN strict
        # only.
        return 1e6 / self._mmi2_factor("harmonic"), "mMI²/Hz"

    def _welch_display(self, opts: WelchOptions) -> Tuple[float, str]:
        return self._ibi_psd_display(opts.units)

    def _lombscargle_display(self, opts: LombscargleOptions) -> Tuple[float, str]:
        return self._ibi_psd_display(opts.units)

    def _carspan_display(
        self,
        carspan_opts: CarspanOptions,
        mean_convention: MeanConvention,
    ) -> Tuple[float, str]:
        """Return ``(convert, unit)`` for the CARSPAN PSD display."""
        units = str(carspan_opts.plot_units)
        if mean_convention == "arithmetic":
            mean_ibi_ms = self._mean_ibi_ms_arithmetic()
        else:
            mean_ibi_ms = self._mean_ibi_ms()
        # Compare on ASCII prefix only — robust against JSON encoding
        # mishaps that could mangle the "²" character (cp1252 vs UTF-8).
        if units.lower().startswith("ms"):
            return (mean_ibi_ms ** 4) * 1e-6, "ms²/Hz"
        return mean_ibi_ms ** 2, "mMI²/Hz"

    # ---------------------------------------------------------------
    #  Back-end dispatchers (one per algorithm)
    # ---------------------------------------------------------------

    def _psd_welch(self, method: PsdMethod, *, with_ci: bool = True) -> PSDResult:
        """Welch PSD, converted from ms²/Hz to the unit chosen by the options."""
        ibi_times_s, ibi_values_ms = self._ibi_clean_pairs()
        convert, unit = self._welch_display(method.welch)

        freqs, power, ci_lo, ci_hi = WelchPSD.compute_welch_psd(
            ibi_times_s,
            ibi_values_ms,
            alpha_ci=method.alpha_ci,
            options=method.welch,
        )
        return self._as_result(
            "welch",
            freqs,
            power,
            ci_lo,
            ci_hi,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(freqs, method.bands),
            unit=unit,
        )

    def _psd_lombscargle(
        self, method: PsdMethod, *, with_ci: bool = True
    ) -> PSDResult:
        """Lomb-Scargle PSD, converted from ms²/Hz."""
        ibi_times_s, ibi_values_ms = self._ibi_clean_pairs()
        convert, unit = self._lombscargle_display(method.lombscargle)

        freqs, power, ci_lo, ci_hi = LombScarglePSD.compute_lombscargle_psd(
            ibi_times_s,
            ibi_values_ms,
            alpha_ci=method.alpha_ci,
            f_max=self._f_max(method.bands),
            options=method.lombscargle,
        )
        return self._as_result(
            "lombscargle",
            freqs,
            power,
            ci_lo,
            ci_hi,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(freqs, method.bands),
            unit=unit,
        )

    def _psd_carspan(self, method: PsdMethod, *, with_ci: bool = True) -> PSDResult:
        """Configurable CARSPAN PSD."""
        convert, unit = self._carspan_display(method.carspan, method.mean_convention)
        freqs, power, ci_lo, ci_hi = CarspanPSD.compute_carspan_psd(
            self._event_times_clean(),
            alpha_ci=method.alpha_ci,
            options=method.carspan,
        )
        return self._as_result(
            "carspan",
            freqs,
            power,
            ci_lo,
            ci_hi,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(freqs, method.bands),
            unit=unit,
        )

    def _psd_carspan_strict(
        self, method: PsdMethod, *, with_ci: bool = True
    ) -> PSDResult:
        """Strict (manual-faithful) CARSPAN PSD."""
        convert, unit = self._carspan_display(method.carspan, method.mean_convention)
        freqs, power, ci_lo, ci_hi = CarspanPSD.compute_carspan_psd_strict(
            self._event_times_clean(),
            alpha_ci=method.alpha_ci,
            smooth=bool(method.carspan.smooth_for_display),
            f_max=float(method.carspan.f_max),
        )
        return self._as_result(
            "carspan_strict",
            freqs,
            power,
            ci_lo,
            ci_hi,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(freqs, method.bands),
            unit=unit,
        )

    def _psd_carspan_native(self, method: PsdMethod) -> PSDResult:
        """CARSPAN PSD on the resampled-but-un-MA-smoothed grid.

        This mirrors CARSPAN's ``PDSin_BCK`` array — the spectrum
        immediately after resample and **before** the 3-point MA
        smoother runs. The integration path (``band_power`` /
        ``band_powers``) uses this rather than the smoothed display
        grid: the smoothing changes peak heights but not band power, so
        omitting it keeps the reported values clean.
        """
        convert, unit = self._carspan_display(method.carspan, method.mean_convention)

        if method.algorithm == "carspan_strict":
            freqs, power, _, _ = CarspanPSD.compute_carspan_psd_strict(
                self._event_times_clean(),
                alpha_ci=method.alpha_ci,
                smooth=False,
                f_max=float(method.carspan.f_max),
            )
        else:
            # Configurable: clone the options with smooth turned off
            # so the bin-average step still runs but the 3-point MA
            # does not.
            unsmoothed = CarspanOptions(
                freq_resolution=method.carspan.freq_resolution,
                smooth_for_display=False,
                f_max=method.carspan.f_max,
                window=method.carspan.window,
                taper=method.carspan.taper,
                alpha_taper=method.carspan.alpha_taper,
                amplitude_correction=method.carspan.amplitude_correction,
                skip_first_event=method.carspan.skip_first_event,
                dc_removal=method.carspan.dc_removal,
                dc_grid=method.carspan.dc_grid,
                plot_units=method.carspan.plot_units,
            )
            freqs, power, _, _ = CarspanPSD.compute_carspan_psd(
                self._event_times_clean(),
                alpha_ci=method.alpha_ci,
                options=unsmoothed,
            )

        # Apply the resample step (CARSPAN's ``Resample``) but NOT the
        # 3-point MA — exactly the state of ``PDSin_BCK`` at the moment
        # ``Calculate_Power`` reads it.
        display_resolution = float(method.carspan.freq_resolution)
        if freqs.size > 1:
            native_df = float(freqs[1] - freqs[0])
            if native_df < display_resolution * 0.99:
                freqs, power, _ = CarspanPSD._bin_average(
                    freqs, power, display_resolution
                )

        ci_dummy = np.zeros_like(power)
        return self._as_result(
            method.algorithm,
            freqs,
            power,
            ci_dummy,
            ci_dummy,
            convert=convert,
            with_ci=False,
            mask=self._band_mask(freqs, method.bands),
            unit=unit,
        )
