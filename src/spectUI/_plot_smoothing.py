"""Plot-only smoothing helpers shared by the PSD and Profile widgets.

CARSPAN applies a 3-point moving-average smoother to both its
**spectrum** plots (manual §3.2 p. 33 — "a moving average window over
three frequency points (0.03 Hz bandwidth) is applied before plotting
the spectral functions") and its **profile** plots (same kernel,
applied along the time axis to each band-power trace). Both spectHR
widgets reach for the same helper here so the boundary policy stays
consistent between them.

The smoother lives in ``spectUI`` rather than ``spectHR`` because it
is **plot-only** — band-power integration in the library never sees
the smoothed array. Keeping it out of the compute layer is what makes
``series.psd()`` / ``series.band_powers()`` round-trip cleanly across
plot toggles.
"""

from __future__ import annotations

import numpy as np


def ma3(arr: np.ndarray) -> np.ndarray:
    """CARSPAN's 3-point moving-average smoother with Pascal-faithful
    edge weights.

    The interior is a plain 3-point mean. The boundaries follow Pascal
    ``MAW_R`` (``T_AnaFunctions.pas:595-643``): instead of zero-padding
    (what ``np.convolve(mode='same')`` does, which artificially pulls
    the first and last bin toward zero), Pascal synthesises a head /
    tail value of ``0.125·x[0] + 0.875·x[1]`` and runs the standard
    3-mean across the lifted array. Algebraically that resolves to::

        out[0]   = 3/8 · x[0]   + 5/8 · x[1]
        out[N-1] = 5/8 · x[N-2] + 3/8 · x[N-1]

    so each boundary stays anchored to its inside neighbour rather
    than being dragged toward zero. For a typical HRV spectrum
    (peaked in the middle, low tails) the difference is ~30 % at the
    very first and last bin; for a band-power profile time series
    the difference is visible whenever the recording starts or ends
    with non-zero activity.

    Mean-preserving on the interior, so the area under the curve is
    preserved. Returns a fresh ``float64`` array; the input is not
    mutated. Arrays shorter than 3 are returned unchanged (a 1- or
    2-element smoother is not meaningful for this kernel).
    """
    if arr is None or arr.size < 3:
        return arr
    out = np.empty_like(arr, dtype=np.float64)
    out[1:-1] = (arr[:-2] + arr[1:-1] + arr[2:]) / 3.0
    out[0]    = 3.0 / 8.0 * arr[0]   + 5.0 / 8.0 * arr[1]
    out[-1]   = 5.0 / 8.0 * arr[-2]  + 3.0 / 8.0 * arr[-1]
    return out
