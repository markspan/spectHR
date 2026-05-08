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

Data classes
------------
``PSDResult``  — immutable container returned by every PSD method, holding
                 frequencies, power, optional confidence bounds, unit string,
                 and method name.

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
from typing import Dict, Optional, Tuple

import numpy as np

# PSD back-ends (located in spectHR.Tools)
from spectHR.Tools.PSD import WelchPSD
from spectHR.Tools.PSD import LombScarglePSD
from spectHR.Tools.PSD import CarspanPSD


# ---------------------------------------------------------------------------
# PSDResult data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PSDResult:
    """
    Immutable container for a PSD computation result.

    Attributes
    ----------
    freqs : np.ndarray
        Frequency axis in Hz.
    power : np.ndarray
        Power spectral density values.
    unit : str
        Physical unit of *power* (e.g. ``"mMI²/Hz"``).
    method : str
        Name of the method that produced this result.
    ci_lower : np.ndarray or None
        Lower confidence-interval bound (same unit as *power*).
    ci_upper : np.ndarray or None
        Upper confidence-interval bound.
    """

    freqs: np.ndarray
    power: np.ndarray
    unit: str = "mMI²/Hz"
    method: str = ""
    ci_lower: Optional[np.ndarray] = None
    ci_upper: Optional[np.ndarray] = None


# ---------------------------------------------------------------------------
# Module-level configuration (mirrors existing pattern in CardioMetricsMixin)
# ---------------------------------------------------------------------------

# Active PSD method: "welch", "lombscargle", "carspan", or "carspan_strict"
METHOD: str = "welch"

# Confidence-interval significance level
CI_ALPHA: float = 0.05

# Frequency bands — loaded from workspace; these are fall-back defaults
HRV_FREQUENCY_BANDS: dict[str, dict[str, float | str]] = {
    "VLF": {"low": 0.003, "high": 0.04, "color": "blue"},
    "LF": {"low": 0.04, "high": 0.15, "color": "darkgreen"},
    "HF": {"low": 0.15, "high": 0.40, "color": "red"},
}


def load_frequency_bands(bands_config: dict) -> None:
    """
    Replace the module-level HRV_FREQUENCY_BANDS from workspace config.

    Parameters
    ----------
    bands_config : dict
        Mapping of band name → {``"low"``, ``"high"``, ``"color"``}.
    """
    global HRV_FREQUENCY_BANDS
    HRV_FREQUENCY_BANDS = dict(bands_config)


def load_method(method: str) -> None:
    """Set the active PSD method (``"welch"``, ``"lombscargle"``, ``"carspan"``, ``"carspan_strict"``)."""
    global METHOD
    METHOD = method


def load_ci_alpha(alpha: float) -> None:
    """Set the confidence-interval significance level."""
    global CI_ALPHA
    CI_ALPHA = alpha


# ---------------------------------------------------------------------------
# Band-power integration (CARSPAN Eq. 3.28)
# ---------------------------------------------------------------------------


def _carspan_edge_quantum() -> Optional[float]:
    """
    Read the CARSPAN "Match Edges" toggle and return the rounding step.

    Returns the display resolution (Δf, e.g. 0.01 Hz) when the workspace
    flag ``FrequencyAnalysis.carspan.match_edges`` is True, ``None``
    otherwise. ``None`` means ``_band_power_rectangular`` uses raw band
    edges; a positive value triggers banker's rounding of the edges to
    the display grid before masking — the bin selection then matches
    CARSPAN's ``Calculate_Power`` exactly.
    """
    params = getattr(CarspanPSD, "CARSPAN_PARAMS", None)
    if not isinstance(params, dict):
        return None
    if not bool(params.get("match_edges", False)):
        return None
    quantum = params.get("freq_resolution", 0.01)
    try:
        quantum_f = float(quantum)
    except (TypeError, ValueError):
        return None
    return quantum_f if quantum_f > 0 else None


def _band_power_rectangular(
    freqs: np.ndarray,
    power: np.ndarray,
    f_low: float,
    f_high: float,
    *,
    edge_quantum: Optional[float] = None,
) -> float:
    """
    Rectangular-rule band power integration (CARSPAN Eq. 3.28):

        B = Σ S_xx(fₖ) · Δf     for f_low ≤ fₖ ≤ f_high

    Both boundaries are inclusive. Uses spacings between consecutive grid
    points, so it adapts to both uniform (Welch, L-S) and native-CARSPAN
    grids.

    Parameters
    ----------
    edge_quantum : float, optional
        When given, ``f_low`` and ``f_high`` are rounded to the nearest
        multiple of ``edge_quantum`` *before* masking. This reproduces
        CARSPAN's "Match Edges" behaviour: ``GetMinBandFreq`` /
        ``GetMaxBandFreq`` ([T_Output.pas:131,150]) round band edges to
        the display resolution (typically 0.01 Hz) via ``SimpleRoundTo``
        before ``Calculate_Power`` indexes the spectrum array. With this
        flag on and band edges initially off-grid (e.g. 0.025 Hz), the
        included bins match CARSPAN bin-for-bin. When ``None`` (default),
        the raw float edges are used — useful when the user picks band
        boundaries that intentionally fall between grid points.
    """
    if edge_quantum is not None and edge_quantum > 0:
        # Banker's rounding (Python and Pascal both use round-half-even
        # by default), so 0.025 → 0.02 and 0.026 → 0.03 — identical to
        # CARSPAN's SimpleRoundTo.
        f_low = round(f_low / edge_quantum) * edge_quantum
        f_high = round(f_high / edge_quantum) * edge_quantum

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
    """
    Mixin that adds frequency-domain HRV methods to a CardioSeries.

    Expects the host class to provide:

    - ``self.times``   : np.ndarray — R-peak timestamps (s)
    - ``self.ibi``     : np.ndarray — inter-beat intervals (s), trailing NaN
    - ``self.labels``  : np.ndarray — per-beat labels
    """

    # ---------------------------------------------------------------
    #  Private helpers — extract clean data from the host object
    # ---------------------------------------------------------------

    # ---------------------------------------------------------------
    #  Label filtering (shared by _ibi_clean_pairs and _event_times_clean)
    # ---------------------------------------------------------------

    _BAD_LABELS = ("TL", "T")
    """Beat labels treated as artefacts and excluded from all PSD computations."""

    def _valid_label_mask(self, labels: np.ndarray) -> np.ndarray:
        """
        Boolean mask that is True for every beat *not* tagged as an artefact.

        Labels ``"TL"`` (too long) and ``"T"`` (technical artefact) are
        excluded.  All other labels (``"N"``, ``"S"``, …) are kept.

        Parameters
        ----------
        labels : np.ndarray
            Per-beat label array, same length as the array being masked.

        Returns
        -------
        np.ndarray of bool
            True where the label is acceptable.
        """
        valid = np.ones(len(labels), dtype=bool)
        for bad in self._BAD_LABELS:
            valid &= labels != bad
        return valid

    def _ibi_clean_pairs(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Return aligned (times, ibi_ms) arrays with invalid intervals removed.

        An IBI is invalid if:
        - It is NaN (the trailing element, or a computational artefact).
        - The beat's label is ``"TL"`` (too long) or ``"T"`` (technical artefact).

        Returns
        -------
        ibi_times_s : np.ndarray, shape (M,)
            Timestamps (s) of the R-peak at the *start* of each valid IBI.
        ibi_values_ms : np.ndarray, shape (M,)
            Duration of each valid IBI in milliseconds.
        """
        ibi_s = self.ibi  # np.diff(times) + trailing NaN, in seconds
        labels = self.labels

        valid = ~np.isnan(ibi_s)
        if labels is not None and len(labels) == len(ibi_s):
            valid &= self._valid_label_mask(labels)

        times_s = self.times[valid]
        values_ms = ibi_s[valid] * 1000.0  # seconds → milliseconds

        return times_s, values_ms

    def _event_times_clean(self) -> np.ndarray:
        """
        Return R-peak timestamps excluding beats labelled as artefacts.

        For CARSPAN's event-series DFT we need the actual R-peak times,
        not the IBI midpoints.  We keep every beat that is *not* labelled
        as a technical artefact.

        Returns
        -------
        np.ndarray, shape (N,)
            Clean R-peak timestamps in seconds.
        """
        labels = self.labels
        times = self.times

        if labels is None or len(labels) == 0:
            return times.copy()

        return times[self._valid_label_mask(labels)]

    def _mean_ibi_ms(self) -> float:
        """
        Mean IBI in milliseconds for use in the mMI² unit conversion, computed
        as T / N × 1000 — the reciprocal of the mean heart rate x̄ = N/T.

        Here T = last_time − first_time (span between first and last R-peak)
        and N = number of clean R-peaks.

        Note: this is *not* the arithmetic mean of the N−1 intervals (T/(N−1)),
        which is the correct time-domain HRV metric.  Using T/N here keeps the
        mMI² conversion factor (mean_ibi_ms²) exactly consistent with the
        CARSPAN definition x̄ = N/T (Eq. 3.20).

        Returns
        -------
        float
            T/N × 1000 in ms — used exclusively for frequency-domain unit
            conversion, not for reporting in the HRV parameter table.
        """
        times = self._event_times_clean()
        N = times.size
        if N < 2:
            raise ValueError("Need at least 2 R-peak events to compute mean IBI.")

        T = float(times[-1] - times[0])
        # CARSPAN defines the mean rate as x̄ = N/T (events per second), so
        # the mean IBI used in the modulation-index conversion is 1/x̄ = T/N,
        # NOT the statistical average T/(N-1).  Using T/N here ensures that
        # the mMI² factor (mean_ibi_ms²) exactly matches CARSPAN Eq. 3.20.
        return (T / N) * 1000.0

    def _mmi2_factor(self) -> float:
        """
        Conversion factor from Hz (events²/Hz) to mMI²/Hz.

        CARSPAN Eq. 3.20 defines the modulation-index spectrum as:

            S'_xx(f) = S_xx(f) / x̄²    (x̄ = N/T, mean heart rate in Hz)

        Since 1/x̄ = T/N = mean_ibi_s:

            S'_xx [MI²/Hz] = S_xx × mean_ibi_s²

        Scaling to **milli**-MI² multiplies by 10⁶, but
        mean_ibi_s² × 10⁶ = (mean_ibi_ms / 1000)² × 10⁶ = mean_ibi_ms²,
        so the factor is simply ``mean_ibi_ms²``.

        Returns
        -------
        float
            mean_ibi_ms² — multiply CARSPAN Hz output by this to get mMI²/Hz.
        """
        mean_ibi = self._mean_ibi_ms()
        return mean_ibi**2

    # ---------------------------------------------------------------
    #  Public API — PSD
    # ---------------------------------------------------------------

    def psd(
        self,
        method: Optional[str] = None,
        with_ci: bool = True,
    ) -> PSDResult:
        """
        Compute the power spectral density, normalised to **mMI²/Hz**.

        Parameters
        ----------
        method : str, optional
            One of ``"welch"``, ``"lombscargle"``, ``"carspan"``,
            ``"carspan_strict"``.  Defaults to the module-level ``METHOD``.
        with_ci : bool
            If True (default), include confidence-interval bounds.

        Returns
        -------
        PSDResult
            Frequencies, power (mMI²/Hz), optional CI bounds, unit, method.

        Notes
        -----
        Welch and Lomb-Scargle analyse the **IBI series** (interval durations),
        while CARSPAN analyses the **event series** (R-peak times as unit
        impulses).  These are fundamentally different representations of the
        same cardiac process.  Both are normalised to mMI²/Hz (modulation
        index), but absolute values are **not directly comparable** across
        representation types.  Within each representation family, results
        are consistent and comparable (e.g. Welch vs. Lomb-Scargle).
        """
        method = method or METHOD

        if method == "welch":
            return self._psd_welch(with_ci=with_ci)
        elif method == "lombscargle":
            return self._psd_lombscargle(with_ci=with_ci)
        elif method == "carspan_strict":
            return self._psd_carspan_strict(with_ci=with_ci)
        elif method == "carspan":
            return self._psd_carspan(with_ci=with_ci)
        else:
            raise ValueError(
                f"Unknown PSD method '{method}'. "
                "Choose from: welch, lombscargle, carspan, carspan_strict."
            )

    def band_power(
        self,
        band_name: str,
        method: Optional[str] = None,
    ) -> float:
        """
        Integrated band power in **mMI²**.

        Uses rectangular summation (CARSPAN Eq. 3.28) on the native PSD grid.

        Parameters
        ----------
        band_name : str
            Key into ``HRV_FREQUENCY_BANDS`` (e.g. ``"VLF"``, ``"LF"``,
            ``"HF"``).
        method : str, optional
            PSD method.  Defaults to module-level ``METHOD``.

        Returns
        -------
        float
            Band power in mMI².
        """
        if band_name not in HRV_FREQUENCY_BANDS:
            raise KeyError(
                f"Unknown band '{band_name}'. "
                f"Available: {list(HRV_FREQUENCY_BANDS.keys())}"
            )

        band = HRV_FREQUENCY_BANDS[band_name]
        f_low = band["low"]
        f_high = band["high"]

        # CARSPAN's manual (§3.2) is explicit that band-power integration
        # must run on the unsmoothed native grid (Δf = 1/T) — not on the
        # bin-averaged, 3-point-MA display spectrum that gets plotted.
        # Welch / Lomb-Scargle have no separate display grid, so the
        # plot path and the integration path coincide for them.
        method_name = (method or METHOD)
        if method_name in ("carspan", "carspan_strict"):
            result = self._psd_carspan_native(method_name)
            edge_quantum = _carspan_edge_quantum()
        else:
            result = self.psd(method=method, with_ci=False)
            edge_quantum = None

        return _band_power_rectangular(
            result.freqs, result.power, f_low, f_high, edge_quantum=edge_quantum
        )

    def band_powers(
        self,
        method: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Compute all configured band powers at once.

        For ``carspan`` / ``carspan_strict`` the integration uses the
        unsmoothed native grid (Δf = 1/T), per CARSPAN manual §3.2.
        For ``welch`` / ``lombscargle`` it uses the same grid that
        ``psd()`` returns.

        Returns
        -------
        dict
            Mapping band_name → power in mMI².
        """
        method_name = (method or METHOD)
        if method_name in ("carspan", "carspan_strict"):
            result = self._psd_carspan_native(method_name)
            edge_quantum = _carspan_edge_quantum()
        else:
            result = self.psd(method=method, with_ci=False)
            edge_quantum = None

        powers = {}
        for name, band in HRV_FREQUENCY_BANDS.items():
            powers[name] = _band_power_rectangular(
                result.freqs,
                result.power,
                band["low"],
                band["high"],
                edge_quantum=edge_quantum,
            )
        return powers

    # ---------------------------------------------------------------
    #  Private dispatchers — one per back-end
    # ---------------------------------------------------------------

    def _f_max(self) -> float:
        """
        Upper frequency limit = max "high" across all configured bands,
        including FullRange.

        FullRange.high (default 0.5 Hz) is genuinely higher than HF.high
        (default 0.4 Hz), so the grid must extend to FullRange.high or the
        0.4–0.5 Hz slice would be silently excluded from FullRange band power.
        Extending the grid too far upward has no downside: extra bins only
        contribute to FullRange integration and do not affect VLF/LF/HF.
        """
        return max(b["high"] for b in HRV_FREQUENCY_BANDS.values())

    def _f_min(self) -> float:
        """
        Lower frequency limit = min "low" across all bands *except* FullRange.

        With the default configuration FullRange.low == VLF.low (both 0.02 Hz),
        so the exclusion makes no practical difference.  It is a defensive guard
        for the case where FullRange.low is configured below all other bands
        (e.g. 0.001 Hz): admitting near-DC bins into the PSD grid would inflate
        VLF power estimates and distort the Lomb-Scargle frequency axis.
        Extending the grid too far downward has an upside cost; extending it
        upward (see _f_max) does not — hence the asymmetry.
        """
        named = [b["low"] for n, b in HRV_FREQUENCY_BANDS.items() if n != "FullRange"]
        if not named:
            return min(b["low"] for b in HRV_FREQUENCY_BANDS.values())
        return min(named)

    def _as_result(
        self,
        method: str,
        freqs: np.ndarray,
        power: np.ndarray,
        ci_lo: np.ndarray,
        ci_hi: np.ndarray,
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
            method=method,
            ci_lower=ci_lo * convert if with_ci else None,
            ci_upper=ci_hi * convert if with_ci else None,
        )

    def _ibi_psd_display(self, units: str) -> Tuple[float, str]:
        """
        Return ``(convert, unit_label)`` for IBI-based PSD methods.

        Both Welch and Lomb-Scargle produce power in ms²/Hz.  This helper
        maps the ``"units"`` workspace string to the correct scale factor
        and display label so that the two display methods stay DRY.

        Parameters
        ----------
        units : str
            Value of the ``"units"`` workspace key, e.g. ``"mMI²"`` or ``"ms²"``.

        Returns
        -------
        convert : float
            Multiply the raw ms²/Hz values by this to obtain display units.
        unit_label : str
            Human-readable unit string for axis labels.
        """
        if units.lower().startswith("ms"):
            # No conversion: keep raw IBI signal PSD in ms²/Hz.
            return 1.0, "ms²/Hz"
        # Normalise by mean_ibi_ms² to obtain heart-rate-independent mMI²/Hz.
        # Derivation: mMI²/Hz = ms²/Hz × 10⁶ / mean_ibi_ms²
        return 1e6 / self._mmi2_factor(), "mMI²/Hz"

    def _welch_display(self) -> Tuple[float, str]:
        """Return ``(convert, unit)`` for Welch PSD display (delegates to _ibi_psd_display)."""
        units = str(WelchPSD.WELCH_PARAMS.get("units", "mMI²"))
        return self._ibi_psd_display(units)

    def _lombscargle_display(self) -> Tuple[float, str]:
        """Return ``(convert, unit)`` for Lomb-Scargle PSD display (delegates to _ibi_psd_display)."""
        units = str(LombScarglePSD.LOMBSCARGLE_PARAMS.get("units", "mMI²"))
        return self._ibi_psd_display(units)

    def _carspan_display(self) -> Tuple[float, str]:
        """
        Return ``(convert, unit)`` for the CARSPAN PSD display.

        CARSPAN computes power in events²/Hz.  Two display conventions:

        - ``"mMI²/Hz"``   — modulation index, factor = ``mean_ibi_ms²``.
                            Matches the CARSPAN tabular band-power output
                            (Eq. 3.20: S' = S_x / x̄²).
        - ``"ms²/Hz"``    — IBI signal PSD in ms²/Hz, derived from the rate
                            PSD via the linearisation δIBI ≈ −δrate / rate²:
                            factor = ``mean_ibi_s⁴ × 10⁶ = mean_ibi_ms⁴ × 10⁻⁶``.
                            Matches the CARSPAN figure Y-axis convention.
        """
        units = str(CarspanPSD.CARSPAN_PARAMS.get("plot_units", "mMI\u00b2/Hz"))
        # Compare on ASCII prefix only — robust against JSON encoding mishaps
        # that could mangle the "²" character on Windows (cp1252 vs UTF-8).
        if units.lower().startswith("ms"):
            mean_ibi_ms = self._mean_ibi_ms()
            return (mean_ibi_ms**4) * 1e-6, "ms\u00b2/Hz"
        return self._mmi2_factor(), "mMI\u00b2/Hz"

    def _band_mask(self, freqs: np.ndarray) -> np.ndarray:
        """Mask restricting freqs to ``[_f_min, _f_max]``."""
        return (freqs >= self._f_min()) & (freqs <= self._f_max())

    def _psd_welch(self, with_ci: bool = True) -> PSDResult:
        """
        Welch PSD, converted from ms²/Hz to the unit selected by the
        ``"units"`` workspace parameter (default: mMI²/Hz).
        """
        ibi_times_s, ibi_values_ms = self._ibi_clean_pairs()
        convert, unit = self._welch_display()

        freqs, power, ci_lo, ci_hi = WelchPSD.compute_welch_psd(
            ibi_times_s,
            ibi_values_ms,
            alpha_ci=CI_ALPHA,
        )
        return self._as_result(
            "welch",
            freqs,
            power,
            ci_lo,
            ci_hi,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(freqs),
            unit=unit,
        )

    def _psd_lombscargle(self, with_ci: bool = True) -> PSDResult:
        """
        Lomb-Scargle PSD, converted from ms²/Hz to the unit selected by the
        ``"units"`` workspace parameter (default: mMI²/Hz).
        """
        ibi_times_s, ibi_values_ms = self._ibi_clean_pairs()
        convert, unit = self._lombscargle_display()

        freqs, power, ci_lo, ci_hi = LombScarglePSD.compute_lombscargle_psd(
            ibi_times_s,
            ibi_values_ms,
            alpha_ci=CI_ALPHA,
            f_max=self._f_max(),
        )
        return self._as_result(
            "lombscargle",
            freqs,
            power,
            ci_lo,
            ci_hi,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(freqs),
            unit=unit,
        )

    def _psd_carspan_strict(self, with_ci: bool = True) -> PSDResult:
        """Strict CARSPAN PSD, converted Hz → display units (mMI²/Hz or ms²/Hz)."""
        convert, unit = self._carspan_display()
        freqs, power, ci_lo, ci_hi = CarspanPSD.compute_carspan_psd_strict(
            self._event_times_clean(),
            alpha_ci=CI_ALPHA,
            f_max=self._f_max(),
        )
        return self._as_result(
            "carspan_strict",
            freqs,
            power,
            ci_lo,
            ci_hi,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(freqs),
            unit=unit,
        )

    def _psd_carspan(self, with_ci: bool = True) -> PSDResult:
        """Configurable CARSPAN PSD, converted Hz → display units (mMI²/Hz or ms²/Hz)."""
        convert, unit = self._carspan_display()
        freqs, power, ci_lo, ci_hi = CarspanPSD.compute_carspan_psd(
            self._event_times_clean(),
            alpha_ci=CI_ALPHA,
            f_max=self._f_max(),
        )
        return self._as_result(
            "carspan",
            freqs,
            power,
            ci_lo,
            ci_hi,
            convert=convert,
            with_ci=with_ci,
            mask=self._band_mask(freqs),
            unit=unit,
        )

    def _psd_carspan_native(self, method: str) -> PSDResult:
        """
        CARSPAN PSD on the *resampled-but-un-MA-smoothed* grid.

        This mirrors CARSPAN's ``PDSin_BCK`` array — the spectrum
        immediately after ``Resample`` (display grid, Δf = 0.01 Hz by
        default) and **before** the 3-point ``MAW`` smoother runs on
        ``PDSin``.  In the reference Pascal source
        (``T_AnaFunctions.pas`` line 1264-1270, then 2389-2412) the
        order is:

            RunPDS    → PDSin on native grid (Δf = 1/T)
            RunResample → PDSin on display grid (Δf = NewRes = 0.01)
            RunMAW    → PDSin_BCK := copy(PDSin); PDSin := MAW(PDSin)
            RunModIdx → both arrays *= 1/Mean²

        and ``Calculate_Power`` (T_Output.pas line 1300) then sums
        ``PDSin_BCK[k] · FreqRes`` with ``FreqRes = 0.01``.  We
        reproduce that array by calling the back-end with
        ``smooth=False`` (skipping both bin-average and the 3-MA),
        then applying the bin-average step ourselves so the
        integration matches CARSPAN's actual numerical output rather
        than the manual's formula 3.28 (which uses Δf = 1/T).

        Parameters
        ----------
        method : {"carspan", "carspan_strict"}
            Selects the back-end (configurable vs. manual-faithful).

        Returns
        -------
        PSDResult
            Frequencies on the display grid, power in display units,
            ``ci_lower`` and ``ci_upper`` set to ``None``.
        """
        convert, unit = self._carspan_display()
        if method == "carspan_strict":
            freqs, power, _, _ = CarspanPSD.compute_carspan_psd_strict(
                self._event_times_clean(),
                alpha_ci=CI_ALPHA,
                f_max=self._f_max(),
                smooth=False,
            )
        else:
            freqs, power, _, _ = CarspanPSD.compute_carspan_psd(
                self._event_times_clean(),
                alpha_ci=CI_ALPHA,
                f_max=self._f_max(),
                smooth=False,
            )

        # Apply the resample step (CARSPAN's ``Resample``) but NOT
        # the 3-point moving average (``MAW``) -- exactly the state of
        # ``PDSin_BCK`` at the moment ``Calculate_Power`` reads it.
        display_resolution = float(CarspanPSD.CARSPAN_PARAMS["freq_resolution"])
        if freqs.size > 1:
            native_df = float(freqs[1] - freqs[0])
            if native_df < display_resolution * 0.99:
                freqs, power, _ = CarspanPSD._bin_average(
                    freqs, power, display_resolution
                )

        # CIs are not meaningful on the band-power path -- pass dummies
        # of the right shape so ``_as_result``'s mask slicing works.
        ci_dummy = np.zeros_like(power)
        return self._as_result(
            method,
            freqs,
            power,
            ci_dummy,
            ci_dummy,
            convert=convert,
            with_ci=False,
            mask=self._band_mask(freqs),
            unit=unit,
        )
