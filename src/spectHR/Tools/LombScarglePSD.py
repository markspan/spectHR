"""
LombScarglePSD.py – Lomb-Scargle power spectral density for IBI series.

Computes the PSD of an inter-beat-interval series directly on the
*non-uniformly-sampled* time grid, avoiding the interpolation artefacts
inherent in Welch's method.

Uses ``scipy.signal.lombscargle`` (unnormalised) to compute the
periodogram, then scales it to a proper one-sided PSD in **ms²/Hz**.

Output units
------------
**ms²/Hz** — power of the IBI series expressed in milliseconds.
Conversion to mMI²/Hz is handled by the caller
(CardioFrequencyMetricsMixin).

References
----------
N. R. Lomb, "Least-squares frequency analysis of unequally spaced data",
Astrophys. Space Sci. 39, 447–462, 1976.

J. D. Scargle, "Studies in astronomical time series analysis. II",
Astrophys. J. 263, 835–853, 1982.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from scipy import signal as sp_signal


# ---------------------------------------------------------------------------
# Module-level default parameters (overridden by workspace config)
# ---------------------------------------------------------------------------

LOMBSCARGLE_PARAMS = {
    "nfreqs": 1000,  # Number of frequency evaluation points
    "fmin_floor": 0.0001,  # Lowest frequency (Hz) to avoid DC
}


def load_lombscargle_params(config: dict) -> None:
    """
    Update module-level LOMBSCARGLE_PARAMS from a workspace configuration dict.

    Parameters
    ----------
    config : dict
        Keys matching LOMBSCARGLE_PARAMS will be updated; unknown keys are
        ignored.
    """
    for key in LOMBSCARGLE_PARAMS:
        if key in config:
            LOMBSCARGLE_PARAMS[key] = config[key]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_lombscargle_psd(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    f_max: float = 0.5,
    nfreqs: Optional[int] = None,
    fmin_floor: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute the Lomb-Scargle PSD of an IBI series.

    Parameters
    ----------
    ibi_times_s : np.ndarray, shape (M,)
        Timestamps (seconds) of each valid IBI measurement (the R-peak
        time at the *start* of each interval).
    ibi_values_ms : np.ndarray, shape (M,)
        Corresponding IBI durations in **milliseconds**.
    f_max : float
        Upper frequency limit in Hz.  Defaults to 0.5 Hz (a reasonable
        ceiling for HRV analysis).
    nfreqs : int, optional
        Number of frequency evaluation points.  Defaults to
        ``LOMBSCARGLE_PARAMS["nfreqs"]``.
    fmin_floor : float, optional
        Lowest frequency.  Defaults to ``LOMBSCARGLE_PARAMS["fmin_floor"]``.

    Returns
    -------
    freqs : np.ndarray, shape (K,)
        Frequency axis in Hz.
    power : np.ndarray, shape (K,)
        Power spectral density in **ms²/Hz**.

    Notes
    -----
    ``scipy.signal.lombscargle`` returns the *unnormalised* periodogram
    P_n(ω).  To convert to a one-sided PSD in physical units we apply:

        PSD(f) = 2 · P_n(2πf) / N

    where N is the number of data points.  The factor 2 folds negative
    frequencies into the positive side.  Division by N normalises
    consistently with Parseval's theorem.  We then further scale by the
    total observation time T to obtain density (per Hz):

        S(f) = PSD(f) · T / N  →  ms²/Hz

    This matches the convention that ∫S(f)df ≈ variance of the signal.
    """
    # --- Resolve parameters ------------------------------------------------
    nfreqs = int(nfreqs if nfreqs is not None else LOMBSCARGLE_PARAMS["nfreqs"])
    fmin_floor = float(
        fmin_floor if fmin_floor is not None else LOMBSCARGLE_PARAMS["fmin_floor"]
    )

    # --- Input validation --------------------------------------------------
    N = ibi_times_s.size
    if N < 4:
        raise ValueError(
            f"Need at least 4 valid IBI samples for Lomb-Scargle PSD, got {N}."
        )

    T = float(ibi_times_s[-1] - ibi_times_s[0])
    if T <= 0:
        raise ValueError("Observation span T must be > 0.")

    # --- Build frequency grid ----------------------------------------------
    # Lowest meaningful frequency is ~ 1/T; honour the fmin_floor
    f_min = max(1.0 / T, fmin_floor)
    freqs = np.linspace(f_min, f_max, nfreqs)

    # Angular frequencies required by scipy
    angular_freqs = 2.0 * np.pi * freqs

    # --- Mean-subtract the IBI series (remove DC) --------------------------
    ibi_centered = ibi_values_ms - np.mean(ibi_values_ms)

    # --- Lomb-Scargle periodogram (unnormalised) ---------------------------
    pgram = sp_signal.lombscargle(
        ibi_times_s,
        ibi_centered,
        angular_freqs,
        normalize=False,
    )

    # --- Scale to proper PSD in ms²/Hz ------------------------------------
    # The unnormalised periodogram has units ms².  Divide by N to normalise,
    # multiply by 2 for one-sided, and multiply by T/N so that the integral
    # over frequency approximates the variance.
    #
    # Derivation: Var ≈ (2/N) Σ P_n(ωk) · Δf   with Δf = (f_max-f_min)/K
    #           = (2/N) ∫ P_n(ω) df
    # So S(f) = 2 P_n(ω) / N  has units ms² · 1 (dimensionless/Hz needs
    # additional T/N factor).  A standard normalisation that matches
    # Parseval:  S(f) = 2 · P_n / N     (already ms²/Hz when ∫S df ≈ var).
    power = 2.0 * pgram / N

    return freqs, power


def compute_lombscargle_psd_with_ci(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    alpha: float = 0.05,
    **kwargs,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Lomb-Scargle PSD with exponential confidence intervals.

    Parameters
    ----------
    ibi_times_s, ibi_values_ms : np.ndarray
        Same as :func:`compute_lombscargle_psd`.
    alpha : float
        Significance level for the CI (default 0.05 → 95 % CI).
    **kwargs
        Forwarded to :func:`compute_lombscargle_psd`.

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray

    Notes
    -----
    For a single Lomb-Scargle periodogram (no averaging), each frequency
    bin has roughly 2 degrees of freedom (equivalent to an exponential
    distribution).  The chi-squared CI with dof = 2 gives:

        ci_lower = power × dof / χ²(1 − α/2, dof)
        ci_upper = power × dof / χ²(α/2, dof)
    """
    from scipy.stats import chi2

    freqs, power = compute_lombscargle_psd(ibi_times_s, ibi_values_ms, **kwargs)

    # Lomb-Scargle periodogram: ~2 dof per frequency bin (no averaging)
    dof = 2
    chi2_lo = chi2.ppf(alpha / 2, dof)
    chi2_hi = chi2.ppf(1 - alpha / 2, dof)

    ci_lower = dof * power / chi2_hi
    ci_upper = dof * power / chi2_lo

    return freqs, power, ci_lower, ci_upper
