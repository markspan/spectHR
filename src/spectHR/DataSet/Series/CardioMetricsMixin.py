# spectHR/DataSet/Series/CardioMetricsMixin.py
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import scipy.signal as signal
from scipy.interpolate import interp1d
from scipy.stats import chi2
from astropy.timeseries import LombScargle

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
    "fs": 100.0,
    "nperseg": 256,
    "noverlap": 128,
    "nfft": None,
    "window": "hamming",
}

LOMBSCARGLE_PARAMS: Dict = {
    "nfreqs": 1000,  # number of frequency grid points
    "fmin_floor": 1e-4,  # lower bound floor (Hz) — avoids evaluating at zero
}

CI_ALPHA: float = 0.05

# "welch" or "lombscargle" — updated by load_method() at startup
METHOD: str = "welch"


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


def load_lombscargle_params(ls_config: dict) -> None:
    """
    Update LOMBSCARGLE_PARAMS in place from workspace["FrequencyAnalysis"]["lombscargle"].
    """
    for key in ("nfreqs", "fmin_floor"):
        if key in ls_config:
            LOMBSCARGLE_PARAMS[key] = ls_config[key]


def load_ci_alpha(alpha: float) -> None:
    """
    Update the module-level CI_ALPHA from
    workspace["FrequencyAnalysis"]["confidence_interval_alpha"].
    """
    global CI_ALPHA
    CI_ALPHA = float(alpha)


def load_method(method: str) -> None:
    """
    Update the module-level METHOD from workspace["FrequencyAnalysis"]["method"].
    Accepted values (case-insensitive): "welch", "lombscargle".
    """
    global METHOD
    m = str(method).lower().strip()
    if m not in ("welch", "lombscargle"):
        raise ValueError(
            f"Unknown PSD method {method!r}. Must be 'welch' or 'lombscargle'."
        )
    METHOD = m


# ======================================================================
# Mixin
# ======================================================================


class CardioMetricsMixin(HRVMetric):
    """
    Mixin providing HRV metric computation for any object that exposes:
        times  : np.ndarray
        labels : np.ndarray
        ibi    : np.ndarray

    All frequency-domain parameters (band edges, Welch settings, CI alpha,
    and method choice) are read from the module-level constants above, which
    are populated at application startup from the workspace JSON via
    workSpace.LoadWorkspace().

    PSD dispatch
    ------------
    ``psd_with_ci()`` is the single public entry point used by the band-power
    metrics and the plot widget.  It routes to Welch or Lomb-Scargle based on
    the workspace-configured METHOD and always returns
    ``(freqs, psd, ci_lower, ci_upper)``.
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
    # Welch back-end
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
        Compute Welch PSD on the IBI series (ms), resampled to a uniform grid.

        Parameters default to the workspace-configured WELCH_PARAMS when not
        explicitly supplied by the caller.

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

    # ------------------------------------------------------------------
    # Lomb-Scargle back-end
    # ------------------------------------------------------------------

    def lombscargle_psd(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute Lomb-Scargle PSD on the *unevenly sampled* IBI series (ms).

        Uses astropy.timeseries.LombScargle with PSD normalisation.
        No interpolation is applied — the native strength of Lomb-Scargle is
        that it handles irregular timestamps directly.

        Parameters are read from the module-level LOMBSCARGLE_PARAMS.
        Returns empty arrays if there are fewer than 4 usable IBIs.
        """
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 4:
            return np.ndarray(0), np.ndarray(0)

        ibi_times = self.times[: ibi_ms.size]  # seconds, irregular

        nfreqs = LOMBSCARGLE_PARAMS["nfreqs"]
        fmin_floor = LOMBSCARGLE_PARAMS["fmin_floor"]

        try:
            # Evaluate on a frequency grid spanning all configured HRV bands
            f_min = min(s["low"] for s in HRV_FREQUENCY_BANDS.values())
            f_max = max(s["high"] for s in HRV_FREQUENCY_BANDS.values())
            freqs = np.linspace(max(f_min, fmin_floor), f_max, nfreqs)

            power = LombScargle(ibi_times, ibi_ms).power(freqs, normalization="psd")
            power = np.asarray(power).ravel()  # astropy can return 2-D
        except Exception:
            return np.ndarray(0), np.ndarray(0)

        return freqs, power

    def lombscargle_psd_with_ci(
        self,
        *,
        alpha: float | None = None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Compute Lomb-Scargle PSD with chi-square confidence intervals.

        Each frequency bin of the Lomb-Scargle periodogram has approximately
        2 degrees of freedom, so a chi²(2) distribution is used — the standard
        approach for Lomb-Scargle CIs.

        alpha defaults to the workspace-configured CI_ALPHA.
        Returns freqs, psd, ci_lower, ci_upper.
        """
        alpha = alpha if alpha is not None else CI_ALPHA
        freqs, psd = self.lombscargle_psd()
        if freqs.size == 0:
            return freqs, psd, psd, psd

        nu = 2  # degrees of freedom per bin for Lomb-Scargle
        ci_lower = (nu * psd) / chi2.ppf(1 - alpha / 2, nu)
        ci_upper = (nu * psd) / chi2.ppf(alpha / 2, nu)
        return freqs, psd, ci_lower, ci_upper

    # ------------------------------------------------------------------
    # Unified dispatcher — used by metrics and the plot widget
    # ------------------------------------------------------------------

    def psd_with_ci(
        self,
        *,
        alpha: float | None = None,
        **kwargs,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Compute PSD with confidence intervals using the method set in the
        workspace (module-level METHOD constant).

        Routes to ``welch_psd_with_ci`` or ``lombscargle_psd_with_ci``
        and always returns ``(freqs, psd, ci_lower, ci_upper)``.
        """
        if METHOD == "lombscargle":
            return self.lombscargle_psd_with_ci(alpha=alpha)
        else:
            return self.welch_psd_with_ci(alpha=alpha, **kwargs)

    # ------------------------------------------------------------------
    # Band-power helper
    # ------------------------------------------------------------------

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
        """VLF band power in ms² — uses the active PSD method."""
        band = HRV_FREQUENCY_BANDS["VLF"]
        freqs, power, _, _ = self.psd_with_ci()
        return self._band_power_exact(freqs, power, band["low"], band["high"])

    @hrv_metric
    def lf_power(self) -> float:
        """LF band power in ms² — uses the active PSD method."""
        band = HRV_FREQUENCY_BANDS["LF"]
        freqs, power, _, _ = self.psd_with_ci()
        return self._band_power_exact(freqs, power, band["low"], band["high"])

    @hrv_metric
    def hf_power(self) -> float:
        """HF band power in ms² — uses the active PSD method."""
        band = HRV_FREQUENCY_BANDS["HF"]
        freqs, power, _, _ = self.psd_with_ci()
        return self._band_power_exact(freqs, power, band["low"], band["high"])

    @hrv_metric
    def lf_hf_ratio(self) -> float:
        """LF/HF ratio (dimensionless)."""
        lf, hf = self.lf_power(), self.hf_power()
        return float(lf / hf) if hf > 0 else np.nan
