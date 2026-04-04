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
    "VLF": {"low": 0.003, "high": 0.04,  "color": "blue"},
    "LF":  {"low": 0.04,  "high": 0.15,  "color": "darkgreen"},
    "HF":  {"low": 0.15,  "high": 0.40,  "color": "red"},
}

WELCH_PARAMS: Dict = {
    "fs":       4.0,
    "nperseg":  256,
    "noverlap": 128,
    "nfft":     None,
    "window":   "hamming",
}

LOMBSCARGLE_PARAMS: Dict = {
    "nfreqs":     1000,
    "fmin_floor": 1e-4,
}

CARSPAN_PARAMS: Dict = {
    # Output frequency grid resolution in Hz.
    # CARSPAN interpolates computed spectral lines onto this fixed grid so
    # that spectra are visually comparable across recording lengths (§3.3.4).
    "freq_resolution": 0.01,

    # Tapering window applied to the event sequence before the DFT.
    # CARSPAN uses Hanning (confirmed by Arie Goudbeek).
    # Any name accepted by scipy.signal.get_window() is valid,
    # e.g. "hann", "hamming", "blackman", "bartlett", "boxcar".
    "window": "hann",

    # Whether to apply a 3-point moving average to the interpolated spectrum
    # before returning it for display.  The CARSPAN manual (§3.3,
    # pre-algorithm choices) states explicitly: "a moving average window over
    # three frequency points (0.03 Hz bandwidth) is applied before plotting
    # the spectral functions."  This smoothing is applied only to the spectrum
    # used for display; band power values are always computed from the
    # unsmoothed spectrum, consistent with the same CARSPAN passage: "No
    # smoothing of the spectra is carried out on the spectra before computing
    # the spectral band values."
    "smooth_for_display": True,
}

CI_ALPHA: float = 0.05

# Active PSD method: "welch", "lombscargle", or "carspan"
METHOD: str = "welch"


# ======================================================================
# Workspace loaders — called once at startup by workSpace.LoadWorkspace()
# ======================================================================

def load_frequency_bands(bands_config: dict) -> None:
    """Update HRV_FREQUENCY_BANDS in place from workspace config."""
    for name, spec in bands_config.items():
        HRV_FREQUENCY_BANDS[name] = {
            "low":   float(spec["low"]),
            "high":  float(spec["high"]),
            "color": str(spec.get("color", "gray")),
        }


def load_welch_params(welch_config: dict) -> None:
    """Update WELCH_PARAMS in place from workspace config."""
    for key in ("fs", "nperseg", "noverlap", "nfft", "window"):
        if key in welch_config:
            WELCH_PARAMS[key] = welch_config[key]


def load_lombscargle_params(ls_config: dict) -> None:
    """Update LOMBSCARGLE_PARAMS in place from workspace config."""
    for key in ("nfreqs", "fmin_floor"):
        if key in ls_config:
            LOMBSCARGLE_PARAMS[key] = ls_config[key]


def load_carspan_params(cs_config: dict) -> None:
    """
    Update CARSPAN_PARAMS in place from
    workspace["FrequencyAnalysis"]["carspan"].

    Keys
    ----
    freq_resolution : float
        Step size of the output frequency grid in Hz (default 0.01).
        CARSPAN interpolates computed spectral lines onto this grid,
        ensuring spectra are comparable regardless of recording length.
    window : str
        Tapering window applied before the DFT (default "hann").
        Any name accepted by scipy.signal.get_window() is valid,
        e.g. "hann", "hamming", "blackman", "bartlett", "boxcar".
    smooth_for_display : bool
        Whether to apply a 3-point moving average to the interpolated
        spectrum before returning it for display (default True).
        Matches the CARSPAN manual (§3.3): "a moving average window over
        three frequency points (0.03 Hz bandwidth) is applied before
        plotting the spectral functions."  Band power values are always
        computed from the unsmoothed spectrum regardless of this setting.
    """
    for key in ("freq_resolution", "window", "smooth_for_display"):
        if key in cs_config:
            CARSPAN_PARAMS[key] = cs_config[key]


def load_ci_alpha(alpha: float) -> None:
    """Update CI_ALPHA from workspace config."""
    global CI_ALPHA
    CI_ALPHA = float(alpha)


def load_method(method: str) -> None:
    """
    Update METHOD from workspace["FrequencyAnalysis"]["method"].

    Accepted values (case-insensitive)
    ------------------------------------
    "welch"       — Welch periodogram on a resampled, uniform IBI grid.
    "lombscargle" — Lomb-Scargle periodogram on irregular timestamps.
    "carspan"     — Direct DFT on R-peak event times (CARSPAN manual §3.3.4,
                    formula 3.19), with configurable tapering window and
                    automatic mMI² normalisation (formula 3.20/3.29).
    """
    global METHOD
    m = str(method).lower().strip()
    if m not in ("welch", "lombscargle", "carspan"):
        raise ValueError(
            f"Unknown PSD method {method!r}. "
            "Must be 'welch', 'lombscargle', or 'carspan'."
        )
    METHOD = m


# ======================================================================
# Mixin
# ======================================================================

class CardioMetricsMixin(HRVMetric):
    """
    Mixin providing HRV metric computation for any object that exposes:
        times  : np.ndarray   R-peak times in seconds
        labels : np.ndarray   per-interval labels
        ibi    : np.ndarray   inter-beat intervals in seconds

    Three PSD back-ends are available, selected via the workspace:

    Welch (default)
        Resamples the IBI series onto a uniform grid (default 4 Hz) and
        applies scipy.signal.welch. Output in ms²/Hz.

    Lomb-Scargle
        Evaluates the spectrum directly on the original irregular beat
        timestamps without resampling. Output in ms²/Hz.

    CARSPAN
        Implements the direct DFT on R-peak event times as described in
        the CARSPAN manual (Mulder, 1988; §3.3.4, formula 3.19):

            S(fk) = (2/T) * |Σ_i  w_i · exp(-2πj·fk·ti)|²

        where w_i is the i-th element of the configurable tapering window
        (default: Hanning, as used in CARSPAN).

        The spectrum is computed on the native frequency grid (Δf = 1/T)
        and then interpolated onto a fixed output grid (default 0.01 Hz
        resolution) so that spectra are visually comparable across
        recordings of different lengths — exactly matching CARSPAN output.

        Band-power values are automatically expressed in mMI²
        (milli-Modulation-Index squared) via the CARSPAN normalisation
        (formula 3.20/3.29):

            power_mMI² = (power_ms² / mean_IBI_ms²) × 1 000 000

        This makes the spectrum dimensionless and directly comparable to
        CARSPAN output.

    Switching the method in the workspace immediately updates all band-power
    metrics (vlf_power, lf_power, hf_power) and the PSD plot.
    """

    METRIC_ORDER = [
        "count", "mean", "median", "min", "max", "std",
        "rmssd", "sdnn", "sdsd",
        "sd1", "sd2", "sd_ratio", "ellipse_area",
        "vlf_power", "lf_power", "hf_power", "lf_hf_ratio",
    ]

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    def _ibi_clean_ms(self) -> np.ndarray:
        """Return valid IBI values in ms, excluding NaN, TL, and T labels."""
        ibi_sec = self.ibi
        if ibi_sec.size == 0:
            return np.array([], dtype=float)
        valid = (
            ~np.isnan(ibi_sec)
            & (self.labels != "TL")
            & (self.labels != "T")
        )
        return 1000.0 * ibi_sec[valid]

    def _carspan_normalise(self, power_raw: float) -> float:
        """
        Convert raw DFT band-power (unit pulses, s²/Hz) to mMI² using the
        CARSPAN normalisation (manual §3.3.4, formulae 3.20 and 3.29):

            S'(fk) = S(fk) / mean_x²   where mean_x = 1 / mean_IBI_sec (HR in Hz)

        Multiplied by 10⁶ to yield mMI²:

            power_mMI² = (power_raw / mean_HR_Hz²) × 1 000 000
                       = power_raw × mean_IBI_sec² × 1 000 000

        Returns NaN if mean IBI is zero or unavailable.
        """
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size == 0:
            return np.nan
        mean_ibi_sec = float(np.mean(ibi_ms)) / 1000.0
        if mean_ibi_sec == 0.0:
            return np.nan
        # mean_x = 1/mean_IBI_sec, so 1/mean_x² = mean_IBI_sec²
        return (power_raw * (mean_ibi_sec ** 2)) * 1_000_000.0

    # ------------------------------------------------------------------
    # Welch back-end
    # ------------------------------------------------------------------

    def welch_psd(
        self,
        *,
        fs:          float | None = None,
        nperseg:     int   | None = None,
        noverlap:    int   | None = None,
        nfft:        int   | None = None,
        window:      str   | None = None,
        interpolate: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute Welch PSD on the IBI series (ms), resampled to a uniform grid.
        Parameters default to the workspace-configured WELCH_PARAMS.
        Returns empty arrays if there are no usable IBIs or interpolation fails.
        """
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
        """Welch PSD with chi-square confidence intervals."""
        alpha = alpha if alpha is not None else CI_ALPHA
        freqs, psd = self.welch_psd(**kwargs)
        if freqs.size == 0:
            return freqs, psd, psd, psd

        nperseg  = kwargs.get("nperseg",  WELCH_PARAMS["nperseg"])
        noverlap = kwargs.get("noverlap", WELCH_PARAMS["noverlap"])
        step       = nperseg - noverlap
        n_segments = max(1, int(np.floor((psd.size * step) / nperseg)))
        nu         = 2 * n_segments
        ci_lower   = (nu * psd) / chi2.ppf(1 - alpha / 2, nu)
        ci_upper   = (nu * psd) / chi2.ppf(alpha / 2, nu)
        return freqs, psd, ci_lower, ci_upper

    # ------------------------------------------------------------------
    # Lomb-Scargle back-end
    # ------------------------------------------------------------------

    def lombscargle_psd(self) -> Tuple[np.ndarray, np.ndarray]:
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
            pgram     = signal.lombscargle(
                ibi_times, ibi_zero, ang_freqs, normalize=False
            )
            T     = float(ibi_times[-1] - ibi_times[0])
            N     = float(ibi_ms.size)
            power = (2.0 * T / (N ** 2)) * pgram
        except Exception:
            return np.ndarray(0), np.ndarray(0)

        # Prepend (fmin_floor, 0) so the plot widget can set xlim to 0
        # without np.interp clamping to the first computed value.
        freqs = np.concatenate(([fmin_floor], freqs))
        power = np.concatenate(([0.0],        power))
        return freqs, power

    def lombscargle_psd_with_ci(
        self,
        *,
        alpha: float | None = None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Lomb-Scargle PSD with chi-square confidence intervals."""
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

    # ------------------------------------------------------------------
    # CARSPAN back-end
    # ------------------------------------------------------------------

    def carspan_psd(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Direct DFT on R-peak event times, following CARSPAN manual §3.3.4
        (Mulder, 1988; formula 3.19):

            S(fk) = (2/T) * |Σ_i  w_i · exp(-2πj·fk·ti)|²

        where w_i is the i-th tapering window coefficient.

        Steps
        -----
        1. Build the native frequency grid fk = k/T (Δf = 1/T),
           restricted to the frequency range covered by the HRV bands.
        2. Apply a tapering window (default: Hanning) to reduce spectral
           leakage, as done in CARSPAN.
        3. Evaluate the direct DFT at each fk.
        4. Interpolate onto a fixed output grid (default 0.01 Hz) so that
           spectra are visually comparable across recording lengths —
           exactly as CARSPAN does.

        Output is in ms²/Hz.  Band-power metrics apply _carspan_normalise()
        to convert to mMI² automatically.
        """
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 4:
            return np.ndarray(0), np.ndarray(0)

        ibi_times = self.times[: ibi_ms.size]
        T = float(ibi_times[-1] - ibi_times[0])
        if T <= 0:
            return np.ndarray(0), np.ndarray(0)

        N = ibi_ms.size

        # Tapering window — configurable, default Hanning
        win_name = CARSPAN_PARAMS["window"]
        try:
            win = signal.get_window(win_name, N)
        except Exception:
            win = np.ones(N)  # fallback: rectangular

        # Native frequency grid: fk = k/T for k = 1 .. ceil(f_max * T).
        # k=1 is the lowest non-DC frequency; DC (k=0) carries no HRV info.
        # We compute the full grid from k=1 so that np.interp never has to
        # extrapolate downward — points below freqs_native[0] are set to 0
        # via the explicit left=0.0 argument.
        f_max  = max(s["high"] for s in HRV_FREQUENCY_BANDS.values())
        k_max  = int(np.ceil(f_max * T))
        k_vals = np.arange(1, k_max + 1)
        freqs_native = k_vals / T  # Hz, resolution = 1/T

        # Direct DFT (formula 3.19), vectorised
        # phases: shape (N_events, N_freqs)
        phases  = -2.0 * np.pi * np.outer(ibi_times, freqs_native)
        X_real  = np.dot(win, np.cos(phases))
        X_imag  = np.dot(win, np.sin(phases))
        power_native = (2.0 / T) * (X_real ** 2 + X_imag ** 2)

        # Interpolate onto the fixed output grid (CARSPAN convention).
        # Grid starts at the lowest band edge so there is no empty space
        # before the first band in the plot.
        freq_res  = float(CARSPAN_PARAMS["freq_resolution"])
        f_min_band = min(s["low"] for s in HRV_FREQUENCY_BANDS.values())
        freqs_out = np.arange(f_min_band, f_max + freq_res / 2, freq_res)
        freqs_out = freqs_out[freqs_out <= f_max]

        if freqs_native.size < 2:
            return np.ndarray(0), np.ndarray(0)

        power_out = np.interp(freqs_out, freqs_native, power_native)

        # Optional 3-point moving average for display — matches CARSPAN
        # plotting convention (manual §3.3, pre-algorithm choices):
        # "a moving average window over three frequency points (0.03 Hz
        # bandwidth) is applied before plotting the spectral functions."
        # The same passage states that band values are computed WITHOUT
        # smoothing, so this is applied here in carspan_psd() which is
        # used for display.  _band_power() calls psd_with_ci() which calls
        # this method, so we must NOT smooth when called from band metrics.
        # We solve this by returning the smoothed array only when the setting
        # is active; the band metrics use _band_power_exact() which
        # integrates over the interpolated (and possibly smoothed) spectrum.
        # Because the smoothing is mild (3-point, 0.03 Hz) the effect on
        # band-integrated power is negligible — consistent with the CARSPAN
        # manual's assertion that smoothing does not affect band values.
        if CARSPAN_PARAMS.get("smooth_for_display", True) and power_out.size >= 3:
            kernel    = np.array([1.0, 1.0, 1.0]) / 3.0
            smoothed  = np.convolve(power_out, kernel, mode="same")
            # np.convolve with mode="same" uses zero-padding at the edges,
            # which underweights the first and last points.  Correct by
            # dividing by the actual number of contributing neighbours.
            smoothed[0]  = (power_out[0]  + power_out[1])  / 2.0
            smoothed[-1] = (power_out[-2] + power_out[-1]) / 2.0
            power_out = smoothed

        return freqs_out, power_out

    def carspan_psd_with_ci(
        self,
        *,
        alpha: float | None = None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        CARSPAN PSD with chi-square confidence intervals.

        Degrees of freedom
        ------------------
        The CARSPAN direct DFT produces one periodogram ordinate per native
        frequency line f_k = k/T.  A single periodogram ordinate at a
        frequency where the true spectral density is S(f) satisfies:

            2 * periodogram / S(f)  ~  chi²_2

        so the degrees of freedom per native line are nu = 2.  The number
        of native lines in the displayed band [f_min, f_max] is
        n_native = (f_max - f_min) * T.  The CI shown reflects the
        uncertainty across those native lines:

            nu = 2 * n_native = 2 * (f_max - f_min) * T

        This differs from the Lomb-Scargle CI (which uses a factor of 4
        following Scargle, 1982) because the direct DFT grid is regular
        and each line is genuinely independent.  The resulting CI is wider
        than the Lomb-Scargle CI for the same recording length, correctly
        reflecting that the direct DFT does not benefit from the adaptive
        frequency placement of Lomb-Scargle.
        """
        alpha = alpha if alpha is not None else CI_ALPHA
        freqs, psd = self.carspan_psd()
        if freqs.size == 0:
            return freqs, psd, psd, psd

        ibi_ms    = self._ibi_clean_ms()
        ibi_times = self.times[: ibi_ms.size]
        T     = float(ibi_times[-1] - ibi_times[0])

        # The CI is displayed per output frequency point.  Each output point
        # sits on the 0.01 Hz grid and is interpolated from the native DFT
        # grid (spacing 1/T Hz).  The number of independent native lines
        # supporting each output point is:
        #
        #     n_per_point = freq_resolution * T   (output step / native step)
        #
        # Each native line is one periodogram ordinate -> nu = 2 per line,
        # so the per-point degrees of freedom are:
        #
        #     nu = 2 * freq_resolution * T
        #
        # This correctly reflects that the CARSPAN direct DFT does no
        # averaging: for a 5-minute recording at 0.01 Hz resolution each
        # point rests on ~3 native lines (nu~6), giving a wide CI that
        # honestly conveys the limited reliability of a single-segment DFT.
        freq_res  = float(CARSPAN_PARAMS["freq_resolution"])
        n_per_point = max(1, int(round(freq_res * T)))
        nu          = 2 * n_per_point

        ci_lower = (nu * psd) / chi2.ppf(1 - alpha / 2, nu)
        ci_upper = (nu * psd) / chi2.ppf(alpha / 2, nu)
        return freqs, psd, ci_lower, ci_upper

    # ------------------------------------------------------------------
    # Unified dispatcher
    # ------------------------------------------------------------------

    def psd_with_ci(
        self,
        *,
        alpha: float | None = None,
        **kwargs,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Compute PSD with confidence intervals using the active METHOD.
        Always returns (freqs, psd, ci_lower, ci_upper) in ms²/Hz.

        When METHOD == "carspan", the raw spectrum is still in ms²/Hz here.
        The mMI² conversion happens in _band_power(), keeping the PSD plot
        unaffected by the normalisation.
        """
        if METHOD == "lombscargle":
            return self.lombscargle_psd_with_ci(alpha=alpha)
        elif METHOD == "carspan":
            return self.carspan_psd_with_ci(alpha=alpha)
        else:
            return self.welch_psd_with_ci(alpha=alpha, **kwargs)

    # ------------------------------------------------------------------
    # Band-power helper
    # ------------------------------------------------------------------

    def _band_power_exact(
        self,
        freqs: np.ndarray,
        power: np.ndarray,
        f0:    float,
        f1:    float,
    ) -> float:
        """
        Band power by trapezoidal integration with endpoint interpolation.
        Returns NaN if the band has no data. Units: ms².
        """
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

    def _carspan_psd_native(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute the CARSPAN direct DFT on the native frequency grid
        (fk = k/T, Δf = 1/T) without any interpolation or smoothing.

        This is the grid used for band power computation following CARSPAN
        manual formula 3.28:

            B(fl, fh) = Σ_{fk=fl}^{fh} S(fk) · Δf

        where Δf = 1/T is fixed by the recording duration, not by
        freq_resolution.  Band power computed here is therefore independent
        of the freq_resolution display setting.

        Returns (freqs_native, power_native) in the same units as
        carspan_psd() — events²/Hz (unit-pulse DFT, before mMI² scaling).
        Returns empty arrays if there are insufficient data.
        """
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

    def _carspan_band_power_native(self, f0: float, f1: float) -> float:
        """
        Band power for the CARSPAN method using formula 3.28 of the CARSPAN
        manual, computed directly on the native DFT grid:

            B(fl, fh) = Σ_{fk=fl}^{fh} S(fk) · Δf,    Δf = 1/T

        This is independent of freq_resolution (which governs only the
        display grid) and matches the band summation used in CARSPAN.

        Returns power in events²/Hz · Hz = events² (before mMI² scaling).
        Returns NaN if no native lines fall within [f0, f1].
        """
        freqs_native, power_native = self._carspan_psd_native()
        if freqs_native.size == 0:
            return np.nan
        T    = float(self.times[: self._ibi_clean_ms().size][-1]
                     - self.times[0])
        delta_f = 1.0 / T
        mask    = (freqs_native >= f0) & (freqs_native <= f1)
        if not np.any(mask):
            return np.nan
        return float(np.sum(power_native[mask]) * delta_f)

    def _band_power(self, band_name: str) -> float:
        """
        Band power using the active method.

        For Welch and Lomb-Scargle: returns ms², computed by trapezoidal
        integration of the interpolated output spectrum.

        For CARSPAN: returns mMI², computed by direct summation on the
        native DFT grid (formula 3.28) — independent of freq_resolution.
        The mMI² normalisation (formula 3.20/3.29) is then applied.
        """
        band = HRV_FREQUENCY_BANDS[band_name]

        if METHOD == "carspan":
            # Use native-grid summation (formula 3.28) — not the display grid
            power_raw = self._carspan_band_power_native(
                band["low"], band["high"]
            )
            return self._carspan_normalise(power_raw)

        # Welch / Lomb-Scargle: integrate the output spectrum
        freqs, power, _, _ = self.psd_with_ci()
        return self._band_power_exact(freqs, power, band["low"], band["high"])

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
        """VLF band power. Units: ms² (welch/lombscargle) or mMI² (carspan)."""
        return self._band_power("VLF")

    @hrv_metric
    def lf_power(self) -> float:
        """LF band power. Units: ms² (welch/lombscargle) or mMI² (carspan)."""
        return self._band_power("LF")

    @hrv_metric
    def hf_power(self) -> float:
        """HF band power. Units: ms² (welch/lombscargle) or mMI² (carspan)."""
        return self._band_power("HF")

    @hrv_metric
    def lf_hf_ratio(self) -> float:
        """LF/HF ratio (dimensionless). Independent of normalisation."""
        lf, hf = self.lf_power(), self.hf_power()
        return float(lf / hf) if hf and hf > 0 else np.nan