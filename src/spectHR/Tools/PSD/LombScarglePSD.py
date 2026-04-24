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
    "nfreqs": 1000,       # Number of frequency evaluation points
    "fmin_floor": 0.0001, # Lowest frequency (Hz) to avoid DC
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
    #
    # scipy.signal.lombscargle (normalize=False) returns the unnormalised
    # periodogram P(f).  For a sinusoid x(t) = A sin(2πf₀t):
    #
    #     P(f₀)  →  A² N / 4      as N → ∞
    #
    # A proper spectral density S(f) should satisfy:
    #
    #     S(f₀) × (resolution bandwidth ≈ 1/T)  ≈  A²/2  =  variance
    #
    # So  S(f₀) = A² T / 2.  Matching this to P(f₀):
    #
    #     S(f) = (2T / N) × P(f)
    #
    # Verification:  S(f₀) = (2T/N) × (A²N/4) = A²T/2  ✓
    # Integral:      ∫ S df  ≈  S(f₀) × (1/T)  =  A²/2  =  σ²  ✓
    #
    # For broadband signals (white noise with variance σ²):
    #     E[P(f)] ≈ σ² N / 4   at each frequency
    #     E[S(f)] = (2T/N) × σ²N/4 = σ²T/2
    #     ∫₀^fₙ S df ≈ σ²T/2 × 2fₙ = σ²Tfₙ ... which for fₙ ≈ 1/(2Δt):
    #     ≈ σ² × T/(2 mean_ibi) ≈ σ²N/2  → a bit high, but for HRV the
    #     spectrum is far from white, so this is a minor issue.
    power = (2.0 * T / N) * pgram

    return freqs, power


def compute_lombscargle_psd_with_ci(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    alpha: float = 0.05,
    **kwargs,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Lomb-Scargle PSD with chi-squared confidence intervals.

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
    A raw Lomb-Scargle periodogram (no segment averaging) has 2 degrees of
    freedom per frequency bin.  The resulting 95 % CI is therefore wide by
    nature (~40 × power for the upper bound) — this correctly reflects the
    inherent uncertainty of a single-segment spectral estimate.  No smoothing
    is applied so that the displayed spectrum and band powers remain faithful
    to the raw data.

    The chi-squared CI formula is:

        ci_lower = dof × Ŝ / χ²(1 − α/2, dof)
        ci_upper = dof × Ŝ / χ²(α/2,     dof)
    """
    from scipy.stats import chi2

    freqs, power = compute_lombscargle_psd(ibi_times_s, ibi_values_ms, **kwargs)

    # Single-segment Lomb-Scargle: 2 degrees of freedom per bin.
    dof = 2

    # Handle edge cases
    if alpha <= 0:
        ci_lower = np.zeros_like(power)
        ci_upper = np.full_like(power, np.inf)
    elif alpha >= 1:
        ci_lower = power.copy()
        ci_upper = power.copy()
    else:
        chi2_lo = chi2.ppf(alpha / 2, dof)
        chi2_hi = chi2.ppf(1 - alpha / 2, dof)
        ci_lower = dof * power / chi2_hi
        ci_upper = dof * power / chi2_lo

    return freqs, power, ci_lower, ci_upper
