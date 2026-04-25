"""
WelchPSD.py – Welch power spectral density for IBI series.

The irregularly-sampled IBI values are cubic-interpolated onto a uniform
grid (default 4 Hz), then handed to ``scipy.signal.welch``.

Output units: **ms²/Hz**.  Conversion to mMI²/Hz is done by the caller
(CardioFrequencyMetricsMixin).

References
----------
P. D. Welch, "The use of fast Fourier transform for the estimation of
power spectra", IEEE Trans. Audio Electroacoust., 1967.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from scipy import signal
from scipy.interpolate import interp1d
from scipy.stats import chi2


WELCH_PARAMS = {
    "fs": 4.0,          # Resampling frequency (Hz)
    "nperseg": 256,     # Samples per segment
    "noverlap": 128,    # Overlap between segments
    "nfft": None,       # FFT length (None → nperseg)
    "window": "hann",   # Window function name
}


def load_welch_params(config: dict) -> None:
    """Update module-level WELCH_PARAMS from a workspace config dict."""
    for key in WELCH_PARAMS:
        if key in config:
            WELCH_PARAMS[key] = config[key]


def _resolve_window(window_spec):
    """Convert ``"X% cosine bell"`` → ``("tukey", alpha)``; pass others through."""
    if isinstance(window_spec, str) and "cosine bell" in window_spec:
        try:
            percent = float(window_spec.split("%")[0].strip())
            return ("tukey", percent / 50.0)
        except (ValueError, IndexError):
            pass
    return window_spec


def compute_welch_psd(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    fs: Optional[float] = None,
    nperseg: Optional[int] = None,
    noverlap: Optional[int] = None,
    nfft: Optional[int] = None,
    window: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Welch PSD of an IBI series with chi-squared confidence intervals.

    Parameters
    ----------
    ibi_times_s, ibi_values_ms : np.ndarray
        Timestamps (s) and IBI durations (ms) of each valid IBI.
    alpha_ci : float
        CI significance level (default 0.05 → 95 % CI).

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
        Power and bounds in ms²/Hz.  Each Welch segment adds ~2 dof.
    """
    fs = float(fs if fs is not None else WELCH_PARAMS["fs"])
    nperseg = int(nperseg if nperseg is not None else WELCH_PARAMS["nperseg"])
    noverlap = int(noverlap if noverlap is not None else WELCH_PARAMS["noverlap"])
    nfft = int(nfft) if nfft is not None else WELCH_PARAMS.get("nfft")
    window = _resolve_window(window if window is not None else WELCH_PARAMS["window"])

    if ibi_times_s.size < 4:
        raise ValueError(
            f"Need at least 4 valid IBI samples for Welch PSD, got {ibi_times_s.size}."
        )

    # Resample onto a uniform grid via cubic interpolation.
    dt = 1.0 / fs
    t_uniform = np.arange(float(ibi_times_s[0]), float(ibi_times_s[-1]), dt)
    ibi_resampled = interp1d(
        ibi_times_s, ibi_values_ms, kind="cubic", fill_value="extrapolate",
    )(t_uniform)

    n_samples = len(ibi_resampled)
    if nperseg > n_samples:
        nperseg = n_samples
    if noverlap >= nperseg:
        noverlap = nperseg // 2

    freqs, power = signal.welch(
        ibi_resampled,
        fs=fs,
        window=window,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=nfft,
        detrend="constant",
        scaling="density",
    )

    # dof ≈ 2 × number of Welch segments.
    step = nperseg - noverlap
    n_segments = max(1, 1 + (n_samples - nperseg) // step)
    ci_lower, ci_upper = _chi2_ci(power, 2 * n_segments, alpha_ci)

    return freqs, power, ci_lower, ci_upper


def _chi2_ci(power, dof, alpha):
    """Chi-squared CI:  S ∈ [ν·Ŝ/χ²_{1-α/2}, ν·Ŝ/χ²_{α/2}]."""
    if alpha <= 0:
        return np.zeros_like(power), np.full_like(power, np.inf)
    if alpha >= 1:
        return power.copy(), power.copy()
    dof_arr = np.asarray(dof, dtype=float)
    lo = chi2.ppf(alpha / 2, dof_arr)
    hi = chi2.ppf(1 - alpha / 2, dof_arr)
    return dof_arr * power / hi, dof_arr * power / lo
