# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/ibi_helpers.py
"""
Pure IBI helper functions.

Every function here takes a ``CardioSeriesLike`` as its first argument and
performs read-only operations on its ``.times``, ``.ibi``, and ``.labels``
arrays. There are no side effects and no imports of dataset classes.

These functions are called by:
- ``spectHR.analysis.time_metrics`` (metric computations)
- ``spectHR.analysis.frequency_metrics``
- ``spectHR.analysis.psd._engine.PSDEngine`` (IBI preparation for PSD back-ends)
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

# Labels treated as artefacts and excluded from every computation.
_BAD_LABELS: Tuple[str, ...] = ("TL", "T")


# ---------------------------------------------------------------------------
# Label filtering
# ---------------------------------------------------------------------------

def valid_label_mask(
    labels: np.ndarray,
    bad_labels: Tuple[str, ...] = _BAD_LABELS,
) -> np.ndarray:
    """Boolean mask: ``True`` for every beat *not* tagged as an artefact.

    Parameters
    ----------
    labels :
        Per-beat label array (same length as the IBI / times array).
    bad_labels :
        Tuple of label strings to exclude.  Defaults to ``("TL", "T")``.
    """
    valid = np.ones(len(labels), dtype=bool)
    for bad in bad_labels:
        valid &= labels != bad
    return valid


# ---------------------------------------------------------------------------
# IBI packing
# ---------------------------------------------------------------------------

def ibi_clean_ms(series) -> np.ndarray:
    """Packed valid IBI values in ms, excluding NaN / TL / T.

    Use for magnitude-only metrics (mean, std, min, max, count, sdnn).
    Do **not** use for successive-difference metrics; use
    :func:`successive_diffs_ms` instead to avoid bridging excluded gaps.
    """
    ibi_sec = series.ibi
    if ibi_sec.size == 0:
        return np.array([], dtype=float)
    valid = ~np.isnan(ibi_sec) & valid_label_mask(series.labels)
    return 1000.0 * ibi_sec[valid]


def ibi_ms_full_with_mask(series) -> Tuple[np.ndarray, np.ndarray]:
    """Return ``(ibi_ms, valid)`` both of length ``len(series.ibi)``.

    ``ibi_ms`` : IBIs in ms, NaN for invalid intervals.
    ``valid``  : boolean mask, True where the IBI is usable.

    Positional adjacency equals temporal adjacency in the recording, which
    is what successive-difference metrics need.
    """
    ibi_sec = series.ibi
    if ibi_sec.size == 0:
        return np.array([], dtype=float), np.array([], dtype=bool)
    valid = ~np.isnan(ibi_sec) & valid_label_mask(series.labels)
    ibi_ms = np.where(valid, 1000.0 * ibi_sec, np.nan)
    return ibi_ms, valid


def successive_diffs_ms(series) -> np.ndarray:
    """Differences between consecutive *valid* IBIs that are temporally adjacent.

    Pairs where either interval is invalid are dropped, preventing
    differences from bridging an excluded beat and inflating RMSSD / SDSD /
    SD1 / SD2.
    """
    ibi_ms, valid = ibi_ms_full_with_mask(series)
    if ibi_ms.size < 2:
        return np.array([], dtype=float)
    pair_ok = valid[:-1] & valid[1:]
    if not np.any(pair_ok):
        return np.array([], dtype=float)
    return ibi_ms[1:][pair_ok] - ibi_ms[:-1][pair_ok]


# ---------------------------------------------------------------------------
# PSD protocol helpers
# (called by CardioSeriesView thin wrappers; also used by PSDEngine)
# ---------------------------------------------------------------------------

def ibi_clean_pairs(series) -> Tuple[np.ndarray, np.ndarray]:
    """Return aligned ``(times_s, ibi_ms)`` with invalid intervals removed.

    Used by the IBI-based PSD back-ends (Welch, Lomb-Scargle).
    """
    ibi_s = series.ibi
    labels = series.labels
    valid = ~np.isnan(ibi_s)
    if labels is not None and len(labels) == len(ibi_s):
        valid &= valid_label_mask(labels)
    times_s = series.times[valid]
    values_ms = ibi_s[valid] * 1000.0
    return times_s, values_ms


def event_times_clean(series) -> np.ndarray:
    """R-peak timestamps with artefact-labelled beats removed.

    Used by the CARSPAN event-series PSD path.
    """
    labels = series.labels
    times = series.times
    if labels is None or len(labels) == 0:
        return times.copy()
    return times[valid_label_mask(labels)]


# ---------------------------------------------------------------------------
# Mean-IBI helpers (used by the mMI² unit-conversion factor)
# ---------------------------------------------------------------------------

def mean_ibi_ms(series) -> float:
    """Mean IBI in ms under the manual's ``T/N`` convention.

    ``T`` is the span from first to last clean R-peak; ``N`` is the count
    of clean events.  Matches CARSPAN's ``x̄ = N/T`` harmonic convention.
    """
    times = event_times_clean(series)
    N = times.size
    if N < 2:
        raise ValueError("Need at least 2 R-peak events to compute mean IBI.")
    T = float(times[-1] - times[0])
    return (T / N) * 1000.0


def mean_ibi_ms_arithmetic(series) -> float:
    """Mean IBI in ms under CARSPAN's strict arithmetic-mean-of-rate convention.

    ``1000 / mean(1/IBI_i)`` over the cleaned IBI series.  Matches the
    reference Pascal ``SOC`` exactly.  Used by ``carspan_strict``.
    """
    _, ibi_values_ms = ibi_clean_pairs(series)
    if ibi_values_ms.size == 0:
        raise ValueError(
            "Need at least one IBI to compute the arithmetic-mean rate."
        )
    ibi_values_s = ibi_values_ms.astype(np.float64) * 1e-3
    valid = np.isfinite(ibi_values_s) & (ibi_values_s > 0)
    if not np.any(valid):
        raise ValueError("All cleaned IBI values are non-positive or NaN.")
    am_rate_hz = float(np.mean(1.0 / ibi_values_s[valid]))
    return 1000.0 / am_rate_hz


def mmi2_factor(series, mean_convention: str) -> float:
    """``mean_ibi_ms²`` - converts events²/Hz to mMI²/Hz.

    Parameters
    ----------
    mean_convention : ``"arithmetic"`` or ``"harmonic"``
        ``"arithmetic"`` uses :func:`mean_ibi_ms_arithmetic` (strict CARSPAN
        path); anything else uses the simpler :func:`mean_ibi_ms`.
    """
    if mean_convention == "arithmetic":
        m = mean_ibi_ms_arithmetic(series)
    else:
        m = mean_ibi_ms(series)
    return m ** 2
