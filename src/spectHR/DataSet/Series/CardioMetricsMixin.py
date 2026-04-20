# spectHR/DataSet/Series/CardioMetricsMixin.py
from __future__ import annotations
from typing import Dict, Tuple
import numpy as np
import scipy.signal as signal
from scipy.interpolate import interp1d
from scipy.stats import chi2
from spectHR.DataSet.HRVMetrics import HRVMetric, hrv_metric

HRV_FREQUENCY_BANDS: Dict[str, Dict] = {
    "VLF": {"low": 0.003, "high": 0.04,  "color": "blue"},
    "LF":  {"low": 0.04,  "high": 0.15,  "color": "darkgreen"},
    "HF":  {"low": 0.15,  "high": 0.40,  "color": "red"},
}
WELCH_PARAMS: Dict = {
    "fs":       4.0,
    "nperseg":  256,
    "noverlap": 128,
    "nfft":     None,
    "window":   "hann",
}
LOMBSCARGLE_PARAMS: Dict = {
    "nfreqs":     1000,
    "fmin_floor": 1e-4,
}
CARSPAN_PARAMS: Dict = {
    "freq_resolution":    0.01,
    "window":             "hann",
    "smooth_for_display": True,
}
CI_ALPHA: float = 0.05
METHOD: str = "welch"

def load_frequency_bands(bands_config: dict) -> None:
    for name, spec in bands_config.items():
        HRV_FREQUENCY_BANDS[name] = {
            "low":   float(spec["low"]),
            "high":  float(spec["high"]),
            "color": str(spec.get("color", "gray")),
        }

def load_welch_params(welch_config: dict) -> None:
    for key in ("fs", "nperseg", "noverlap", "nfft", "window"):
        if key in welch_config:
            WELCH_PARAMS[key] = welch_config[key]

def load_lombscargle_params(ls_config: dict) -> None:
    for key in ("nfreqs", "fmin_floor"):
        if key in ls_config:
            LOMBSCARGLE_PARAMS[key] = ls_config[key]

def load_carspan_params(cs_config: dict) -> None:
    for key in ("freq_resolution", "window", "smooth_for_display"):
        if key in cs_config:
            CARSPAN_PARAMS[key] = cs_config[key]

def load_ci_alpha(alpha: float) -> None:
    global CI_ALPHA
    CI_ALPHA = float(alpha)

def load_method(method: str) -> None:
    global METHOD
    m = str(method).lower().strip()
    if m not in ("welch", "lombscargle", "carspan"):
        raise ValueError(
            f"Unknown PSD method {method!r}. "
            "Must be 'welch', 'lombscargle', or 'carspan'."
        )
    METHOD = m

class CardioMetricsMixin(HRVMetric):
    METRIC_ORDER = [
        "count", "mean", "median", "min", "max", "std",
        "rmssd", "sdnn", "sdsd",
        "sd1", "sd2", "sd_ratio", "ellipse_area",
        "vlf_power", "lf_power", "hf_power", "lf_hf_ratio",
    ]

    def _ibi_clean_ms(self) -> np.ndarray:
        """Return packed valid IBI values in ms, excluding NaN/TL/T.
        Use for magnitude-only metrics (mean, std, min, max, count, sdnn).
        Do NOT use for successive-difference metrics; use
        _successive_diffs_ms() instead to avoid bridging excluded gaps."""
        ibi_sec = self.ibi
        if ibi_sec.size == 0:
            return np.array([], dtype=float)
        valid = (
            ~np.isnan(ibi_sec)
            & (self.labels != "TL")
            & (self.labels != "T")
        )
        return 1000.0 * ibi_sec[valid]

    def _ibi_ms_full_with_mask(self):
        """Return (ibi_ms, valid) both of length len(self.ibi).
        ibi_ms: IBIs in ms, NaN for invalid intervals.
        valid:  boolean mask, True where IBI is usable.
        Positional adjacency equals temporal adjacency in the recording."""
        ibi_sec = self.ibi
        if ibi_sec.size == 0:
            return np.array([], dtype=float), np.array([], dtype=bool)
        valid = (
            ~np.isnan(ibi_sec)
            & (self.labels != "TL")
            & (self.labels != "T")
        )
        ibi_ms = np.where(valid, 1000.0 * ibi_sec, np.nan)
        return ibi_ms, valid

    def _successive_diffs_ms(self) -> np.ndarray:
        """Differences between consecutive VALID IBIs that were also
        temporally adjacent in the original series.
        Pairs where either interval is invalid are dropped, preventing
        differences from bridging an excluded beat and inflating RMSSD/
        SDSD/SD1/SD2. Returns empty array if no adjacent valid pairs exist."""
        ibi_ms, valid = self._ibi_ms_full_with_mask()
        if ibi_ms.size < 2:
            return np.array([], dtype=float)
        pair_ok = valid[:-1] & valid[1:]
        if not np.any(pair_ok):
            return np.array([], dtype=float)
        return ibi_ms[1:][pair_ok] - ibi_ms[:-1][pair_ok]

    def _carspan_normalise(self, power_raw: float) -> float:
        """Convert raw DFT band-power (s^2/Hz) to mMI2:
        power_mMI2 = power_raw * mean_IBI_sec^2 * 1e6"""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size == 0:
            return np.nan
        mean_ibi_sec = float(np.mean(ibi_ms)) / 1000.0
        if mean_ibi_sec == 0.0:
            return np.nan
        return (power_raw * (mean_ibi_sec ** 2)) * 1_000_000.0

    def welch_psd(self, *, fs=None, nperseg=None, noverlap=None,
                  nfft=None, window=None, interpolate=True):
        fs       = fs       if fs       is not None else WELCH_PARAMS["fs"]
        nperseg  = nperseg  if nperseg  is not None else WELCH_PARAMS["nperseg"]
        noverlap = noverlap if noverlap is not None else WELCH_PARAMS["noverlap"]
        nfft     = nfft     if nfft     is not None else WELCH_PARAMS["nfft"]
        window   = window   if window   is not None else WELCH_PARAMS["window"]
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size == 0:
            return np.ndarray(0), np.ndarray(0)
        if ibi_ms.size < nperseg:
            nperseg  = ibi_ms.size
            noverlap = int(ibi_ms.size / 2) if ibi_ms.size >= 2 else 0
        ibi_times = self.times[: ibi_ms.size]
        if interpolate:
            try:
                if ibi_times.size >= 2:
                    t_uniform = np.arange(ibi_times[0], ibi_times[-1], 1.0 / fs)
                    ibi_ms = interp1d(
                        ibi_times, ibi_ms,
                        kind="linear", fill_value="extrapolate",
                    )(t_uniform)
            except Exception:
                return np.ndarray(0), np.ndarray(0)
        freqs, power = signal.welch(
            ibi_ms, fs=fs, scaling="density",
            nfft=nfft, nperseg=nperseg, noverlap=noverlap, window=window,
        )
        return freqs, power

    @staticmethod
    def _welch_effective_dof(*, n_samples, nperseg, noverlap, window):
        """Effective chi-square degrees of freedom for Welch's method.
        nu = 2 * K * W_eff / (1 + 2 * sum_{k>=1} (1-k/K) * rho^2(k))
        where K = segment count, W_eff = noise bandwidth, rho(k) =
        inter-segment correlation. All computed from the window array.
        Sanity: rectangular no-overlap -> nu=2K; Hann 50% -> nu~8K/3."""
        step = max(1, nperseg - noverlap)
        K = (1 + (n_samples - nperseg) // step) if n_samples >= nperseg else 1
        K = max(1, int(K))
        try:
            w = signal.get_window(window, nperseg).astype(float)
        except Exception:
            w = np.ones(nperseg, dtype=float)
        sw  = float(np.sum(w))
        sw2 = float(np.sum(w * w))
        if sw <= 0.0 or sw2 <= 0.0:
            return max(2, 2 * K)
        W_eff = nperseg * sw2 / (sw * sw)
        corr_sum = 0.0
        k = 1
        while k < K and k * step < nperseg:
            shift = k * step
            c = float(np.sum(w[: nperseg - shift] * w[shift:])) / sw2
            corr_sum += (1.0 - k / K) * (c * c)
            k += 1
        denom = 1.0 + 2.0 * corr_sum
        nu    = 2.0 * K * W_eff / denom
        return max(2, int(round(nu)))

    def welch_psd_with_ci(self, *, alpha=None, **kwargs):
        """Welch PSD with chi-square CI. DoF corrected for actual segment
        count (from resampled signal length, NOT psd.size), window noise
        bandwidth, and between-segment overlap correlation."""
        alpha = alpha if alpha is not None else CI_ALPHA
        freqs, psd = self.welch_psd(**kwargs)
        if freqs.size == 0:
            return freqs, psd, psd, psd
        fs       = kwargs.get("fs",       WELCH_PARAMS["fs"])
        nperseg  = kwargs.get("nperseg",  WELCH_PARAMS["nperseg"])
        noverlap = kwargs.get("noverlap", WELCH_PARAMS["noverlap"])
        window   = kwargs.get("window",   WELCH_PARAMS["window"])
        ibi_ms    = self._ibi_clean_ms()
        ibi_times = self.times[: ibi_ms.size]
        if ibi_times.size >= 2:
            n_samples = int(np.floor((ibi_times[-1] - ibi_times[0]) * fs))
        else:
            n_samples = int(ibi_ms.size)
        n_samples = max(1, n_samples)
        if n_samples < nperseg:
            nperseg_eff  = max(1, n_samples)
            noverlap_eff = nperseg_eff // 2 if nperseg_eff >= 2 else 0
        else:
            nperseg_eff  = int(nperseg)
            noverlap_eff = int(noverlap)
        nu = self._welch_effective_dof(
            n_samples=n_samples,
            nperseg=nperseg_eff,
            noverlap=noverlap_eff,
            window=window,
        )
        ci_lower = (nu * psd) / chi2.ppf(1.0 - alpha / 2.0, nu)
        ci_upper = (nu * psd) / chi2.ppf(alpha / 2.0, nu)
        return freqs, psd, ci_lower, ci_upper

    def lombscargle_psd(self):
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 4:
            return np.ndarray(0), np.ndarray(0)
        ibi_times  = self.times[: ibi_ms.size]
        nfreqs     = LOMBSCARGLE_PARAMS["nfreqs"]
        fmin_floor = LOMBSCARGLE_PARAMS["fmin_floor"]
        try:
            f_max     = max(s["high"] for s in HRV_FREQUENCY_BANDS.values())
            freqs     = np.linspace(fmin_floor, f_max, nfreqs)
            ang_freqs = 2.0 * np.pi * freqs
            ibi_zero  = ibi_ms - ibi_ms.mean()
            pgram     = signal.lombscargle(ibi_times, ibi_zero, ang_freqs, normalize=False)
            T         = float(ibi_times[-1] - ibi_times[0])
            N         = float(ibi_ms.size)
            power     = (2.0 * T / (N ** 2)) * pgram
        except Exception:
            return np.ndarray(0), np.ndarray(0)
        freqs = np.concatenate(([fmin_floor], freqs))
        power = np.concatenate(([0.0], power))
        return freqs, power

    def lombscargle_psd_with_ci(self, *, alpha=None):
        alpha = alpha if alpha is not None else CI_ALPHA
        freqs, psd = self.lombscargle_psd()
        if freqs.size == 0:
            return freqs, psd, psd, psd
        ibi_ms    = self._ibi_clean_ms()
        ibi_times = self.times[: ibi_ms.size]
        T     = float(ibi_times[-1] - ibi_times[0])
        f_min = float(freqs[0])
        f_max = float(freqs[-1])
        n_eff = max(1, int(2.0 * (f_max - f_min) * T))
        nu    = 2 * n_eff
        ci_lower = (nu * psd) / chi2.ppf(1 - alpha / 2, nu)
        ci_upper = (nu * psd) / chi2.ppf(alpha / 2, nu)
        return freqs, psd, ci_lower, ci_upper

    def carspan_psd(self):
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 4:
            return np.ndarray(0), np.ndarray(0)
        ibi_times = self.times[: ibi_ms.size]
        T = float(ibi_times[-1] - ibi_times[0])
        if T <= 0:
            return np.ndarray(0), np.ndarray(0)
        N = ibi_ms.size
        win_name = CARSPAN_PARAMS["window"]
        try:
            win = signal.get_window(win_name, N)
        except Exception:
            win = np.ones(N)
        f_max        = max(s["high"] for s in HRV_FREQUENCY_BANDS.values())
        k_max        = int(np.ceil(f_max * T))
        k_vals       = np.arange(1, k_max + 1)
        freqs_native = k_vals / T
        phases       = -2.0 * np.pi * np.outer(ibi_times, freqs_native)
        X_real       = np.dot(win, np.cos(phases))
        X_imag       = np.dot(win, np.sin(phases))
        power_native = (2.0 / T) * (X_real ** 2 + X_imag ** 2)
        freq_res     = float(CARSPAN_PARAMS["freq_resolution"])
        f_min_band   = min(s["low"] for s in HRV_FREQUENCY_BANDS.values())
        freqs_out    = np.arange(f_min_band, f_max + freq_res / 2, freq_res)
        freqs_out    = freqs_out[freqs_out <= f_max]
        if freqs_native.size < 2:
            return np.ndarray(0), np.ndarray(0)
        power_out = np.interp(freqs_out, freqs_native, power_native)
        if CARSPAN_PARAMS.get("smooth_for_display", True) and power_out.size >= 3:
            kernel   = np.array([1.0, 1.0, 1.0]) / 3.0
            smoothed = np.convolve(power_out, kernel, mode="same")
            smoothed[0]  = (power_out[0]  + power_out[1])  / 2.0
            smoothed[-1] = (power_out[-2] + power_out[-1]) / 2.0
            power_out = smoothed
        return freqs_out, power_out

    def carspan_psd_with_ci(self, *, alpha=None):
        alpha = alpha if alpha is not None else CI_ALPHA
        freqs, psd = self.carspan_psd()
        if freqs.size == 0:
            return freqs, psd, psd, psd
        ibi_ms    = self._ibi_clean_ms()
        ibi_times = self.times[: ibi_ms.size]
        T         = float(ibi_times[-1] - ibi_times[0])
        freq_res  = float(CARSPAN_PARAMS["freq_resolution"])
        n_per_point = max(1, int(round(freq_res * T)))
        nu = 2 * n_per_point
        ci_lower = (nu * psd) / chi2.ppf(1 - alpha / 2, nu)
        ci_upper = (nu * psd) / chi2.ppf(alpha / 2, nu)
        return freqs, psd, ci_lower, ci_upper

    def psd_with_ci(self, *, alpha=None, **kwargs):
        if METHOD == "lombscargle":
            return self.lombscargle_psd_with_ci(alpha=alpha)
        elif METHOD == "carspan":
            return self.carspan_psd_with_ci(alpha=alpha)
        else:
            return self.welch_psd_with_ci(alpha=alpha, **kwargs)

    def _band_power_exact(self, freqs, power, f0, f1):
        if freqs.size == 0:
            return np.nan
        mask = (freqs > f0) & (freqs < f1)
        if not np.any(mask):
            return np.nan
        p0     = np.interp(f0, freqs, power)
        p1     = np.interp(f1, freqs, power)
        f_band = np.concatenate(([f0], freqs[mask], [f1]))
        p_band = np.concatenate(([p0], power[mask], [p1]))
        return float(np.trapezoid(p_band, f_band))

    def _carspan_psd_native(self):
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 4:
            return np.ndarray(0), np.ndarray(0)
        ibi_times = self.times[: ibi_ms.size]
        T = float(ibi_times[-1] - ibi_times[0])
        if T <= 0:
            return np.ndarray(0), np.ndarray(0)
        N = ibi_ms.size
        win_name = CARSPAN_PARAMS["window"]
        try:
            win = signal.get_window(win_name, N)
        except Exception:
            win = np.ones(N)
        f_max        = max(s["high"] for s in HRV_FREQUENCY_BANDS.values())
        k_max        = int(np.ceil(f_max * T))
        freqs_native = np.arange(1, k_max + 1) / T
        phases       = -2.0 * np.pi * np.outer(ibi_times, freqs_native)
        X_real       = np.dot(win, np.cos(phases))
        X_imag       = np.dot(win, np.sin(phases))
        power_native = (2.0 / T) * (X_real ** 2 + X_imag ** 2)
        return freqs_native, power_native

    def _carspan_band_power_native(self, f0, f1):
        freqs_native, power_native = self._carspan_psd_native()
        if freqs_native.size == 0:
            return np.nan
        T       = float(self.times[: self._ibi_clean_ms().size][-1] - self.times[0])
        delta_f = 1.0 / T
        mask    = (freqs_native >= f0) & (freqs_native <= f1)
        if not np.any(mask):
            return np.nan
        return float(np.sum(power_native[mask]) * delta_f)

    def _band_power(self, band_name):
        band = HRV_FREQUENCY_BANDS[band_name]
        if METHOD == "carspan":
            power_raw = self._carspan_band_power_native(band["low"], band["high"])
            return self._carspan_normalise(power_raw)
        freqs, power, _, _ = self.psd_with_ci()
        return self._band_power_exact(freqs, power, band["low"], band["high"])

    @hrv_metric
    def count(self):
        return int(self._ibi_clean_ms().size)

    @hrv_metric
    def mean(self):
        ibi_ms = self._ibi_clean_ms()
        return float(np.mean(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def std(self):
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def min(self):
        ibi_ms = self._ibi_clean_ms()
        return float(np.min(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def max(self):
        ibi_ms = self._ibi_clean_ms()
        return float(np.max(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def median(self):
        ibi_ms = self._ibi_clean_ms()
        return float(np.median(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def rmssd(self):
        """RMS of successive differences. Gap-safe: never bridges excluded beats."""
        d = self._successive_diffs_ms()
        if d.size == 0:
            return np.nan
        return float(np.sqrt(np.mean(d * d)))

    @hrv_metric
    def sdnn(self):
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def sdsd(self):
        """SD of successive differences. Gap-safe: never bridges excluded beats."""
        d = self._successive_diffs_ms()
        if d.size == 0:
            return np.nan
        return float(np.std(d))

    @hrv_metric
    def sd1(self):
        """Poincare SD1 = std(dIBI)/sqrt(2). Gap-safe."""
        d = self._successive_diffs_ms()
        if d.size == 0:
            return np.nan
        return float(np.std(d) / np.sqrt(2.0))

    @hrv_metric
    def sd2(self):
        """Poincare SD2 via Brennan identity: SD2^2 = 2*Var(IBI) - 0.5*Var(dIBI).
        Uses packed valid IBIs for Var(IBI) and gap-safe diffs for Var(dIBI)."""
        ibi_ms = self._ibi_clean_ms()
        d      = self._successive_diffs_ms()
        if ibi_ms.size < 2 or d.size == 0:
            return np.nan
        val = 2.0 * float(np.var(ibi_ms)) - 0.5 * float(np.var(d))
        if val <= 0.0:
            return np.nan
        return float(np.sqrt(val))

    @hrv_metric
    def sd_ratio(self):
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2) or s2 == 0:
            return np.nan
        return float(s1 / s2)

    @hrv_metric
    def ellipse_area(self):
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2):
            return np.nan
        return float(np.pi * s1 * s2)

    @hrv_metric
    def vlf_power(self):
        return self._band_power("VLF")

    @hrv_metric
    def lf_power(self):
        return self._band_power("LF")

    @hrv_metric
    def hf_power(self):
        return self._band_power("HF")

    @hrv_metric
    def lf_hf_ratio(self):
        lf, hf = self.lf_power(), self.hf_power()
        return float(lf / hf) if hf and hf > 0 else np.nan
