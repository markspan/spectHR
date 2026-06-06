# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/icg_metrics.py
"""
Impedance-cardiography (ICG) metric: pre-ejection period (PEP).

PEP is the cleanest non-invasive index of *sympathetic* (beta-adrenergic)
drive to the heart — the branch that HRV alone cannot isolate (Sherwood et
al., 1990; Berntson et al., 2004). It is the interval from the onset of
left-ventricular electrical activation to the opening of the aortic valve,
read off the ICG ``dZ/dt`` waveform.

Availability
------------
VU-AMS EDF exports carry the ICG derivative as the ``DZDT`` channel, which
the EDF loader stores as ``dzdt-[vuams]``. When that channel is present,
:class:`~spectHR.analysis.epoch_context.EpochContext` exposes it and this
module computes a per-beat PEP; its epoch mean becomes the single scalar
``pep`` column in the parameters CSV (blank when no ICG channel is loaded).

B-point detection (experimental)
--------------------------------
Per cardiac interval, within an early-systole search window after the
R-peak:

1. the **C-point** is the maximum of ``dZ/dt`` (peak ejection velocity);
2. the **B-point** (aortic-valve opening) is taken as the point of maximum
   upstroke acceleration before C — the maximum of the second derivative
   of ``dZ/dt`` (equivalently the maximum of the third derivative of
   ``Z``), a standard automated B-point heuristic (Lozano et al., 2007).

PEP is reported as the R-to-B interval in ms. True PEP is measured from
the ECG Q-onset; an optional ``q_offset_ms`` lets the user shift the
reference to approximate Q-onset (Q precedes R by a few tens of ms).
Implausible values (outside ``[pep_min_ms, pep_max_ms]``) are dropped as
``NaN``. Automated B-point detection is error-prone, so PEP here is
**experimental** and should be visually spot-checked.

References
----------
Sherwood, A., et al. (1990). Methodological guidelines for impedance
cardiography. *Psychophysiology*, 27(1), 1-23.
Berntson, G. G., et al. (2004). Cardiac autonomic balance versus regulatory
capacity. *Psychophysiology*, 45(4), 643-652.
Lozano, D. L., et al. (2007). Where to B in dZ/dt. *Psychophysiology*,
44(1), 113-119.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.registry import epoch_metric


__all__ = ["pep_per_beat", "pep"]


def pep_per_beat(
    icg_times: np.ndarray,
    dzdt_values: np.ndarray,
    rpeak_times: np.ndarray,
    *,
    q_offset_ms: float = 0.0,
    search_start_ms: float = 40.0,
    search_frac: float = 0.4,
    search_max_ms: float = 300.0,
    pep_min_ms: float = 40.0,
    pep_max_ms: float = 180.0,
) -> np.ndarray:
    """Per-beat pre-ejection period (R-to-B-point interval) in ms.

    Parameters
    ----------
    icg_times, dzdt_values : np.ndarray
        The ICG ``dZ/dt`` waveform (seconds, physical units), sorted by time.
    rpeak_times : np.ndarray
        R-peak times (seconds) delimiting the cardiac intervals.
    q_offset_ms : float
        Added to every PEP value to approximate the Q-onset reference
        (R-to-B underestimates true Q-to-B PEP). Default 0 (report R-to-B).
    search_start_ms : float
        Start of the B-point search window after the R-peak (default 40 ms).
    search_frac, search_max_ms : float
        The window ends at ``R + min(search_frac · IBI, search_max_ms)``.
    pep_min_ms, pep_max_ms : float
        Physiological plausibility bounds; out-of-range beats become NaN.

    Returns
    -------
    np.ndarray
        One value per cardiac interval (length ``len(rpeak_times) - 1``);
        ``NaN`` where no plausible B-point could be located.
    """
    icg_times = np.asarray(icg_times, dtype=float)
    dzdt = np.asarray(dzdt_values, dtype=float)
    rt = np.asarray(rpeak_times, dtype=float)

    n_beats = max(0, rt.size - 1)
    pep = np.full(n_beats, np.nan)
    if n_beats == 0 or dzdt.size < 8:
        return pep

    for i in range(n_beats):
        r = rt[i]
        ibi = rt[i + 1] - r
        if not np.isfinite(ibi) or ibi <= 0:
            continue

        w_start = r + search_start_ms / 1000.0
        w_end = r + min(search_frac * ibi, search_max_ms / 1000.0)
        if w_end <= w_start:
            continue

        lo = int(np.searchsorted(icg_times, w_start))
        hi = int(np.searchsorted(icg_times, w_end))
        if hi - lo < 5:
            continue

        seg_t = icg_times[lo:hi]
        seg = dzdt[lo:hi]

        c = int(np.argmax(seg))          # C-point: peak ejection velocity
        if c < 4:
            continue

        up_t = seg_t[: c + 1]
        up = seg[: c + 1]
        # B-point: maximum upstroke acceleration before C (max of the second
        # derivative of dZ/dt = third derivative of Z).
        d1 = np.gradient(up, up_t)
        d2 = np.gradient(d1, up_t)
        b = int(np.argmax(d2))
        t_b = up_t[b]

        val = (t_b - r) * 1000.0 + q_offset_ms
        if pep_min_ms <= val <= pep_max_ms:
            pep[i] = val

    return pep


@epoch_metric
def pep(ctx) -> float:
    """Pre-ejection period, epoch mean of per-beat R-to-B intervals (ms; needs ICG dZ/dt)."""
    beats = getattr(ctx, "pep_beats", None)
    if beats is None:
        return float("nan")
    beats = np.asarray(beats, dtype=float)
    valid = beats[np.isfinite(beats)]
    return float(np.mean(valid)) if valid.size > 0 else float("nan")
