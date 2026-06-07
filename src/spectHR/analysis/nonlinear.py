# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/nonlinear.py
"""
Non-linear HRV metrics.

Currently exposes the short-term **detrended fluctuation analysis** scaling
exponent ``DFA-α1`` (Peng et al., 1995), registered as a single-valued
``@epoch_metric`` so it contributes one column (``dfa_a1``) to the
parameters table exactly like the time-domain metrics.

DFA quantifies the fractal scaling of the IBI series. The short-term
exponent ``α1`` (computed over box sizes of 4-16 beats) is the variant most
widely reported in psychophysiology: values near 1.0 indicate healthy,
"1/f"-like long-range correlation; values toward 0.5 indicate
uncorrelated (white-noise-like) variability and toward 1.5 a
Brownian/random-walk regime.

Reference
---------
Peng, C.-K., Havlin, S., Stanley, H. E., & Goldberger, A. L. (1995).
Quantification of scaling exponents and crossover phenomena in
nonstationary heartbeat time series. *Chaos*, 5(1), 82-87.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.registry import epoch_metric
from spectHR.analysis.ibi_helpers import ibi_clean_ms


__all__ = ["dfa_fluctuation", "dfa_alpha1", "dfa_a1"]


def dfa_fluctuation(x: np.ndarray, scales: np.ndarray) -> np.ndarray:
    """Detrended fluctuation ``F(n)`` of *x* for each box size in *scales*.

    The series is integrated (cumulative sum of mean-removed values), split
    into non-overlapping windows of length ``n``, locally detrended with a
    linear fit, and the root-mean-square residual taken across all windows.

    Returns ``NaN`` for any scale that does not fit at least two windows in
    the series.
    """
    x = np.asarray(x, dtype=float)
    n_pts = x.size
    y = np.cumsum(x - np.mean(x))

    out = np.full(len(scales), np.nan)
    for k, n in enumerate(scales):
        n = int(n)
        if n < 4 or n > n_pts // 2:
            continue
        n_seg = n_pts // n
        segs = y[: n_seg * n].reshape(n_seg, n)
        t = np.arange(n)
        # Linear local detrend per segment.
        rms = np.empty(n_seg)
        for s in range(n_seg):
            coef = np.polyfit(t, segs[s], 1)
            fit = np.polyval(coef, t)
            rms[s] = np.mean((segs[s] - fit) ** 2)
        out[k] = np.sqrt(np.mean(rms))
    return out


def dfa_alpha1(
    ibi_ms: np.ndarray,
    *,
    scale_min: int = 4,
    scale_max: int = 16,
) -> float:
    """Short-term DFA scaling exponent ``α1`` of an IBI series.

    Parameters
    ----------
    ibi_ms : np.ndarray
        Clean inter-beat intervals in ms (artefacts already removed).
    scale_min, scale_max : int
        Inclusive box-size range in beats (default 4-16, the standard
        short-term window).

    Returns
    -------
    float
        The slope of ``log F(n)`` vs ``log n`` over the configured scales,
        or ``NaN`` when the series is too short (fewer than ``2·scale_max``
        beats) or the fit is degenerate.
    """
    x = np.asarray(ibi_ms, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 2 * int(scale_max):
        return float("nan")

    scales = np.arange(int(scale_min), int(scale_max) + 1)
    f = dfa_fluctuation(x, scales)
    ok = np.isfinite(f) & (f > 0)
    if int(np.sum(ok)) < 3:
        return float("nan")
    coef = np.polyfit(np.log(scales[ok]), np.log(f[ok]), 1)
    return float(coef[0])


@epoch_metric
def dfa_a1(series) -> float:
    """DFA short-term scaling exponent α1 (Peng et al. 1995, box sizes 4-16 beats)."""
    return dfa_alpha1(ibi_clean_ms(series))
