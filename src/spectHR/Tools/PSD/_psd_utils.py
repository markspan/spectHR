"""
_psd_utils.py – Shared helpers for all PSD back-ends.

Centralises logic that was previously copy-pasted across
WelchPSD.py, LombScarglePSD.py, and CarspanPSD.py.

Also defines :class:`PSDResult`, the small dataclass every compute
function returns. Keeping the result type next to the helpers (rather
than next to the consumer in CardioMetricsMixin) lets the compute
modules stay self-contained — they own the raw output shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.stats import chi2


# ---------------------------------------------------------------------------
# PSDResult — common output type for every PSD back-end
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PSDResult:
    """Immutable container for a PSD computation result.

    Returned by every ``compute_*_psd`` function and by every
    ``CardioMetricsMixin.psd*`` method. Compute functions fill it with
    the **raw** unit (e.g. ``"ms²/Hz"`` for Welch, ``"Hz"`` for CARSPAN)
    and the algorithm name; the mixin then applies any unit conversion
    and band-range masking before handing the result to the caller.
    """

    freqs: np.ndarray
    power: np.ndarray
    unit: str = ""
    method: str = ""
    ci_lower: Optional[np.ndarray] = None
    ci_upper: Optional[np.ndarray] = None


# ---------------------------------------------------------------------------
# Chi-squared confidence interval (identical formula across all PSD methods)
# ---------------------------------------------------------------------------

def _chi2_ci(
    power: np.ndarray,
    dof: float | np.ndarray,
    alpha: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Chi-squared confidence interval for a PSD estimate.

    For a spectral estimate S_hat with nu degrees of freedom:

        S in [ nu * S_hat / chi2_{1-alpha/2,nu},
               nu * S_hat / chi2_{alpha/2,nu} ]

    Parameters
    ----------
    power : np.ndarray
        PSD values (any unit).
    dof : float or np.ndarray
        Degrees of freedom.  May be scalar (same for all bins) or
        per-bin array (e.g. CARSPAN after bin-averaging).
    alpha : float
        Significance level (e.g. 0.05 -> 95 % CI).

    Returns
    -------
    ci_lower, ci_upper : np.ndarray
        Lower and upper CI bounds, same shape and unit as *power*.
        Returns (zeros, inf) when alpha <= 0 and (power, power) when alpha >= 1.
    """
    if alpha <= 0:
        return np.zeros_like(power), np.full_like(power, np.inf)
    if alpha >= 1:
        return power.copy(), power.copy()
    dof_arr = np.asarray(dof, dtype=float)
    lo = chi2.ppf(alpha / 2, dof_arr)
    hi = chi2.ppf(1.0 - alpha / 2, dof_arr)
    return dof_arr * power / hi, dof_arr * power / lo


# ---------------------------------------------------------------------------
# Window-spec resolver (shared by Welch and CARSPAN)
# ---------------------------------------------------------------------------

def _resolve_window(window_spec):
    """
    Translate a human-readable cosine-bell spec into a scipy window tuple.

    ``"X% cosine bell"``  ->  ``("tukey", X / 50)``

    Any other value is returned unchanged, so plain scipy names (``"hann"``,
    ``"hamming"``, ...) and already-resolved tuples pass through unmodified.

    Parameters
    ----------
    window_spec : str or tuple
        Window specification from the workspace or a function argument.

    Returns
    -------
    str or tuple
        Resolved window specification suitable for ``scipy.signal.get_window``.
    """
    if isinstance(window_spec, str) and "cosine bell" in window_spec:
        try:
            percent = float(window_spec.split("%")[0].strip())
            return ("tukey", percent / 50.0)
        except (ValueError, IndexError):
            pass
    return window_spec


# ---------------------------------------------------------------------------
# Minimum-sample guard (standardises error messages across PSD methods)
# ---------------------------------------------------------------------------

def _require_min_samples(n, min_n, context):
    """
    Raise a descriptive ``ValueError`` when a sample-count requirement is
    not met.

    Parameters
    ----------
    n : int
        Actual number of samples available.
    min_n : int
        Minimum number required.
    context : str
        Short description of the computation (used in the error message),
        e.g. ``"Welch PSD"`` or ``"CARSPAN PSD"``.

    Raises
    ------
    ValueError
        When ``n < min_n``.
    """
    if n < min_n:
        raise ValueError(
            f"Need at least {min_n} valid samples for {context}, got {n}."
        )
