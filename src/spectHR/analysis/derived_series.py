# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/derived_series.py
"""
Plot-ready series derived from an R-peak :class:`Events` channel.

These are the small transforms the *viewer* widgets need, instantaneous
heart rate over time, and the Poincaré point cloud, kept here in
``spectHR`` so the UI computes nothing.  Both reuse the artefact-aware
extraction in :mod:`spectHR.analysis.ibi_helpers` (a dropped or artefact
beat breaks the chain rather than bridging it), so they share one
definition of "valid interval" with every HRV metric.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from spectHR.analysis.ibi_helpers import ibi_clean_pairs, ibi_ms_full_with_mask

__all__ = ["heart_rate_series", "poincare_pairs", "poincare_points",
           "PoincareDescriptors", "poincare_descriptors"]


def heart_rate_series(events) -> "tuple[np.ndarray, np.ndarray]":
    """Instantaneous heart rate over time, in beats per minute.

    Parameters
    ----------
    events
        An :class:`~spectHR.session.Events`-like object (``times`` /
        ``labels`` / ``ibi``).

    Returns
    -------
    (times_s, hr_bpm)
        Aligned arrays of R-peak times (s) and instantaneous heart rate
        (bpm), with artefact / NaN intervals removed so dropped beats leave
        gaps instead of spurious spikes.  Empty arrays when no valid beats.
    """
    times_s, ibi_ms = ibi_clean_pairs(events)
    if ibi_ms.size == 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    return times_s, 60000.0 / ibi_ms


def poincare_pairs(events) -> "tuple[np.ndarray, np.ndarray]":
    """Consecutive IBI pairs ``(ibi_n, ibi_n+1)`` in ms, for a Poincaré plot.

    Only *temporally adjacent* valid intervals are paired, an artefact or
    dropped beat breaks the pair rather than bridging the gap, matching the
    convention used by the SD1/SD2/RMSSD metrics.

    Parameters
    ----------
    events
        An :class:`~spectHR.session.Events`-like object.

    Returns
    -------
    (ibi_n_ms, ibi_n1_ms)
        Aligned arrays of equal length; empty when fewer than two adjacent
        valid intervals exist.
    """
    x, y, _t = poincare_points(events)
    return x, y


def poincare_points(events) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """Like :func:`poincare_pairs`, but also return the beat time of each pair.

    Returns
    -------
    (ibi_n_ms, ibi_n1_ms, time_s)
        The IBI pair and the R-peak time of beat *n* (so a click on a cloud
        point can be traced back to its place in the recording).
    """
    ibi_ms, valid = ibi_ms_full_with_mask(events)
    if ibi_ms.size < 2:
        empty = np.array([], dtype=float)
        return empty, empty, empty
    pair_ok = valid[:-1] & valid[1:]
    times = np.asarray(events.times, dtype=float)
    return ibi_ms[:-1][pair_ok], ibi_ms[1:][pair_ok], times[:-1][pair_ok]


@dataclass(frozen=True)
class PoincareDescriptors:
    """Geometric descriptors of a Poincaré cloud (all in ms).

    ``sd1`` / ``sd2`` are the minor / major axes of the dispersion ellipse
    (short- and long-term variability); ``cx`` / ``cy`` its centre.
    """

    sd1: float
    sd2: float
    cx: float
    cy: float


def poincare_descriptors(events) -> "PoincareDescriptors | None":
    """Return :class:`PoincareDescriptors` for the Poincaré cloud, or ``None``.

    ``SD1 = sqrt(½·var(xₙ − xₙ₊₁))`` (short-term), ``SD2 = sqrt(½·var(xₙ +
    xₙ₊₁))`` (long-term), computed from the same artefact-aware consecutive
    pairs as :func:`poincare_pairs`.  ``None`` when fewer than two pairs exist.
    """
    x, y = poincare_pairs(events)
    if x.size < 2:
        return None
    sd1 = float(np.sqrt(0.5) * np.std(x - y))
    sd2 = float(np.sqrt(0.5) * np.std(x + y))
    return PoincareDescriptors(sd1=sd1, sd2=sd2, cx=float(np.mean(x)), cy=float(np.mean(y)))
