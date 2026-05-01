"""
LombScarglePSD.py – Lomb-Scargle power spectral density for IBI series.

Computes the PSD of an inter-beat-interval series directly on the
non-uniformly-sampled time grid, avoiding interpolation artefacts.

Output units: **ms²/Hz**.  Conversion to mMI²/Hz is done by the caller
(CardioFrequencyMetricsMixin).

References
----------
N. R. Lomb, "Least-squares frequency analysis of unequally spaced data",
Astrophys. Space Sci. 39, 1976.
J. D. Scargle, "Studies in astronomical time series analysis. II",
Astrophys. J. 263, 1982.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from scipy import signal as sp_signal

from spectHR.Tools.PSD._psd_utils import _chi2_ci, _require_min_samples, update_params


LOMBSCARGLE_PARAMS = {
    "nfreqs": 1000,        # Number of frequency evaluation points
    "fmin_floor": 0.0001,  # Lowest frequency (Hz) to avoid DC
    "units": "mMI²",       # Output units: "mMI²" (modulation index) or "ms²" (raw IBI power)
}


def load_lombscargle_params(config: dict) -> None:
    """Update module-level LOMBSCARGLE_PARAMS from a workspace config dict."""
    update_params(LOMBSCARGLE_PARAMS, config)


def compute_lombscargle_psd(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    f_max: float = 0.5,
    nfreqs: Optional[int] = None,
    fmin_floor: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Lomb-Scargle PSD with chi-squared confidence intervals.

    scipy.signal.lombscargle returns the unnormalised periodogram P(f).
    For a sinusoid x(t) = A sin(2πf₀t), P(f₀) → A²N/4 as N → ∞.  Scaling
    by 2T/N yields a density S(f) with S(f₀) = A²T/2, matching the
    convention ∫S(f)df ≈ variance.

    Returns
    -------
    freqs, power, ci_lower, ci_upper : np.ndarray
        Power and bounds in ms²/Hz.  Each bin has 2 dof (single-segment).
    """
    nfreqs = int(nfreqs if nfreqs is not None else LOMBSCARGLE_PARAMS["nfreqs"])
    fmin_floor = float(
        fmin_floor if fmin_floor is not None else LOMBSCARGLE_PARAMS["fmin_floor"]
    )

    N = ibi_times_s.size
    _require_min_samples(N, 4, "Lomb-Scargle PSD")

    T = float(ibi_times_s[-1] - ibi_times_s[0])
    if T <= 0:
        raise ValueError("Observation span T must be > 0.")

    f_min = max(1.0 / T, fmin_floor)
    freqs = np.linspace(f_min, f_max, nfreqs)

    pgram = sp_signal.lombscargle(
        ibi_times_s,
        ibi_values_ms - np.mean(ibi_values_ms),
        2.0 * np.pi * freqs,
        normalize=False,
    )
    power = (2.0 * T / N) * pgram

    # Effective degrees of freedom following Scargle (1982).
    #
    # The number of statistically independent frequencies in the
    # evaluated range [f_min, f_max] is approximately:
    #
    #     M = floor(2 · (f_max − f_min) · T)
    #
    # Each independent frequency contributes 2 dof (chi-squared).
    # When the evaluation grid has nfreqs points spread over M
    # independent frequencies, adjacent points are correlated and
    # the effective dof per bin scales as 2M / nfreqs.  The result
    # is clamped to a minimum of 2 (one independent complex estimate).
    f_range = float(freqs[-1] - freqs[0])
    M = max(1, int(np.floor(2.0 * f_range * T)))
    dof_per_bin = max(2.0, 2.0 * M / len(freqs))

    ci_lower, ci_upper = _chi2_ci(power, dof=dof_per_bin, alpha=alpha_ci)
    return freqs, power, ci_lower, ci_upper
