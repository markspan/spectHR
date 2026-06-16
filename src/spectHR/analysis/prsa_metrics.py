# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/prsa_metrics.py
"""
Phase-Rectified Signal Averaging (PRSA) metrics.

``dc`` — Deceleration Capacity
    Parasympathetic index derived by anchoring on beats where the IBI
    *increased* (heart slowed), averaging the surrounding window of T beats,
    and applying the four-point formula.  A strong independent predictor of
    post-MI mortality (Bauer et al. 2006, 2008).

``ac`` — Acceleration Capacity
    Mirror image: anchors on beats where the IBI *decreased* (heart
    accelerated).  Reflects sympathetic / combined autonomic drive.

Both are reported in milliseconds; larger absolute values indicate greater
autonomic modulation.  DC is positive by convention, AC is negative.

Reference
---------
Bauer A, Kantelhardt JW, Barthel P, et al. (2006). Deceleration capacity of
heart rate as a predictor of mortality after myocardial infarction:
cohort study. *The Lancet*, 367(9523), 1674–1681.
https://doi.org/10.1016/S0140-6736(06)68735-7
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.ibi_helpers import ibi_clean_ms
from spectHR.analysis.registry import epoch_metric

# Default half-window: 30 beats each side of the anchor (Bauer 2006).
# Overridden at runtime by CardioParameters.PrsaAnalysis.prsa_window in the workspace.
_T_DEFAULT = 30


def _prsa(ibi: np.ndarray, deceleration: bool, T: int = _T_DEFAULT) -> float:
    """Core PRSA computation.

    Parameters
    ----------
    ibi:
        Clean IBI series in milliseconds, length N.
    deceleration:
        ``True`` → DC anchors (IBI[i] > IBI[i-1]);
        ``False`` → AC anchors (IBI[i] < IBI[i-1]).
    T:
        Half-window size in beats (default 30).

    Returns the four-point PRSA capacity in milliseconds, or ``nan`` when
    fewer than 2·T+2 beats are available or no qualifying anchors exist.
    """
    N = len(ibi)
    if N < 2 * T + 2:
        return np.nan

    # Anchor indices: i in [T, N-T) satisfying the monotonicity condition.
    diffs = np.diff(ibi)                          # length N-1
    if deceleration:
        anchors = np.where(diffs[T - 1: N - T - 1] > 0)[0] + T
    else:
        anchors = np.where(diffs[T - 1: N - T - 1] < 0)[0] + T

    if anchors.size == 0:
        return np.nan

    # Stack windows and average.
    windows = np.stack([ibi[a - T: a + T] for a in anchors])  # (n, 2T)
    avg = windows.mean(axis=0)

    # Four-point formula centred on the anchor (index T within avg).
    capacity = (avg[T] + avg[T + 1] - avg[T - 1] - avg[T - 2]) / 4.0
    return float(capacity)


@epoch_metric
def dc(series) -> float:
    """Deceleration Capacity (DC) in ms — PRSA parasympathetic index.

    Anchors on beats where IBI increased (heart decelerated), averages a
    window of ±T beats (T = CardioParameters → PrsaAnalysis → prsa_window,
    default 30), and applies the four-point formula (Bauer et al. 2006).
    Larger positive values indicate stronger parasympathetic modulation.
    Returns NaN when fewer than 2·T+2 clean beats are available or no
    deceleration anchors exist.
    """
    ibi = ibi_clean_ms(series)
    T = int(getattr(series, "prsa_window", _T_DEFAULT))
    return _prsa(ibi, deceleration=True, T=T)


@epoch_metric
def ac(series) -> float:
    """Acceleration Capacity (AC) in ms — PRSA sympatho-vagal index.

    Anchors on beats where IBI decreased (heart accelerated), averages a
    window of ±T beats (T = CardioParameters → PrsaAnalysis → prsa_window,
    default 30), and applies the four-point formula (Bauer et al. 2006).
    AC is negative by convention; more negative values indicate stronger
    acceleration drive.  Returns NaN when fewer than 2·T+2 clean beats are
    available or no acceleration anchors exist.
    """
    ibi = ibi_clean_ms(series)
    T = int(getattr(series, "prsa_window", _T_DEFAULT))
    return _prsa(ibi, deceleration=False, T=T)
