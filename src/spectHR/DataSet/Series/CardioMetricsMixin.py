# spectHR/DataSet/Series/CardioMetricsMixin.py
"""
Time-domain heart-rate variability (HRV) metrics.

This mixin provides classical HRV measures computed directly from inter-beat
intervals (IBIs): magnitude-based stats (count, mean, min, max), time-domain
variability (rmssd, sdnn, sdsd), and Poincaré analysis (sd1, sd2, sd_ratio,
ellipse_area).

All methods handle irregular data and excluded beats (NaN, TL, T labels) correctly.

Frequency-domain metrics (PSD, band power) are provided separately by
CardioFrequencyMetricsMixin, which should be mixed in alongside this mixin.
"""

from __future__ import annotations
import numpy as np
from spectHR.DataSet.HRVMetrics import HRVMetric, hrv_metric


# ============================================================================
# Module-level loader functions (re-exported from specialized modules)
# ============================================================================
# Import and re-export loaders so they're accessible via this module
# for backward compatibility with MainWindow and other code.

from spectHR.DataSet.Series.CardioFrequencyMetricsMixin import (
    load_frequency_bands,
    load_method,
    load_ci_alpha,
)
from spectHR.Tools.PSD.WelchPSD import load_welch_params
from spectHR.Tools.PSD.LombScarglePSD import load_lombscargle_params
from spectHR.Tools.PSD.CarspanPSD import load_carspan_params

__all__ = [
    "CardioMetricsMixin",
    "load_frequency_bands",
    "load_method",
    "load_ci_alpha",
    "load_welch_params",
    "load_lombscargle_params",
    "load_carspan_params",
]


class CardioMetricsMixin(HRVMetric):
    """Time-domain HRV metrics.

    Provides classical time-domain measures and Poincaré plot analysis.
    Frequency-domain metrics are provided by CardioFrequencyMetricsMixin,
    which should be mixed in alongside this class.
    """

    METRIC_ORDER = [
        "count",
        "mean",
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
    """Canonical order for metrics (time-domain + frequency bands).

    Note: vlf_power, lf_power, hf_power, lf_hf_ratio are computed via
    CardioFrequencyMetricsMixin.band_power() and are available on CardioSeries
    instances that inherit from both mixins.
    """

    # ========================================================================
    # IBI Data Extraction (used by time-domain metrics)
    # ========================================================================

    def _ibi_clean_ms(self) -> np.ndarray:
        """Return packed valid IBI values in ms, excluding NaN/TL/T.

        Use for magnitude-only metrics (mean, std, min, max, count, sdnn).
        Do NOT use for successive-difference metrics; use
        _successive_diffs_ms() instead to avoid bridging excluded gaps.
        """
        ibi_sec = self.ibi
        if ibi_sec.size == 0:
            return np.array([], dtype=float)
        valid = ~np.isnan(ibi_sec) & (self.labels != "TL") & (self.labels != "T")
        return 1000.0 * ibi_sec[valid]

    def _ibi_ms_full_with_mask(self):
        """Return (ibi_ms, valid) both of length len(self.ibi).

        ibi_ms: IBIs in ms, NaN for invalid intervals.
        valid:  boolean mask, True where IBI is usable.

        Positional adjacency equals temporal adjacency in the recording.
        Used internally by time-domain successive-difference metrics.
        """
        ibi_sec = self.ibi
        if ibi_sec.size == 0:
            return np.array([], dtype=float), np.array([], dtype=bool)
        valid = ~np.isnan(ibi_sec) & (self.labels != "TL") & (self.labels != "T")
        ibi_ms = np.where(valid, 1000.0 * ibi_sec, np.nan)
        return ibi_ms, valid

    # ========================================================================
    # IBI Helper: Successive Differences (time-domain specific)
    # ========================================================================

    def _successive_diffs_ms(self) -> np.ndarray:
        """Differences between consecutive VALID IBIs that were also
        temporally adjacent in the original series.

        Pairs where either interval is invalid are dropped, preventing
        differences from bridging an excluded beat and inflating RMSSD/
        SDSD/SD1/SD2. Returns empty array if no adjacent valid pairs exist.

        Used by: rmssd, sdsd, sd1, sd2 (avoid bridging gaps).
        """
        ibi_ms, valid = self._ibi_ms_full_with_mask()
        if ibi_ms.size < 2:
            return np.array([], dtype=float)
        pair_ok = valid[:-1] & valid[1:]
        if not np.any(pair_ok):
            return np.array([], dtype=float)
        return ibi_ms[1:][pair_ok] - ibi_ms[:-1][pair_ok]

    # ========================================================================
    # Time-Domain Metrics: Magnitude-Based Statistics
    # ========================================================================

    @hrv_metric
    def count(self):
        """Total number of valid inter-beat intervals (count of R-peaks - 1)."""
        return int(self._ibi_clean_ms().size)

    @hrv_metric
    def mean(self):
        """Mean inter-beat interval (ms). Excludes NaN and excluded beats."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.mean(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def min(self):
        """Minimum inter-beat interval (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.min(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def max(self):
        """Maximum inter-beat interval (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.max(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def median(self):
        """Median inter-beat interval (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.median(ibi_ms)) if ibi_ms.size else np.nan

    # ========================================================================
    # Time-Domain Metrics: Variability
    # ========================================================================

    @hrv_metric
    def rmssd(self):
        """Root mean square of successive differences (ms).

        Gap-safe: never bridges excluded beats. Standard HRV marker of
        high-frequency parasympathetic activity.

            RMSSD = sqrt(mean(dIBI_i^2))  where dIBI_i = IBI_i - IBI_{i-1}
        """
        d = self._successive_diffs_ms()
        if d.size == 0:
            return np.nan
        return float(np.sqrt(np.mean(d * d)))

    @hrv_metric
    def sdnn(self):
        """Standard deviation of all inter-beat intervals (ms).

        Overall time-domain variability marker. Uses packed valid IBIs
        (no gap bridging, unlike rmssd).
        """
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def sdsd(self):
        """Standard deviation of successive differences (ms).

        Complements RMSSD; gap-safe to avoid bridging excluded beats.
        """
        d = self._successive_diffs_ms()
        if d.size == 0:
            return np.nan
        return float(np.std(d))

    # ========================================================================
    # Time-Domain Metrics: Poincaré Plot Analysis
    # ========================================================================

    @hrv_metric
    def sd1(self):
        """Poincaré SD1 (minor axis, ms): SD of perpendicular distance
        from the line of identity in the Poincaré plot.

            SD1 = std(dIBI) / sqrt(2)

        Reflects very-short-term parasympathetic (vagal) activity.
        Gap-safe: never bridges excluded beats.
        """
        d = self._successive_diffs_ms()
        if d.size == 0:
            return np.nan
        return float(np.std(d) / np.sqrt(2.0))

    @hrv_metric
    def sd2(self):
        """Poincaré SD2 (major axis, ms): SD along the line of identity.

        Computed via Brennan identity: SD2^2 = 2*Var(IBI) - 0.5*Var(dIBI).
        Reflects long-term sympathetic activity and overall HRV.
        Uses packed valid IBIs for Var(IBI) and gap-safe diffs for Var(dIBI).
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
        """Ratio SD1/SD2: balance between short-term and long-term variability.

        Lower ratio (SD1 << SD2) indicates parasympathetic dominance.
        Returns NaN if SD2 is zero or either metric is invalid.

        Notes
        -----
        For a mathematically uniform IBI series (e.g. synthetic ``[800] * N``)
        ``cumsum`` introduces ULP-level jitter, so ``Var(IBI)`` and ``Var(dIBI)``
        end up at the float64 noise floor (~1e-26).  Brennan's formula
        ``SD2² = 2·Var(IBI) − 0.5·Var(dIBI)`` then produces a tiny positive
        residual instead of zero, leaving SD2 as ~1e-13 ms — which the explicit
        ``s2 == 0`` test below cannot detect.  We therefore additionally guard
        against this degenerate case by checking SDNN (the actual standard
        deviation of IBIs): if SDNN is effectively zero, the ratio is
        meaningless and we return NaN.
        """
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2) or s2 == 0:
            return np.nan

        # Detect a (numerically) uniform IBI series via SDNN.  Any value below
        # 1e-9 ms (one picosecond) is unambiguously float-precision noise; a
        # genuine HRV SDNN is at least many microseconds.
        sdnn = self.sdnn()
        if np.isnan(sdnn) or sdnn < 1e-9:
            return np.nan

        return float(s1 / s2)

    @hrv_metric
    def ellipse_area(self):
        """Area of the Poincaré plot ellipse (ms²).

        Represents overall heart-rate variability in the Poincaré plane.

            Area = π * SD1 * SD2
        """
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2):
            return np.nan
        return float(np.pi * s1 * s2)

    # ========================================================================
    # Frequency-Domain Metrics: Band Powers (require CardioFrequencyMetricsMixin)
    # ========================================================================

    @hrv_metric
    def fullrange_power(self):
        """Total power across the full frequency range (FullRange band).

        Units follow the active PSD method's ``"units"`` workspace setting
        (default: mMI²; optionally ms² for Welch and Lomb-Scargle).
        Returns NaN if FullRange band is not defined or computation fails.

        ``ValueError`` is also caught: PSD back-ends raise it when the series
        is too short (fewer than the minimum required IBIs) or contains no
        valid R-peaks after artefact exclusion (all-TL series).
        """
        try:
            return self.band_power("FullRange")
        except (KeyError, AttributeError, ValueError):
            return np.nan

    @hrv_metric
    def vlf_power(self):
        """Power in the very-low-frequency band (VLF).

        Units follow the active PSD method's ``"units"`` workspace setting
        (default: mMI²; optionally ms² for Welch and Lomb-Scargle).

        Returns NaN when the underlying PSD cannot be computed (too few
        valid IBIs, all beats labelled as artefacts, etc.).
        """
        try:
            return self.band_power("VLF")
        except (KeyError, AttributeError, ValueError):
            return np.nan

    @hrv_metric
    def lf_power(self):
        """Power in the low-frequency band (LF).

        Units follow the active PSD method's ``"units"`` workspace setting
        (default: mMI²; optionally ms² for Welch and Lomb-Scargle).

        Returns NaN when the underlying PSD cannot be computed (too few
        valid IBIs, all beats labelled as artefacts, etc.).
        """
        try:
            return self.band_power("LF")
        except (KeyError, AttributeError, ValueError):
            return np.nan

    @hrv_metric
    def hf_power(self):
        """Power in the high-frequency band (HF).

        Units follow the active PSD method's ``"units"`` workspace setting
        (default: mMI²; optionally ms² for Welch and Lomb-Scargle).

        Returns NaN when the underlying PSD cannot be computed (too few
        valid IBIs, all beats labelled as artefacts, etc.).
        """
        try:
            return self.band_power("HF")
        except (KeyError, AttributeError, ValueError):
            return np.nan

    @hrv_metric
    def lf_hf_ratio(self):
        """LF/HF ratio (dimensionless). NaN if either band is missing or HF is zero.

        Because both LF and HF are expressed in the same units, the ratio is
        independent of the ``"units"`` workspace setting.
        """
        lf, hf = self.lf_power(), self.hf_power()
        if np.isnan(lf) or np.isnan(hf) or hf == 0:
            return np.nan
        return float(lf / hf)

