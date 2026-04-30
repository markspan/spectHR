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

from spectHR.Tools.PSD._psd_utils import _chi2_ci, _require_min_samples, _resolve_window


WELCH_PARAMS = {
    "fs": 4.0,          # Resampling frequency (Hz)
    "nperseg": 256,     # Samples per segment
    "noverlap": 128,    # Overlap between segments
    "nfft": None,       # FFT length (None → nperseg)
    "window": "hann",   # Window function name
    "units": "mMI²",    # Output units: "mMI²" (modulation index) or "ms²" (raw IBI power)
}


def load_welch_params(config: dict) -> None:
    """Update module-level WELCH_PARAMS from a workspace config dict."""
    for key in WELCH_PARAMS:
        if key in config:
            WELCH_PARAMS[key] = config[key]


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

    _require_min_samples(ibi_times_s.size, 4, "Welch PSD")

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

    # Effective degrees of freedom with window-overlap correction.
    #
    # For K independent segments: ν = 2K.  Overlapping segments are
    # partially correlated, which reduces ν.  The correction uses the
    # normalised window autocorrelation ρ at the segment step offset
    # (Percival & Walden, 1993, §6.7):
    #
    #     ν = 2K / (1 + 2(1 − 1/K) ρ²)
    #
    # ρ is computed numerically from the actual window samples so that
    # any window shape (Hann, Tukey, Hamming, …) is handled correctly.
    step = nperseg - noverlap
    n_segments = max(1, 1 + (n_samples - nperseg) // step)

    # Retrieve actual window samples for the correlation calculation.
    w_arr = signal.get_window(window, nperseg, fftbins=False).astype(float)
    w_sq = float(np.dot(w_arr, w_arr))
    if step < nperseg and n_segments > 1 and w_sq > 0.0:
        # Normalised autocorrelation of w at lag = step samples.
        rho = float(np.dot(w_arr[: nperseg - step], w_arr[step:])) / w_sq
        dof = 2.0 * n_segments / (1.0 + 2.0 * (1.0 - 1.0 / n_segments) * rho ** 2)
    else:
        # Non-overlapping segments or single segment: no correction needed.
        rho = 0.0
        dof = float(2 * n_segments)

    ci_lower, ci_upper = _chi2_ci(power, dof, alpha_ci)

    return freqs, power, ci_lower, ci_upper


