# spectHR/DataSet/Series/CardioMetricsMixin.py
from __future__ import annotations

from typing import Tuple

import numpy as np
import scipy.signal as signal
from scipy.interpolate import interp1d
from scipy.stats import chi2

from spectHR.DataSet.HRVMetrics import HRVMetric, hrv_metric

# Standard HRV frequency bands (Hz).
# Used by both the metric methods and the PSD plot widget.
HRV_FREQUENCY_BANDS = {
    "VLF": (0.003, 0.04),
    "LF": (0.04, 0.15),
    "HF": (0.15, 0.40),
}


class CardioMetricsMixin(HRVMetric):
    """
    Mixin providing HRV metric computation for any object that exposes:
        times  : np.ndarray  (property or attribute)
        labels : np.ndarray  (property or attribute)
        ibi    : np.ndarray  (property)

    Both CardioSeries (data owner) and CardioSeriesView (zero-copy view)
    inherit from this mixin so they share an identical metric implementation
    without either class depending on the other.

    Methods here never mutate labels or times.
    """

    METRIC_ORDER = [
        "count",
        "mean",
        "median",
        "min",
        "max",
        "std",
        "rmssd",
        "sdnn",
        "sdsd",
        "sd1",
        "sd2",
        "sd_ratio",
        "ellipse_area",
        "vlf_power",
        "lf_power",
        "hf_power",
        "lf_hf_ratio",
    ]

    # ------------------------------------------------------------------
    # Core helper
    # ------------------------------------------------------------------

    def _ibi_clean_ms(self) -> np.ndarray:
        """
        Return valid IBI values in milliseconds for HRV metric calculations.

        Excludes:
        - NaN values (trailing alignment NaN, missing data)
        - Intervals labeled "TL" (too long; likely artifacts)
        - Intervals labeled "T"  (degenerate; zero or negative)
        """
        ibi_sec = self.ibi
        if ibi_sec.size == 0:
            return np.array([], dtype=float)
        valid = ~np.isnan(ibi_sec) & (self.labels != "TL") & (self.labels != "T")
        return 1000.0 * ibi_sec[valid]

    # ------------------------------------------------------------------
    # Frequency domain
    # ------------------------------------------------------------------

    def welch_psd(
        self,
        *,
        fs: float = 4.0,
        nperseg: int = 256,
        noverlap: int = 128,
        window: str = "hamming",
        interpolate: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute Welch PSD on the IBI series (ms), optionally interpolated to
        uniform sampling.

        Parameters
        ----------
        fs : float
            Target resampling frequency (Hz) for interpolation.
        nperseg : int
            Segment length for Welch.
        noverlap : int
            Segment overlap.
        window : str
            Window function name (passed to SciPy's Welch).
        interpolate : bool
            If True, interpolate the IBI series to a uniform grid at fs.

        Returns
        -------
        freqs, power : np.ndarray
            Empty arrays if there are no usable IBI samples or interpolation
            fails.
        """
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size == 0:
            return np.ndarray(0), np.ndarray(0)

        if ibi_ms.size < nperseg:
            nperseg = ibi_ms.size
            noverlap = int(ibi_ms.size / 2) if ibi_ms.size >= 2 else 0

        ibi_times = self.times[: ibi_ms.size]

        if interpolate:
            try:
                if ibi_times.size >= 2:
                    t_uniform = np.arange(ibi_times[0], ibi_times[-1], 1.0 / fs)
                    ibi_ms = interp1d(
                        ibi_times,
                        ibi_ms,
                        kind="linear",
                        fill_value="extrapolate",
                    )(t_uniform)
            except Exception:
                return np.ndarray(0), np.ndarray(0)

        freqs, power = signal.welch(
            ibi_ms,
            fs=fs,
            scaling="density",
            nfft=1024,
            nperseg=nperseg,
            noverlap=noverlap,
            window=window,
        )
        return freqs, power

    def welch_psd_with_ci(
        self,
        *,
        fs: float = 4.0,
        nperseg: int = 256,
        noverlap: int = 128,
        window: str = "hamming",
        interpolate: bool = True,
        alpha: float = 0.05,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Compute Welch PSD with chi-square confidence intervals.

        Returns
        -------
        freqs, psd, ci_lower, ci_upper
        """
        freqs, psd = self.welch_psd(
            fs=fs,
            nperseg=nperseg,
            noverlap=noverlap,
            window=window,
            interpolate=interpolate,
        )
        if freqs.size == 0:
            return freqs, psd, psd, psd

        step = nperseg - noverlap
        n_segments = max(1, int(np.floor((psd.size * step) / nperseg)))
        nu = 2 * n_segments
        ci_lower = (nu * psd) / chi2.ppf(1 - alpha / 2, nu)
        ci_upper = (nu * psd) / chi2.ppf(alpha / 2, nu)
        return freqs, psd, ci_lower, ci_upper

    def _band_power_exact(
        self,
        freqs: np.ndarray,
        power: np.ndarray,
        f0: float,
        f1: float,
    ) -> float:
        """
        Band power by trapezoidal integration with endpoint interpolation.

        Returns NaN if inputs are empty or the band contains no frequencies.
        Units: ms² (same as PSD integrated over Hz).
        """
        if freqs.size == 0:
            return np.nan
        mask = (freqs >= f0) & (freqs < f1)
        if not np.any(mask):
            return np.nan
        p0 = np.interp(f0, freqs, power)
        p1 = np.interp(f1, freqs, power)
        f_band = np.concatenate(([f0], freqs[mask], [f1]))
        p_band = np.concatenate(([p0], power[mask], [p1]))
        return float(np.trapezoid(p_band, f_band))

    # ------------------------------------------------------------------
    # HRV metrics
    # ------------------------------------------------------------------

    @hrv_metric
    def count(self) -> int:
        """Number of valid IBIs after NaN and artifact removal."""
        return int(self._ibi_clean_ms().size)

    @hrv_metric
    def mean(self) -> float:
        """Mean IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.mean(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def std(self) -> float:
        """Standard deviation of IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def min(self) -> float:
        """Minimum IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.min(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def max(self) -> float:
        """Maximum IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.max(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def median(self) -> float:
        """Median IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.median(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def rmssd(self) -> float:
        """Root mean square of successive differences (ms)."""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        d = np.diff(ibi_ms)
        return float(np.sqrt(np.mean(d * d)))

    @hrv_metric
    def sdnn(self) -> float:
        """SDNN (ms): standard deviation of IBI."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def sdsd(self) -> float:
        """SDSD (ms): standard deviation of successive differences."""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        return float(np.std(np.diff(ibi_ms)))

    @hrv_metric
    def sd1(self) -> float:
        """SD1 (ms) — short-term Poincaré variability."""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        return float(np.std((ibi_ms[:-1] - ibi_ms[1:]) / np.sqrt(2.0)))

    @hrv_metric
    def sd2(self) -> float:
        """SD2 (ms) — long-term Poincaré variability."""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        return float(np.std((ibi_ms[:-1] + ibi_ms[1:]) / np.sqrt(2.0)))

    @hrv_metric
    def sd_ratio(self) -> float:
        """SD1/SD2 ratio (dimensionless)."""
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2) or s2 == 0:
            return np.nan
        return float(s1 / s2)

    @hrv_metric
    def ellipse_area(self) -> float:
        """Area of the Poincaré ellipse (π · SD1 · SD2) in ms²."""
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2):
            return np.nan
        return float(np.pi * s1 * s2)

    @hrv_metric
    def vlf_power(self) -> float:
        """VLF band power in ms²."""
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, *HRV_FREQUENCY_BANDS["VLF"])

    @hrv_metric
    def lf_power(self) -> float:
        """LF band power in ms²."""
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, *HRV_FREQUENCY_BANDS["LF"])

    @hrv_metric
    def hf_power(self) -> float:
        """HF band power in ms²."""
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, *HRV_FREQUENCY_BANDS["HF"])

    @hrv_metric
    def lf_hf_ratio(self) -> float:
        """LF/HF ratio (dimensionless)."""
        lf, hf = self.lf_power(), self.hf_power()
        return float(lf / hf) if hf > 0 else np.nan
