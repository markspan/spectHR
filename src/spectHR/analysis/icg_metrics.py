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

B-point detection
-----------------
Per cardiac interval, within an early-systole search window after the
Q-onset (or R-peak when no ECG is available):

1. the **C-point** is the maximum of ``dZ/dt`` (peak ejection velocity);
2. the **B-point** (aortic-valve opening) is taken as the point of maximum
   upstroke acceleration before C — the maximum of the second derivative
   of ``dZ/dt`` (equivalently the maximum of the third derivative of
   ``Z``), a standard automated B-point heuristic (Lozano et al., 2007).

Q-onset detection
-----------------
When the ECG waveform is provided (``ecg_times``/``ecg_values``), each
beat's PEP reference is shifted from the R-peak to the true ECG Q-onset.
The algorithm searches backward from the R-peak in a 100 ms window:

1. the **Q trough** is the minimum of the lightly smoothed ECG in
   ``[R − 100 ms, R − 10 ms]``;
2. the **Q-onset** is the last sample before the Q trough at which the
   smoothed ECG gradient is non-negative (the point where the waveform
   transitions from isoelectric baseline to the Q-wave descent).

This yields the true clinical PEP (Q-onset to B-point). Without an ECG
the reported value is the slightly shorter R-to-B interval; the column
is still named ``pep`` in both cases.

Implausible values (outside ``[pep_min_ms, pep_max_ms]``) are replaced
with ``NaN``. B-point detection is heuristic, so individual beats should
be spot-checked in demanding applications.

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


def _find_q_onset(
    ecg_times: np.ndarray,
    ecg_values: np.ndarray,
    r_time: float,
    *,
    q_search_ms: float = 100.0,
    smooth_n: int = 5,
) -> float:
    """Return the Q-onset time preceding *r_time*, or *r_time* if undetectable.

    Searches ``[r_time − q_search_ms, r_time − 10 ms]`` for the Q trough
    (argmin of lightly smoothed ECG), then walks backward from the trough
    to the last sample with a non-negative gradient — the isoelectric-to-Q
    descent transition.
    """
    t_end = r_time - 0.010          # Q trough is at least 10 ms before R
    t_start = r_time - q_search_ms / 1000.0
    lo = int(np.searchsorted(ecg_times, t_start))
    hi = int(np.searchsorted(ecg_times, t_end))
    if hi - lo < 5:
        return r_time               # window too narrow — fall back to R

    seg_t = ecg_times[lo:hi]
    seg = ecg_values[lo:hi]

    if smooth_n > 1 and seg.size > smooth_n:
        seg = np.convolve(seg, np.ones(smooth_n) / smooth_n, mode="same")

    q_idx = int(np.argmin(seg))
    if q_idx < 2:
        return float(seg_t[0])

    pre_t = seg_t[: q_idx + 1]
    pre = seg[: q_idx + 1]
    d1 = np.gradient(pre, pre_t)
    non_neg = np.where(d1 >= 0)[0]
    onset_idx = int(non_neg[-1]) if non_neg.size else 0
    return float(pre_t[onset_idx])


def pep_per_beat(
    icg_times: np.ndarray,
    dzdt_values: np.ndarray,
    rpeak_times: np.ndarray,
    *,
    ecg_times: np.ndarray | None = None,
    ecg_values: np.ndarray | None = None,
    q_search_ms: float = 100.0,
    search_start_ms: float = 40.0,
    search_frac: float = 0.4,
    search_max_ms: float = 300.0,
    pep_min_ms: float = 40.0,
    pep_max_ms: float = 180.0,
) -> np.ndarray:
    """Per-beat pre-ejection period (Q-onset-to-B-point, or R-to-B) in ms.

    Parameters
    ----------
    icg_times, dzdt_values : np.ndarray
        The ICG ``dZ/dt`` waveform (seconds, physical units), sorted by time.
    rpeak_times : np.ndarray
        R-peak times (seconds) delimiting the cardiac intervals.
    ecg_times, ecg_values : np.ndarray | None
        ECG waveform used for Q-onset detection.  When provided each beat's
        PEP is measured from the detected Q-onset (true clinical PEP);
        otherwise from the R-peak (slightly shorter R-to-B interval).
    q_search_ms : float
        Backward search window for Q-onset detection (default 100 ms).
    search_start_ms : float
        Start of the B-point search window after the reference time (default
        40 ms).
    search_frac, search_max_ms : float
        The window ends at ``ref + min(search_frac · IBI, search_max_ms)``.
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

    use_ecg = (
        ecg_times is not None and ecg_values is not None
        and np.asarray(ecg_times).size > 0
    )
    if use_ecg:
        ecg_t = np.asarray(ecg_times, dtype=float)
        ecg_v = np.asarray(ecg_values, dtype=float)

    n_beats = max(0, rt.size - 1)
    pep = np.full(n_beats, np.nan)
    if n_beats == 0 or dzdt.size < 8:
        return pep

    for i in range(n_beats):
        r = rt[i]
        ibi = rt[i + 1] - r
        if not np.isfinite(ibi) or ibi <= 0:
            continue

        # PEP reference: Q-onset when ECG is available, R-peak otherwise.
        if use_ecg:
            ref = _find_q_onset(ecg_t, ecg_v, r, q_search_ms=q_search_ms)
        else:
            ref = r

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

        val = (t_b - ref) * 1000.0
        if pep_min_ms <= val <= pep_max_ms:
            pep[i] = val

    return pep


@epoch_metric
def pep(ctx) -> float:
    """Pre-ejection period, epoch mean of per-beat Q-onset-to-B intervals (ms; needs ICG dZ/dt)."""
    beats = getattr(ctx, "pep_beats", None)
    if beats is None:
        return float("nan")
    beats = np.asarray(beats, dtype=float)
    valid = beats[np.isfinite(beats)]
    return float(np.mean(valid)) if valid.size > 0 else float("nan")
