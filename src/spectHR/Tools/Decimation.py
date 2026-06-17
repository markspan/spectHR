# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Min/max-envelope decimation for cheap overview rendering.

A pure-numpy data-reduction routine: it has no Qt or matplotlib
dependency, so it lives in the headless library and is reusable from
scripts and tests as well as the plot widgets.
"""
from __future__ import annotations

import numpy as np


def decimate_minmax(
    times: np.ndarray,
    values: np.ndarray,
    target_points: int = 4000,
) -> tuple[np.ndarray, np.ndarray]:
    """Min/max-envelope decimation for cheap overview rendering.

    An overview axis is only a couple of thousand pixels wide, so plotting
    a multi-million-sample recording into it is almost entirely wasted
    work, and it is re-rendered on every mouse-move while the window
    rectangle is dragged. This reduces the line to ~``target_points``
    points while preserving the visual envelope: the signal is split into
    buckets and each bucket contributes its min and its max (in time
    order), so tall narrow features like ECG R-peaks survive instead of
    being skipped by plain stride sampling.

    NaN-safe: a bucket with no finite samples emits NaN, so gaps in series
    like the heart-rate trace remain visible as line breaks.

    Returns the input unchanged when it is already small enough.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)
    n = times.size
    if n <= target_points or n < 4:
        return times, values

    n_buckets = max(1, target_points // 2)
    bucket = n // n_buckets
    if bucket < 2:
        return times, values

    usable = n_buckets * bucket
    t = times[:usable].reshape(n_buckets, bucket)
    v = values[:usable].reshape(n_buckets, bucket)

    finite = np.isfinite(v)
    has_finite = finite.any(axis=1)
    # Ignore NaN when locating the per-bucket extrema.
    v_min_src = np.where(finite, v, np.inf)
    v_max_src = np.where(finite, v, -np.inf)
    imin = v_min_src.argmin(axis=1)
    imax = v_max_src.argmax(axis=1)

    cols = np.arange(n_buckets)
    t_min, v_min = t[cols, imin], v[cols, imin]
    t_max, v_max = t[cols, imax], v[cols, imax]
    first_is_min = imin <= imax

    out_t = np.empty(n_buckets * 2)
    out_v = np.empty(n_buckets * 2)
    out_t[0::2] = np.where(first_is_min, t_min, t_max)
    out_t[1::2] = np.where(first_is_min, t_max, t_min)
    out_v[0::2] = np.where(first_is_min, v_min, v_max)
    out_v[1::2] = np.where(first_is_min, v_max, v_min)

    # All-NaN buckets: emit NaN so the gap is preserved as a line break.
    if not has_finite.all():
        out_v[np.repeat(~has_finite, 2)] = np.nan

    # Tail samples that did not fill a whole bucket.
    if usable < n:
        out_t = np.concatenate([out_t, times[usable:]])
        out_v = np.concatenate([out_v, values[usable:]])

    return out_t, out_v
