# spectHR/DataSet/Series/CardioMetricsMixin.py
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import scipy.signal as signal
from scipy.interpolate import interp1d
from scipy.stats import chi2

from spectHR.DataSet.HRVMetrics import HRVMetric, hrv_metric


# ======================================================================
# Module-level configuration — populated from workspace at startup
# ======================================================================

HRV_FREQUENCY_BANDS: Dict[str, Dict] = {
    "VLF": {"low": 0.003, "high": 0.04, "color": "blue"},
    "LF": {"low": 0.04, "high": 0.15, "color": "darkgreen"},
    "HF": {"low": 0.15, "high": 0.40, "color": "red"},
}

WELCH_PARAMS: Dict = {
    "fs": 4.0,
    "nperseg": 256,
    "noverlap": 128,
    "nfft": 1024,
    "window": "hamming",
}

CI_ALPHA: float = 0.05


def load_frequency_bands(bands_config: dict) -> None:
    """
    Update HRV_FREQUENCY_BANDS in place from workspace["FrequencyAnalysis"]["bands"].
    Extra bands in the config are added; missing ones keep their defaults.
    """
    for name, spec in bands_config.items():
        HRV_FREQUENCY_BANDS[name] = {
            "low": float(spec["low"]),
            "high": float(spec["high"]),
            "color": str(spec.get("color", "gray")),
        }


def load_welch_params(welch_config: dict) -> None:
    """
    Update WELCH_PARAMS in place from workspace["FrequencyAnalysis"]["welch"].
    """
    for key in ("fs", "nperseg", "noverlap", "nfft", "window"):
        if key in welch_config:
            WELCH_PARAMS[key] = welch_config[key]


def load_ci_alpha(alpha: float) -> None:
    """
    Update the module-level CI_ALPHA from
    workspace["FrequencyAnalysis"]["confidence_interval_alpha"].
    """
    global CI_ALPHA
    CI_ALPHA = float(alpha)


# ======================================================================
# Mixin
# ======================================================================


class CardioMetricsMixin(HRVMetric):
    """
    Mixin providing HRV metric computation for any object that exposes:
        times  : np.ndarray
        labels : np.ndarray
        ibi    : np.ndarray

    All frequency-domain parameters (band edges, Welch settings, CI alpha)
    are read from the module-level constants above, which are populated at
    application startup from the workspace JSON via workSpace.LoadWorkspace().
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
        Return valid IBI values in milliseconds, excluding NaN, TL, and T labels.
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
        fs: float | None = None,
        nperseg: int | None = None,
        noverlap: int | None = None,
        nfft: int | None = None,
        window: str | None = None,
        interpolate: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute Welch PSD on the IBI series (ms).

        Parameters default to the workspace-configured WELCH_PARAMS when
        not explicitly supplied by the caller.

        Returns empty arrays if there are no usable IBIs or interpolation fails.
        """
        fs = fs if fs is not None else WELCH_PARAMS["fs"]
        nperseg = nperseg if nperseg is not None else WELCH_PARAMS["nperseg"]
        noverlap = noverlap if noverlap is not None else WELCH_PARAMS["noverlap"]
        nfft = nfft if nfft is not None else WELCH_PARAMS["nfft"]
        window = window if window is not None else WELCH_PARAMS["window"]

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
            nfft=nfft,
            nperseg=nperseg,
            noverlap=noverlap,
            window=window,
        )
        return freqs, power

    def welch_psd_with_ci(
        self,
        *,
        alpha: float | None = None,
        **kwargs,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Compute Welch PSD with chi-square confidence intervals.

        alpha defaults to the workspace-configured CI_ALPHA.

        Returns freqs, psd, ci_lower, ci_upper.
        """
        alpha = alpha if alpha is not None else CI_ALPHA

        freqs, psd = self.welch_psd(**kwargs)
        if freqs.size == 0:
            return freqs, psd, psd, psd

        nperseg = kwargs.get("nperseg", WELCH_PARAMS["nperseg"])
        noverlap = kwargs.get("noverlap", WELCH_PARAMS["noverlap"])
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
        Units: ms².  Returns NaN if band has no data.
        """
        if freqs.size == 0:
            return np.nan
        mask = (freqs > f0) & (freqs < f1)
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
        return int(self._ibi_clean_ms().size)

    @hrv_metric
    def mean(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        return float(np.mean(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def std(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def min(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        return float(np.min(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def max(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        return float(np.max(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def median(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        return float(np.median(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def rmssd(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        d = np.diff(ibi_ms)
        return float(np.sqrt(np.mean(d * d)))

    @hrv_metric
    def sdnn(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def sdsd(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        return float(np.std(np.diff(ibi_ms)))

    @hrv_metric
    def sd1(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        return float(np.std((ibi_ms[:-1] - ibi_ms[1:]) / np.sqrt(2.0)))

    @hrv_metric
    def sd2(self) -> float:
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        return float(np.std((ibi_ms[:-1] + ibi_ms[1:]) / np.sqrt(2.0)))

    @hrv_metric
    def sd_ratio(self) -> float:
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2) or s2 == 0:
            return np.nan
        return float(s1 / s2)

    @hrv_metric
    def ellipse_area(self) -> float:
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2):
            return np.nan
        return float(np.pi * s1 * s2)

    @hrv_metric
    def vlf_power(self) -> float:
        """VLF band power in ms² — edges from HRV_FREQUENCY_BANDS."""
        band = HRV_FREQUENCY_BANDS["VLF"]
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, band["low"], band["high"])

    @hrv_metric
    def lf_power(self) -> float:
        """LF band power in ms² — edges from HRV_FREQUENCY_BANDS."""
        band = HRV_FREQUENCY_BANDS["LF"]
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, band["low"], band["high"])

    @hrv_metric
    def hf_power(self) -> float:
        """HF band power in ms² — edges from HRV_FREQUENCY_BANDS."""
        band = HRV_FREQUENCY_BANDS["HF"]
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, band["low"], band["high"])

    @hrv_metric
    def lf_hf_ratio(self) -> float:
        """LF/HF ratio (dimensionless)."""
        lf, hf = self.lf_power(), self.hf_power()
        return float(lf / hf) if hf > 0 else np.nan
