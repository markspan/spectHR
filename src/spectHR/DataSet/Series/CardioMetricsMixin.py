# spectHR/DataSet/Series/CardioMetricsMixin.py
"""
Heart-rate-variability (HRV) metrics on a CardioSeries.

This single mixin provides both time-domain (RMSSD, SDNN, SD1, SD2 …)
and frequency-domain (PSD, band power, LF/HF ratio) HRV measures. The
two used to live in separate mixins (``CardioMetricsMixin`` and
``CardioFrequencyMetricsMixin``); the split duplicated label-filtering
and IBI-cleaning logic and is now merged.

Public surface
--------------
- :class:`PsdMethod`  — frozen dataclass bundling the active algorithm,
  band table, alpha_ci, mean convention, and the three back-end option
  dataclasses (``WelchOptions``, ``LombscargleOptions``,
  ``CarspanOptions``).
- :class:`BandSpec`   — one row of the band table.
- :class:`PSDResult`  — re-exported from ``spectHR.Tools.PSD``.
- :class:`CardioMetricsMixin` — the mixin proper.

Configuration model
-------------------
A series gets its configuration through the instance attribute
``series.psd_method``. ``PhysioData.set_psd_method(method)`` assigns
the same :class:`PsdMethod` to every master ``CardioSeries`` in the
dataset; ``CardioSeriesView`` delegates the attribute to its parent,
so per-epoch views pick it up automatically.

Unit conversion
---------------
The mixin layer is the single place where the various PSD back-ends'
native units are translated into the display unit (mMI²/Hz or ms²/Hz).
There are **three** native units in play:

* ``compute_carspan_psd`` (configurable, unit-impulse SOC of Eq. 3.19)
  → returns ``events²/Hz``.  Convert to mMI²/Hz by ``× mean_ms²``
  (legacy mapping kept for back-compat; see ``_carspan_display``).
* ``compute_carspan_psd_strict`` (IBI-amplitude DFT of Eq. 3.21)
  → returns ``ms²/Hz`` (variance per Hz, as the manual writes it).
  Convert to mMI²/Hz by ``× 10⁶ / mean_ms²`` (Eq. 3.20 + milli²).
  This is the path that reproduces the CARSPAN manual's reference
  numbers — verified against epoch #2 of ``example1.EVT`` to within
  ~2 % on every band.
* ``compute_welch_psd`` / ``compute_lombscargle_psd`` (regular Welch /
  Lomb-Scargle of the IBI series) → ``ms²/Hz`` natively.  Convert to
  mMI²/Hz by ``× 10⁶ / mean_ms²``.

The strict CARSPAN path also uses the **arithmetic mean of the
per-beat instantaneous rate** (= harmonic mean of IBI) for the mMI²
conversion — Pascal's ``SOC`` computes the same. The configurable
CARSPAN and the two IBI methods use the simpler harmonic mean ``T/N``
from the manual. The split is controlled by ``PsdMethod.mean_convention``
(``"arithmetic"`` for strict, ``"harmonic"`` everywhere else).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Literal, Optional, Tuple

import numpy as np

from spectHR.DataSet.HRVMetrics import HRVMetric, hrv_metric

# PSD back-ends
from spectHR.Tools.PSD import WelchPSD
from spectHR.Tools.PSD import LombScarglePSD
from spectHR.Tools.PSD import CarspanPSD
from spectHR.Tools.PSD.WelchPSD import WelchOptions
from spectHR.Tools.PSD.LombScarglePSD import LombscargleOptions
from spectHR.Tools.PSD.CarspanPSD import CarspanOptions
from spectHR.Tools.PSD._psd_utils import PSDResult


__all__ = [
    "BandSpec",
    "PsdMethod",
    "PSDResult",
    "CardioMetricsMixin",
]


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Algorithm = Literal["welch", "lombscargle", "carspan", "carspan_strict"]
MeanConvention = Literal["harmonic", "arithmetic"]


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
    each series via ``series.psd_method = …``.
    """

    algorithm: Algorithm = "carspan"
    bands: Dict[str, BandSpec] = field(default_factory=_default_bands)
    alpha_ci: float = 0.05
    mean_convention: MeanConvention = "harmonic"
    """Mean rate convention for the events²/Hz → mMI²/Hz conversion.
    ``"harmonic"`` (= ``T/N``) is the manual definition; ``"arithmetic"``
    (= ``Σ 1/IBI / N``) matches the reference CARSPAN Pascal SOC and is
    picked automatically by the UI for ``algorithm == "carspan_strict"``."""

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


class CardioMetricsMixin(HRVMetric):
    """HRV metrics mixed into ``CardioSeries`` / ``CardioSeriesView``.

    Expects the host class to provide:

    - ``self.times``   : np.ndarray — R-peak timestamps (s)
    - ``self.ibi``     : np.ndarray — IBI series (s), trailing NaN
    - ``self.labels``  : np.ndarray — per-beat labels (``"N"``, ``"TL"``, …)

    The UI assigns the active configuration via ``series.psd_method``;
    an unset attribute falls back to ``PsdMethod()``.
    """

    # ------------------------------------------------------------------
    # Class-level fall-backs and constants
    # ------------------------------------------------------------------

    # Per-instance configuration. The class-level default acts as a
    # safety net; ``PhysioData.set_psd_method`` overrides it for every
    # loaded series.
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
    """Canonical order for displaying metrics in the UI table."""

    _BAD_LABELS = ("TL", "T")
    """Beat labels treated as artefacts — excluded from every metric."""

    # ------------------------------------------------------------------
    # Label / IBI filtering — shared by time- and frequency-domain
    # ------------------------------------------------------------------

    def _valid_label_mask(self, labels: np.ndarray) -> np.ndarray:
        """True for every beat *not* tagged as an artefact (``TL`` or ``T``)."""
        valid = np.ones(len(labels), dtype=bool)
        for bad in self._BAD_LABELS:
            valid &= labels != bad
        return valid

    def _ibi_clean_ms(self) -> np.ndarray:
        """Packed valid IBI values in ms, excluding NaN / TL / T.

        Use for magnitude-only metrics (mean, std, min, max, count,
        sdnn). Do NOT use for successive-difference metrics; use
        :func:`_successive_diffs_ms` instead to avoid bridging excluded
        gaps.
        """
        ibi_sec = self.ibi
        if ibi_sec.size == 0:
            return np.array([], dtype=float)
        valid = ~np.isnan(ibi_sec) & self._valid_label_mask(self.labels)
        return 1000.0 * ibi_sec[valid]

    def _ibi_ms_full_with_mask(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return ``(ibi_ms, valid)`` both of length ``len(self.ibi)``.

        ``ibi_ms``: IBIs in ms, NaN for invalid intervals.
        ``valid`` : boolean mask, True where IBI is usable.

        Positional adjacency equals temporal adjacency in the recording.
        Used internally by successive-difference metrics.
        """
        ibi_sec = self.ibi
        if ibi_sec.size == 0:
            return np.array([], dtype=float), np.array([], dtype=bool)
        valid = ~np.isnan(ibi_sec) & self._valid_label_mask(self.labels)
        ibi_ms = np.where(valid, 1000.0 * ibi_sec, np.nan)
        return ibi_ms, valid

    def _successive_diffs_ms(self) -> np.ndarray:
        """Differences between consecutive *valid* IBIs that are also
        temporally adjacent in the original series.

        Pairs where either interval is invalid are dropped, preventing
        differences from bridging an excluded beat and inflating
        RMSSD / SDSD / SD1 / SD2.

        Used by: rmssd, sdsd, sd1, sd2.
        """
        ibi_ms, valid = self._ibi_ms_full_with_mask()
        if ibi_ms.size < 2:
            return np.array([], dtype=float)
        pair_ok = valid[:-1] & valid[1:]
        if not np.any(pair_ok):
            return np.array([], dtype=float)
        return ibi_ms[1:][pair_ok] - ibi_ms[:-1][pair_ok]

    def _ibi_clean_pairs(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return aligned ``(times_s, ibi_ms)`` with invalid intervals removed.

        Used by the IBI-based PSD back-ends (Welch, Lomb-Scargle).
        """
        ibi_s = self.ibi  # np.diff(times) + trailing NaN, in seconds
        labels = self.labels

        valid = ~np.isnan(ibi_s)
        if labels is not None and len(labels) == len(ibi_s):
            valid &= self._valid_label_mask(labels)

        times_s = self.times[valid]
        values_ms = ibi_s[valid] * 1000.0

        return times_s, values_ms

    def _event_times_clean(self) -> np.ndarray:
        """R-peak timestamps with artefact-labelled beats removed.

        Used by the CARSPAN event-series PSD path.
        """
        labels = self.labels
        times = self.times
        if labels is None or len(labels) == 0:
            return times.copy()
        return times[self._valid_label_mask(labels)]

    # ------------------------------------------------------------------
    # Mean-IBI helpers (used by the mMI² conversion factor)
    # ------------------------------------------------------------------

    def _mean_ibi_ms(self) -> float:
        """Mean IBI in ms under the manual's ``x̄ = N/T`` convention (``T/N × 1000``)."""
        times = self._event_times_clean()
        N = times.size
        if N < 2:
            raise ValueError("Need at least 2 R-peak events to compute mean IBI.")
        T = float(times[-1] - times[0])
        return (T / N) * 1000.0

    def _mean_ibi_ms_arithmetic(self) -> float:
        """Mean IBI in ms under CARSPAN's strict arithmetic-mean-of-rate convention.

        ``1000 / mean(1/IBI_i)`` over the cleaned IBI series. Matches
        the reference Pascal ``SOC`` exactly. Used by ``carspan_strict``.
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
        """``mean_ibi_ms²`` — the multiplier that turns Hz (events²/Hz) into mMI²/Hz."""
        if mean_convention == "arithmetic":
            mean_ibi = self._mean_ibi_ms_arithmetic()
        else:
            mean_ibi = self._mean_ibi_ms()
        return mean_ibi ** 2

    # ========================================================================
    # Time-Domain Metrics: Magnitude-Based Statistics
    # ========================================================================

    @hrv_metric
    def count(self):
        """Total number of valid inter-beat intervals."""
        return int(self._ibi_clean_ms().size)

    @hrv_metric
    def stationarity(self):
        """Correlation of IBI vs. time — drift indicator."""
        return (
            np.corrcoef(self._ibi_clean_ms(), self.times[:-1])[0, 1]
            if self.count() > 2
            else np.nan
        )

    @hrv_metric
    def mean(self):
        """Mean IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.mean(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def min(self):
        """Minimum IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.min(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def max(self):
        """Maximum IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.max(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def median(self):
        """Median IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.median(ibi_ms)) if ibi_ms.size else np.nan

    # ========================================================================
    # Time-Domain Metrics: Variability
    # ========================================================================

    @hrv_metric
    def rmssd(self):
        """Root mean square of successive differences (ms). Gap-safe."""
        d = self._successive_diffs_ms()
        if d.size == 0:
            return np.nan
        return float(np.sqrt(np.mean(d * d)))

    @hrv_metric
    def sdnn(self):
        """Standard deviation of all IBIs (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def sdsd(self):
        """Standard deviation of successive differences (ms). Gap-safe."""
        d = self._successive_diffs_ms()
        if d.size == 0:
            return np.nan
        return float(np.std(d))

    # ========================================================================
    # Time-Domain Metrics: Poincaré
    # ========================================================================

    @hrv_metric
    def sd1(self):
        """Poincaré SD1 (minor axis, ms) = std(dIBI) / sqrt(2). Gap-safe."""
        d = self._successive_diffs_ms()
        if d.size == 0:
            return np.nan
        return float(np.std(d) / np.sqrt(2.0))

    @hrv_metric
    def sd2(self):
        """Poincaré SD2 (major axis, ms) via Brennan's identity:
        ``SD2² = 2·Var(IBI) − 0.5·Var(dIBI)``.
        """
        ibi_ms = self._ibi_clean_ms()
        d = self._successive_diffs_ms()
        if ibi_ms.size < 2 or d.size == 0:
            return np.nan
        val = 2.0 * float(np.var(ibi_ms)) - 0.5 * float(np.var(d))
        if val <= 0.0:
            return np.nan
        return float(np.sqrt(val))

    @hrv_metric
    def sd_ratio(self):
        """SD1 / SD2 — short-term vs long-term variability balance.

        Guards against degenerate uniform-IBI series whose Brennan
        residual is float-precision noise rather than a meaningful SD2.
        """
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2) or s2 == 0:
            return np.nan
        sdnn = self.sdnn()
        if np.isnan(sdnn) or sdnn < 1e-9:
            return np.nan
        return float(s1 / s2)

    @hrv_metric
    def ellipse_area(self):
        """Area of the Poincaré ellipse, ``π · SD1 · SD2`` (ms²)."""
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2):
            return np.nan
        return float(np.pi * s1 * s2)

    # ========================================================================
    # Frequency-Domain Metrics: Band Powers (call self.band_power)
    # ========================================================================

    @hrv_metric
    def fullrange_power(self):
        """Power across the FullRange band (mMI² by default)."""
        try:
            return self.band_power("FullRange")
        except (KeyError, AttributeError, ValueError):
            return np.nan

    @hrv_metric
    def vlf_power(self):
        """Power in the very-low-frequency band."""
        try:
            return self.band_power("VLF")
        except (KeyError, AttributeError, ValueError):
            return np.nan

    @hrv_metric
    def lf_power(self):
        """Power in the low-frequency band."""
        try:
            return self.band_power("LF")
        except (KeyError, AttributeError, ValueError):
            return np.nan

    @hrv_metric
    def hf_power(self):
        """Power in the high-frequency band."""
        try:
            return self.band_power("HF")
        except (KeyError, AttributeError, ValueError):
            return np.nan

    @hrv_metric
    def lf_hf_ratio(self):
        """LF/HF ratio (dimensionless)."""
        lf, hf = self.lf_power(), self.hf_power()
        if np.isnan(lf) or np.isnan(hf) or hf == 0:
            return np.nan
        return float(lf / hf)

    # ========================================================================
    # Public PSD API
    # ========================================================================

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
            Explicit override. Falls back to ``self.psd_method`` and
            then to the module default.
        with_ci : bool
            If True (default), include confidence-interval bounds.
        """
        method = self._resolve_method(psd_method)
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
        result = self._psd_for_band_power(method)
        return _band_power_rectangular(
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
            name: _band_power_rectangular(
                result.freqs, result.power, band.low, band.high
            )
            for name, band in method.bands.items()
        }

    # ------------------------------------------------------------------
    # Resolve psd_method with sensible fall-backs
    # ------------------------------------------------------------------

    def _resolve_method(self, override: Optional[PsdMethod]) -> PsdMethod:
        """Pick the :class:`PsdMethod`: override → instance attribute → default."""
        if override is not None:
            return override
        instance_attr = getattr(self, "psd_method", None)
        if instance_attr is not None:
            return instance_attr
        return _DEFAULT_PSD_METHOD

    def _psd_for_band_power(self, method: PsdMethod) -> PSDResult:
        """Return the grid that band-power integration should run on.

        CARSPAN integrates on the **unsmoothed** native grid (manual
        §3.2). Welch / Lomb-Scargle have no separate display grid, so
        the plot path and the integration path coincide for them.
        """
        if method.algorithm in ("carspan", "carspan_strict"):
            return self._psd_carspan_native(method)
        return self.psd(psd_method=method, with_ci=False)

    # ------------------------------------------------------------------
    # Frequency bounds (used to clip / mask compute output)
    # ------------------------------------------------------------------

    def _f_max(self, bands: Dict[str, BandSpec]) -> float:
        """Upper frequency limit = max ``high`` across all configured bands."""
        return max(b.high for b in bands.values())

    def _f_min(self, bands: Dict[str, BandSpec]) -> float:
        """Lower frequency limit = min ``low`` across all bands except FullRange.

        Defensive against pathological configurations where FullRange.low
        is set far below all other bands (e.g. 0.001 Hz): the near-DC
        bins would inflate VLF power estimates and distort the
        Lomb-Scargle frequency axis. Extending the grid upward (see
        ``_f_max``) is cheap; extending it downward is not — hence the
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

    # ------------------------------------------------------------------
    # Result assembly + unit conversion
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
        """Mask, unit-convert, and stamp a raw PSDResult into the display form.

        Takes the result that the compute layer returned and:

        * trims arrays to ``mask`` when given,
        * multiplies power (and CIs) by the unit-conversion ``convert``
          factor,
        * replaces the ``unit`` and (optionally) drops CIs to match the
          ``with_ci`` flag.

        The ``method`` field is carried through from *raw* unchanged.
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

        Welch and Lomb-Scargle produce ms²/Hz. The ``"units"`` setting
        chooses whether the displayed unit is mMI²/Hz (normalised) or
        ms²/Hz (raw).
        """
        if units.lower().startswith("ms"):
            return 1.0, "ms²/Hz"
        # mMI²/Hz = ms²/Hz × 10⁶ / mean_ibi_ms².  Always uses T/N here;
        # the arithmetic-mean convention is CARSPAN-strict only.
        return 1e6 / self._mmi2_factor("harmonic"), "mMI²/Hz"

    def _carspan_display(
        self,
        carspan_opts: CarspanOptions,
        mean_convention: MeanConvention,
    ) -> Tuple[float, str]:
        """Return ``(convert, unit)`` for the CARSPAN display path.

        Dispatch is driven by ``carspan_opts.signal``: the two CARSPAN
        variants produce different raw spectra and therefore need
        different unit conversions to reach mMI²/Hz:

        * ``signal="ibi_amplitude"`` (manual Eq. 3.21) — raw spectrum
          is already in **ms²/Hz**. To express in mMI²/Hz, multiply by
          ``10⁶ / mean_ms²`` (manual Eq. 3.20 + milli²).
        * ``signal="events"`` (manual Eq. 3.19) — raw spectrum is in
          events²/Hz (unit-impulse DFT). Legacy mapping uses ``mean_ms²``
          (kept for back-compat).
        """
        units = str(carspan_opts.plot_units)
        if mean_convention == "arithmetic":
            mean_ibi_ms = self._mean_ibi_ms_arithmetic()
        else:
            mean_ibi_ms = self._mean_ibi_ms()

        if getattr(carspan_opts, "signal", "events") == "ibi_amplitude":
            # IBI-amplitude raw spectrum is already in ms²/Hz (Eq. 3.21).
            if units.lower().startswith("ms"):
                return 1.0, "ms²/Hz"
            # mMI²/Hz = ms²/Hz × 10⁶ / mean_ms² (Eq. 3.20 + milli²).
            return 1.0e6 / (mean_ibi_ms ** 2), "mMI²/Hz"

        # Unit-impulse SOC path — legacy conversion.
        if units.lower().startswith("ms"):
            # ms²/Hz: mean_ibi_s⁴ × 10⁶ = mean_ibi_ms⁴ × 10⁻⁶
            return (mean_ibi_ms ** 4) * 1e-6, "ms²/Hz"
        return mean_ibi_ms ** 2, "mMI²/Hz"

    # ------------------------------------------------------------------
    # Back-end dispatchers (one per algorithm)
    # ------------------------------------------------------------------

    def _psd_welch(self, method: PsdMethod, *, with_ci: bool = True) -> PSDResult:
        ibi_times_s, ibi_values_ms = self._ibi_clean_pairs()
        convert, unit = self._ibi_psd_display(method.welch.units)
        raw = WelchPSD.compute_welch_psd(
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
        ibi_times_s, ibi_values_ms = self._ibi_clean_pairs()
        convert, unit = self._ibi_psd_display(method.lombscargle.units)
        raw = LombScarglePSD.compute_lombscargle_psd(
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

    def _psd_carspan(self, method: PsdMethod, *, with_ci: bool = True) -> PSDResult:
        """Dispatch through the unified CARSPAN compute path.

        Used for both ``algorithm="carspan"`` (configurable, any
        ``CarspanOptions``) and ``algorithm="carspan_strict"`` (which
        first forces ``method.carspan`` to :func:`carspan_strict_options`).
        """
        convert, unit = self._carspan_display(method.carspan, method.mean_convention)
        raw = CarspanPSD.compute_carspan_psd(
            self._event_times_clean(),
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

        The strict variant is — by design — just :func:`carspan_strict_options`
        applied through the same compute pipeline as configurable CARSPAN.
        Only ``smooth_for_display``, ``f_max``, and ``plot_units`` are
        carried over from the caller's ``method.carspan``; every other
        field is overridden by the strict preset to match Pascal's
        ``IsRPDataCol=False`` branch (IBI-amplitude DFT, Eq. 3.21). The
        ``method`` field on the returned PSDResult is rebranded to
        ``"carspan_strict"`` so downstream code can tell the two apart.
        """
        strict_opts = CarspanPSD.carspan_strict_options(
            smooth_for_display=bool(method.carspan.smooth_for_display),
            f_max=float(method.carspan.f_max),
            plot_units=str(method.carspan.plot_units),
        )
        strict_method = replace(method, carspan=strict_opts)
        result = self._psd_carspan(strict_method, with_ci=with_ci)
        return replace(result, method="carspan_strict")

    def _psd_carspan_native(self, method: PsdMethod) -> PSDResult:
        """CARSPAN PSD on the resampled-but-un-MA-smoothed grid.

        Mirrors CARSPAN's ``PDSin_BCK`` array — the spectrum immediately
        after resample and **before** the 3-point MA smoother runs. The
        integration path (``band_power`` / ``band_powers``) uses this
        rather than the smoothed display grid: the smoothing changes
        peak heights but not band power, so omitting it keeps the
        reported values clean.

        Implementation: force ``smooth_for_display=False`` on a copy of
        the active ``CarspanOptions`` and dispatch through the unified
        :meth:`_psd_carspan` path. Bin-averaging to the display grid
        still happens inside ``compute_carspan_psd`` (Pascal's
        ``Resample`` is unconditional), but the 3-MA step is skipped.
        """
        # For the strict algorithm, swap in the strict preset first so
        # the right signal/taper/etc. drive the compute layer.
        if method.algorithm == "carspan_strict":
            carspan_opts = CarspanPSD.carspan_strict_options(
                smooth_for_display=False,
                f_max=float(method.carspan.f_max),
                plot_units=str(method.carspan.plot_units),
            )
        else:
            carspan_opts = replace(method.carspan, smooth_for_display=False)

        method_unsmoothed = replace(method, carspan=carspan_opts)
        return self._psd_carspan(method_unsmoothed, with_ci=False)
