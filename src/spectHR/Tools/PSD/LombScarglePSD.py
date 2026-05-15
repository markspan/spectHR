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

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import signal as sp_signal

from spectHR.Tools.PSD._psd_utils import (
    PSDResult,
    _chi2_ci,
    _require_min_samples,
)


@dataclass(frozen=True)
class LombscargleOptions:
    """Configuration for ``compute_lombscargle_psd``."""

    nfreqs: int = 1000
    """Number of frequency evaluation points across ``[f_min, f_max]``."""

    fmin_floor: float = 1e-4
    """Lower frequency floor in Hz, to keep the DC bin out of the grid."""

    units: str = "mMI²"
    """Output unit hint for the caller's display layer: ``"mMI²"`` or ``"ms²"``."""


_DEFAULT_LS_OPTIONS = LombscargleOptions()


def compute_lombscargle_psd(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    *,
    alpha_ci: float = 0.05,
    f_max: float = 0.5,
    options: Optional[LombscargleOptions] = None,
) -> PSDResult:
    """
    Lomb-Scargle PSD with chi-squared confidence intervals.

    scipy.signal.lombscargle returns the unnormalised periodogram P(f).
    For a sinusoid x(t) = A sin(2πf₀t), P(f₀) → A²N/4 as N → ∞.  Scaling
    by 2T/N yields a density S(f) with S(f₀) = A²T/2, matching the
    convention ∫S(f)df ≈ variance.

    Parameters
    ----------
    f_max : float
        Upper frequency bound of the evaluation grid (Hz).
    options : LombscargleOptions, optional
        Tuning. Defaults to ``LombscargleOptions()`` when not provided.

    Returns
    -------
    PSDResult
        ``power`` in **ms²/Hz** (raw unit). Each bin has 2 dof
        (single-segment). The caller applies any further unit
        conversion.
    """
    opts = options if options is not None else _DEFAULT_LS_OPTIONS

    nfreqs = int(opts.nfreqs)
    fmin_floor = float(opts.fmin_floor)

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
    return PSDResult(
        freqs=freqs,
        power=power,
        unit="ms²/Hz",
        method="lombscargle",
        ci_lower=ci_lower,
        ci_upper=ci_upper,
    )
