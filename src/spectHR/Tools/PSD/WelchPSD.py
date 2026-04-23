"""
WelchPSD.py – Welch power spectral density estimation for IBI series.

Computes PSD of an inter-beat-interval (IBI) time series using Welch's
averaged periodogram method (scipy.signal.welch).  The IBI series is first
resampled to a uniform grid (default 4 Hz) because Welch's method requires
equidistant samples.

Output units
------------
The native output is **ms²/Hz** (power of the IBI series expressed in
milliseconds).  Conversion to mMI²/Hz is handled by the caller
(CardioFrequencyMetricsMixin).

References
----------
P. D. Welch, "The use of fast Fourier transform for the estimation of
power spectra", IEEE Trans. Audio Electroacoust., 1967.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from scipy import signal
from scipy.interpolate import interp1d


# ---------------------------------------------------------------------------
# Module-level default parameters (overridden by workspace config)
# ---------------------------------------------------------------------------

WELCH_PARAMS = {
    "fs": 4.0,  # Resampling frequency (Hz)
    "nperseg": 256,  # Samples per segment
    "noverlap": 128,  # Overlap between segments
    "nfft": None,  # FFT length (None → nperseg)
    "window": "hann",  # Window function name
}


def load_welch_params(config: dict) -> None:
    """
    Update module-level WELCH_PARAMS from a workspace configuration dict.

    Parameters
    ----------
    config : dict
        Keys matching WELCH_PARAMS will be updated; unknown keys are ignored.
    """
    for key in WELCH_PARAMS:
        if key in config:
            WELCH_PARAMS[key] = config[key]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_welch_psd(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    fs: Optional[float] = None,
    nperseg: Optional[int] = None,
    noverlap: Optional[int] = None,
    nfft: Optional[int] = None,
    window: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute the Welch PSD of an IBI series.

    The irregularly-sampled IBI values are first interpolated onto a uniform
    time grid at *fs* Hz, then handed to ``scipy.signal.welch``.

    Parameters
    ----------
    ibi_times_s : np.ndarray, shape (M,)
        Timestamps (seconds) of each valid IBI.  Typically the R-peak time
        at the *start* of each interval.
    ibi_values_ms : np.ndarray, shape (M,)
        Corresponding IBI durations in **milliseconds**.
    fs : float, optional
        Resampling frequency in Hz.  Defaults to ``WELCH_PARAMS["fs"]``.
    nperseg : int, optional
        FFT segment length.  Defaults to ``WELCH_PARAMS["nperseg"]``.
    noverlap : int, optional
        Segment overlap.  Defaults to ``WELCH_PARAMS["noverlap"]``.
    nfft : int, optional
        FFT length.  Defaults to ``WELCH_PARAMS["nfft"]``.
    window : str, optional
        Window name (any scipy window).  Defaults to ``WELCH_PARAMS["window"]``.

    Returns
    -------
    freqs : np.ndarray, shape (K,)
        Frequency axis in Hz.
    power : np.ndarray, shape (K,)
        Power spectral density in **ms²/Hz**.
    """
    # --- Resolve parameters from module defaults where not given -----------
    fs = float(fs if fs is not None else WELCH_PARAMS["fs"])
    nperseg = int(nperseg if nperseg is not None else WELCH_PARAMS["nperseg"])
    noverlap = int(noverlap if noverlap is not None else WELCH_PARAMS["noverlap"])
    nfft = int(nfft) if nfft is not None else WELCH_PARAMS.get("nfft")
    window = window if window is not None else WELCH_PARAMS["window"]

    # --- Input validation --------------------------------------------------
    if ibi_times_s.size < 4:
        raise ValueError(
            f"Need at least 4 valid IBI samples for Welch PSD, got {ibi_times_s.size}."
        )

    # --- Resample IBI to a uniform grid ------------------------------------
    # Build a uniform time axis spanning the same interval
    t_start = float(ibi_times_s[0])
    t_end = float(ibi_times_s[-1])
    dt = 1.0 / fs
    t_uniform = np.arange(t_start, t_end, dt)

    # Cubic interpolation of IBI values onto the uniform grid
    interpolator = interp1d(
        ibi_times_s,
        ibi_values_ms,
        kind="cubic",
        fill_value="extrapolate",
    )
    ibi_resampled = interpolator(t_uniform)

    # --- Clamp nperseg to signal length ------------------------------------
    n_samples = len(ibi_resampled)
    if nperseg > n_samples:
        nperseg = n_samples
    if noverlap >= nperseg:
        noverlap = nperseg // 2

    # --- Welch PSD ---------------------------------------------------------
    freqs, power = signal.welch(
        ibi_resampled,
        fs=fs,
        window=window,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=nfft,
        detrend="constant",  # Remove mean before FFT
        scaling="density",  # V²/Hz  →  ms²/Hz
    )

    return freqs, power


def compute_welch_psd_with_ci(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    alpha: float = 0.05,
    **kwargs,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Welch PSD with chi-squared confidence intervals.

    Parameters
    ----------
    ibi_times_s, ibi_values_ms : np.ndarray
        Same as :func:`compute_welch_psd`.
    alpha : float
        Significance level for the CI (default 0.05 → 95 % CI).
    **kwargs
        Forwarded to :func:`compute_welch_psd`.

    Returns
    -------
    freqs : np.ndarray
    power : np.ndarray
    ci_lower : np.ndarray
    ci_upper : np.ndarray
        Lower and upper confidence bounds in ms²/Hz.

    Notes
    -----
    Degrees of freedom are estimated as
        dof ≈ 2 × (number of segments)
    Each segment contributes ~2 dof for a real-valued signal with a Hann
    window (the exact factor depends on overlap and window shape, but 2
    is the standard Welch approximation).
    """
    from scipy.stats import chi2

    # --- Resolve segment parameters for dof calculation --------------------
    fs = float(kwargs.get("fs") or WELCH_PARAMS["fs"])
    nperseg = int(kwargs.get("nperseg") or WELCH_PARAMS["nperseg"])
    noverlap = int(kwargs.get("noverlap") or WELCH_PARAMS["noverlap"])

    # Resample length (mirroring the main function)
    t_start = float(ibi_times_s[0])
    t_end = float(ibi_times_s[-1])
    n_samples = int((t_end - t_start) * fs)

    if nperseg > n_samples:
        nperseg = n_samples
    if noverlap >= nperseg:
        noverlap = nperseg // 2

    step = nperseg - noverlap
    n_segments = max(1, 1 + (n_samples - nperseg) // step)
    dof = 2 * n_segments  # Approximate degrees of freedom

    # --- Compute PSD -------------------------------------------------------
    freqs, power = compute_welch_psd(ibi_times_s, ibi_values_ms, **kwargs)

    # --- Chi-squared confidence interval -----------------------------------
    # For a chi² variable with ν dof:
    #   P[ χ²_{α/2,ν}  ≤  ν·Ŝ/S  ≤  χ²_{1-α/2,ν} ] = 1 − α
    #
    # Rearranging:  S ∈ [ ν·Ŝ / χ²_{1-α/2},  ν·Ŝ / χ²_{α/2} ]
    chi2_lo = chi2.ppf(alpha / 2, dof)
    chi2_hi = chi2.ppf(1 - alpha / 2, dof)

    ci_lower = dof * power / chi2_hi
    ci_upper = dof * power / chi2_lo

    return freqs, power, ci_lower, ci_upper
