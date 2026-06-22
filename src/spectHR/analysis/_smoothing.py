# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/_smoothing.py
"""Canonical home for spectHR's 3-point smoothing kernels.

The two kernels are NOT interchangeable

"""

from __future__ import annotations

import numpy as np

__all__ = ["smooth3", "smooth3_triangular"]


# ---------------------------------------------------------------------------
# MAW kernel - the display smoother
# ---------------------------------------------------------------------------


def smooth3(arr: np.ndarray) -> np.ndarray:
    """CARSPAN's 3-point moving-average smoother with Pascal-faithful edges.


        out[0]   = 3/8 . x[0]   + 5/8 . x[1]
        out[N-1] = 5/8 . x[N-2] + 3/8 . x[N-1]

    Parameters
    ----------
    arr : np.ndarray or None
        1-D array to smooth.

    Returns
    -------
    np.ndarray
        Smoothed array, same length as ``arr``.  When ``arr`` is too
        short or ``None``, returns ``arr`` unchanged.
    """
    if arr is None or arr.size < 3:
        return arr
    out = np.empty_like(arr, dtype=np.float64)
    out[1:-1] = (arr[:-2] + arr[1:-1] + arr[2:]) / 3.0
    out[0] = 3.0 / 8.0 * arr[0] + 5.0 / 8.0 * arr[1]
    out[-1] = 5.0 / 8.0 * arr[-2] + 3.0 / 8.0 * arr[-1]
    return out


# ---------------------------------------------------------------------------
# CreateWindow(3) triangular kernel - the in-spectrum smoother
# ---------------------------------------------------------------------------


def smooth3_triangular(x: np.ndarray) -> np.ndarray:
    """3-point triangular frequency smoother (WindowSize=3).

        out[0]    = (x[0] + x[1]) / 2                              # left mirror
        out[k]    = (x[k-1] + 2*x[k] + x[k+1]) / 4                 # interior, k in [1, N-4]
        out[k1]   = (x[k1-1] + 3*x[k1]) / 4                         # right edge, first
                    with k1 = max(1, N-3)
        out[k1+1] = ... = out[N-1] = x[k1]                          # right edge, replicated

    Parameters
    ----------
    x : np.ndarray
        Real or complex 1-D spectrum.

    Returns
    -------
    np.ndarray
        Smoothed spectrum, same length and dtype family as ``x``.
        Arrays shorter than 3 are returned as a copy unchanged.
    """
    n = x.size
    if n < 3:
        return x.copy()

    # Use a complex buffer iff the input is complex - keeps the real
    # AutoSpectrum path purely real (faster, and the test outputs read
    # like the Pascal trace).
    out_dtype = np.complex128 if np.iscomplexobj(x) else np.float64
    out = np.empty(n, dtype=out_dtype)

    # Left mirror: same as Pascal's MaxPnt-branch with TMPVector =
    # [x[1], x[0], x[1]] -> (x[0] + x[1]) / 2.
    out[0] = (x[0] + x[1]) / 2.0

    # Interior bins (output_index in [1, N-4]); only present when N >= 5.
    if n >= 5:
        out[1 : n - 3] = (x[: n - 4] + 2.0 * x[1 : n - 3] + x[2 : n - 2]) / 4.0

    # First right-edge bin: TMPVector = [x[k1-1], x[k1], x[k1]]
    #   -> (x[k1-1] + 3*x[k1]) / 4.
    # k1 = max(1, N-3) - for N == 3 this collapses onto out[1].
    k1 = max(1, n - 3)
    out[k1] = (x[k1 - 1] + 3.0 * x[k1]) / 4.0

    # Remaining right-edge bins: Pascal's replicate-centre policy makes
    # TMPVector saturate at [x[k1], x[k1], x[k1]] -> x[k1].
    if k1 + 1 < n:
        out[k1 + 1 :] = x[k1]

    return out
