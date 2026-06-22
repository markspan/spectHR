# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/signal/ibi_classification.py
"""
Standalone IBI classification algorithm.

The rolling-window beat-label assignment logic, kept as a pure function so it
is independently testable.  :meth:`spectHR.session.Events.detect` and the
re-classification helpers call it with the IBI and label arrays.

Public surface
--------------
classify_ibi(ibi_sec, labels, *, window_length, n_std, max_ibi_sec) -> None
    Classify inter-beat intervals and write labels in-place.
"""
from __future__ import annotations

import numpy as np

from spectHR.logger import logger

__all__ = ["classify_ibi"]


def classify_ibi(
    ibi_sec: np.ndarray,
    labels: np.ndarray,
    *,
    window_length: int   = 51,
    n_std:         float = 4.0,
    max_ibi_sec:   float = 2.0,
) -> None:
    """Classify inter-beat intervals and write beat labels in-place.

    Operates on *labels* in-place: the array is modified and nothing is
    returned. Passes through quietly when *ibi_sec* is empty.

    Labels written
    --------------
    ``"N"``   - normal
    ``"L"``   - long (above rolling upper threshold)
    ``"S"``   - short (below rolling lower threshold)
    ``"TL"``  - too long (> *max_ibi_sec*); excluded from statistics
    ``"SL"``  - short-then-long pattern (ectopic pair)
    ``"SNS"`` - short-normal-short pattern (compensatory pause pair)
    ``"T"``   - degenerate (NaN or <= 0)

    Parameters
    ----------
    ibi_sec : np.ndarray
        Inter-beat intervals in seconds, length N. The last element is
        typically NaN (the per-beat alignment sentinel from ``Events.ibi``).
    labels : np.ndarray
        Label array of the same length N. Modified in-place.
    window_length : int
        Size of the centered rolling window in beats for local mean/std
        computation. When ``N < window_length``, global statistics are
        used instead (short-series fallback).
        Loaded from ``workspace["CardioParameters"]["IbiClassification"]
        ["window_length"]``. Default 51.
    n_std : float
        Threshold width in standard deviations: ``mean ± n_std * std``
        defines the S/L boundaries. Default 4.0.
    max_ibi_sec : float
        Absolute ceiling in seconds. IBIs longer than this are labeled
        ``"TL"`` before rolling statistics are computed, so large
        artefacts do not distort the local thresholds. Default 2.0.

    Algorithm
    ---------
    Step 1  Tag degenerate beats (NaN or <= 0) as ``"T"`` and beats
            exceeding *max_ibi_sec* as ``"TL"``.
    Step 2  Build *ibi_stats*: a copy of *ibi_sec* with T/TL intervals
            replaced by NaN so they do not bias rolling statistics.
            The trailing sentinel NaN is replaced by the last valid IBI.
    Step 3  Short-series fallback (N < window_length): use global
            mean/std instead of rolling statistics.
    Step 4  Rolling statistics: center a window of *window_length* beats
            around each position using ``np.lib.stride_tricks``. Compute
            nanmean and nanstd per window.
    Step 5  Pointwise classification: each non-T/TL beat is labeled
            ``"L"``, ``"S"``, or ``"N"`` based on its position relative
            to the local thresholds.
    Step 6  Sequence heuristics: a ``"S"`` followed immediately by
            ``"L"`` becomes ``"SL"``; a ``"S"``-``"N"``-``"S"`` triplet
            labels the first ``"S"`` as ``"SNS"``.
    Step 7  Log a per-label count summary at INFO level.
    """
    n = ibi_sec.size
    if n == 0:
        return

    # Step 1: degenerate and too-long
    degenerate = np.isnan(ibi_sec) | (ibi_sec <= 0)
    labels[degenerate] = "T"
    too_long = ibi_sec > max_ibi_sec
    labels[too_long] = "TL"

    # Step 2: IBI array for statistics (exclude T and TL)
    ibi_stats = ibi_sec.astype(float, copy=True)
    ibi_stats[degenerate | too_long] = np.nan

    # Replace the trailing NaN sentinel with the last valid IBI so rolling
    # edge-padding does not pull the rightmost windows toward zero.
    if ibi_stats.size >= 2 and np.isnan(ibi_stats[-1]):
        last_valid = ibi_stats[~np.isnan(ibi_stats)]
        if last_valid.size > 0:
            ibi_stats[-1] = last_valid[-1]

    if not np.any(~np.isnan(ibi_stats)):
        return

    # Step 3: short-series fallback
    if n < window_length:
        mean = np.nanmean(ibi_stats)
        std  = np.nanstd(ibi_stats)
        lo   = mean - n_std * std
        hi   = mean + n_std * std
        for i in range(n):
            if labels[i] in ("T", "TL"):
                continue
            labels[i] = "L" if ibi_sec[i] > hi else "S" if ibi_sec[i] < lo else "N"
        return

    # Step 4: rolling statistics (centered window, edge-padded)
    half    = window_length // 2
    padded  = np.pad(ibi_stats, (half, half), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window_length)
    local_mean = np.nanmean(windows, axis=1)[:n]
    local_std  = np.nanstd(windows,  axis=1)[:n]
    lo = local_mean - n_std * local_std
    hi = local_mean + n_std * local_std

    # Step 5: pointwise classification
    for i in range(n):
        if labels[i] in ("T", "TL"):
            continue
        labels[i] = (
            "L" if ibi_sec[i] > hi[i] else "S" if ibi_sec[i] < lo[i] else "N"
        )

    # Step 6: sequence heuristics
    for i in range(n - 1):
        if labels[i] == "S" and labels[i + 1] == "L":
            labels[i] = "SL"
    for i in range(n - 2):
        if labels[i] == "S" and labels[i + 1] == "N" and labels[i + 2] == "S":
            labels[i] = "SNS"

    # Step 7: summary
    unique, counts = np.unique(labels, return_counts=True)
    logger.info(f"IBI classification summary (n_IBI={n}):")
    for lab, cnt in zip(unique, counts):
        logger.info(f"  {lab}: {cnt}")
