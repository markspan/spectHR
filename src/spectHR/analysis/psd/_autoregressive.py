# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/psd/_autoregressive.py
"""
Autoregressive (parametric) power spectral density for IBI series.

An AR(p) model is fitted to the uniformly-resampled IBI tachogram with
**Burg's method**, then the PSD is evaluated analytically from the model
coefficients.  Output is ms²/Hz (unit conversion to mMI²/Hz is done by
:class:`~spectHR.analysis.psd._engine.PSDEngine`, exactly as for Welch and
Lomb-Scargle).

Why offer it
------------
The autoregressive estimator is one of the two methods the Task Force (1996)
standard recommends alongside the periodogram family, and it is the third PSD
method carried by both pyHRV and Kubios.  Compared with Welch it produces a
smooth spectrum with sharper band peaks and no window-length / segment
trade-off, which is an advantage on the short epochs (1-5 min) typical of
mental-effort research.  It is a tachogram method (needs a uniformly sampled
series), so, like Welch, it resamples the unevenly-spaced IBIs first.

It is an **opt-in** method: the CARSPAN paths remain the default and are never
touched.

References
----------
- Task Force of the ESC and NASPE (1996). Heart rate variability: standards of
  measurement.  *Circulation*, 93, 1043-1065.
- Burg, J. P. (1975). *Maximum entropy spectral analysis*. PhD thesis, Stanford.
- Boardman, A., et al. (2002). A study on the optimum order of autoregressive
  models for heart rate variability. *Physiological Measurement*, 23, 325-336.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.interpolate import interp1d

from spectHR.analysis.psd._utils import PSDResult, _require_min_samples


@dataclass(frozen=True)
class AutoregressiveOptions:
    """Configuration for ``compute_autoregressive_psd``."""

    fs: float = 4.0
    """Resampling frequency in Hz used before the AR fit (as for Welch)."""

    order: int = 16
    """AR model order ``p``.  16 is the pyHRV default and sits in the
    10-20 range Boardman et al. (2002) recommend for short-term HRV; too low
    over-smooths, too high introduces spurious peaks."""

    nfreqs: int = 512
    """Number of frequency evaluation points across ``[0, f_max]``."""


_DEFAULT_AR_OPTIONS = AutoregressiveOptions()


def _arburg(x: np.ndarray, order: int) -> "tuple[np.ndarray, float]":
    """Fit an AR(*order*) model to *x* with Burg's method.

    Returns
    -------
    a : np.ndarray
        AR coefficients, length ``order + 1``, with the convention
        ``A(z) = 1 + a[1] z⁻¹ + … + a[order] z⁻ᵖ`` (so ``a[0] == 1``).
    sigma2 : float
        Estimated variance of the white-noise driving term (final Burg
        prediction-error power).

    Burg minimises the sum of forward and backward prediction errors and is
    the standard AR estimator for short HRV series: it never produces an
    unstable model and gives better frequency resolution than the
    autocorrelation (Yule-Walker) method.
    """
    x = np.asarray(x, dtype=float)
    n = x.size
    f = x.copy()
    b = x.copy()
    a = np.zeros(order + 1, dtype=float)
    a[0] = 1.0
    sigma2 = float(np.dot(x, x) / n)

    for m in range(order):
        fm = f[m + 1:]
        bm = b[m:n - 1]
        denom = float(np.dot(fm, fm) + np.dot(bm, bm))
        if denom <= 0.0:
            break
        k = -2.0 * float(np.dot(fm, bm)) / denom

        # Levinson update of the AR coefficients (uses the pre-update copy).
        a_prev = a[:m + 2].copy()
        a[1:m + 2] = a_prev[1:m + 2] + k * a_prev[m::-1]

        # Update the forward / backward prediction errors.
        f_old = f.copy()
        f[m + 1:] = fm + k * bm
        b[m + 1:] = bm + k * f_old[m + 1:]

        sigma2 *= (1.0 - k * k)

    return a, sigma2


def compute_autoregressive_psd(
    ibi_times_s: np.ndarray,
    ibi_values_ms: np.ndarray,
    *,
    alpha_ci: float = 0.05,   # noqa: ARG001, kept for a uniform back-end signature
    f_max: float = 0.5,
    options: Optional[AutoregressiveOptions] = None,
) -> PSDResult:
    """Autoregressive (Burg) PSD of an IBI series.

    Returns ``power`` in ms²/Hz on a uniform ``[0, f_max]`` grid.  Unit
    conversion to mMI²/Hz is done by :class:`PSDEngine`.

    No confidence interval is returned (``ci_lower`` / ``ci_upper`` are
    ``None``): a parametric AR spectrum has no simple chi-squared interval like
    the periodogram methods, and a bootstrap interval is out of scope here.
    """
    opts = options if options is not None else _DEFAULT_AR_OPTIONS
    fs = float(opts.fs)
    order = int(opts.order)
    nfreqs = int(opts.nfreqs)

    ibi_times_s = np.asarray(ibi_times_s, dtype=float)
    ibi_values_ms = np.asarray(ibi_values_ms, dtype=float)
    _require_min_samples(ibi_times_s.size, 4, "Autoregressive PSD")

    # Resample the unevenly-spaced IBIs onto a uniform grid (as Welch does).
    dt = 1.0 / fs
    t_uniform = np.arange(float(ibi_times_s[0]), float(ibi_times_s[-1]), dt)
    if t_uniform.size <= 4:
        raise ValueError("IBI span too short for an autoregressive PSD.")
    x = interp1d(
        ibi_times_s, ibi_values_ms, kind="cubic", fill_value="extrapolate",
    )(t_uniform)
    x = x - float(np.mean(x))

    # The model order cannot exceed the sample count; clamp defensively.
    order = max(1, min(order, x.size - 1))

    a, sigma2 = _arburg(x, order)

    # Evaluate the AR transfer function on the frequency grid:
    #   A(f) = 1 + Σ_{k=1}^p a_k · exp(-j 2π f k / fs)
    # and the one-sided PSD  S(f) = 2 σ² / fs / |A(f)|²  (ms²/Hz), matching
    # the one-sided "density" scaling scipy.welch uses.
    freqs = np.linspace(0.0, float(f_max), nfreqs)
    k = np.arange(1, order + 1)
    phase = np.exp(-2j * np.pi * np.outer(freqs, k) / fs)   # (nfreqs, order)
    a_resp = 1.0 + phase @ a[1:order + 1]
    power = (2.0 * sigma2 / fs) / (np.abs(a_resp) ** 2)

    return PSDResult(
        freqs=freqs,
        power=power,
        unit="ms²/Hz",
        method="autoregressive",
        ci_lower=None,
        ci_upper=None,
    )
