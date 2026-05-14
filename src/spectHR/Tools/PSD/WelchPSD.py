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

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np
from scipy import signal
from scipy.interpolate import interp1d

from spectHR.Tools.PSD._psd_utils import (
    _chi2_ci,
    _require_min_samples,
    _resolve_window,
)


@dataclass(frozen=True)
class WelchOptions:
    """Configuration for ``compute_welch_psd``.

    All values are pure Python defaults; the spectUI layer overrides
    them from the workspace JSON by building a fresh ``WelchOptions``.
    """

    fs: float = 4.0
    """Resampling frequency in Hz used before the Welch averaging."""

    nperseg: int = 256
    """Samples per Welch segment."""

    noverlap: int = 128
    """Overlap (samples) between consecutive segments."""

    nfft: Optional[int] = None
    """FFT length; falls through to ``nperseg`` when None."""

    window: str = "hann"
    """``scipy.signal.get_window`` name."""

    units: str = "mMI²"
    """Output unit chosen by the caller's display layer: ``"mMI²"`` (normalised) or ``"ms²"`` (raw)."""


_DEFAULT_WELCH_OPTIONS = WelchOptions()


def compute_welch_psd(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    options: Optional[WelchOptions] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Welch PSD of an IBI series with chi-squared confidence intervals.

    Parameters
    ----------
    ibi_times_s, ibi_values_ms : np.ndarray
        Timestamps (s) and IBI durations (ms) of each valid IBI.
    alpha_ci : float
        CI significance level (default 0.05 → 95 % CI).
    options : WelchOptions, optional
        Welch tuning. Defaults to ``WelchOptions()`` when not provided.

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
        Power and bounds in ms²/Hz.  Each Welch segment adds ~2 dof.
    """
    opts = options if options is not None else _DEFAULT_WELCH_OPTIONS

    fs = float(opts.fs)
    nperseg = int(opts.nperseg)
    noverlap = int(opts.noverlap)
    nfft = int(opts.nfft) if opts.nfft is not None else None
    window = _resolve_window(opts.window)

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

    w_arr = signal.get_window(window, nperseg, fftbins=False).astype(float)
    w_sq = float(np.dot(w_arr, w_arr))
    if step < nperseg and n_segments > 1 and w_sq > 0.0:
        rho = float(np.dot(w_arr[: nperseg - step], w_arr[step:])) / w_sq
        dof = 2.0 * n_segments / (1.0 + 2.0 * (1.0 - 1.0 / n_segments) * rho ** 2)
    else:
        rho = 0.0
        dof = float(2 * n_segments)

    ci_lower, ci_upper = _chi2_ci(power, dof, alpha_ci)
    return freqs, power, ci_lower, ci_upper
