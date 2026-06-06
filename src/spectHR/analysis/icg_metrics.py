# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/icg_metrics.py
"""
Impedance-cardiography (ICG) metric: pre-ejection period (PEP).

PEP is the cleanest non-invasive index of *sympathetic* (beta-adrenergic)
drive to the heart — the branch that HRV alone cannot isolate (Sherwood et
al., 1990; Berntson et al., 2004). It is the interval from the onset of
left-ventricular electrical depolarization (the ECG **Q-onset**) to the
opening of the aortic valve (the **B-point** on the ICG ``dZ/dt`` waveform).

Method (aligned with VU-DAMS)
-----------------------------
The VU-DAMS manual (§5.5) does **not** score the ICG beat by beat: the raw
``dZ/dt`` is far too noisy for reliable inflection-point detection on a
single complex. Instead it computes a **Large Scale Ensemble Average** over
all beats in a label, time-locked to the R-peak, and scores one B/C/X point
on that clean averaged complex (Riese et al., 2004). spectHR follows the
same recipe per epoch:

1. **Ensemble average** the ``dZ/dt`` waveform across the epoch's beats,
   R-locked onto a common time grid; likewise the ECG.
2. **Low-pass filter** the averaged complex at 60 Hz (the manual's default;
   "necessary to overcome the noise confound and assure reliable detection
   of the inflection points").
3. **Polarity**: the raw VU-AMS ``dZ/dt`` carries the C-point as a *minimum*
   ("the dZ/dt minimum is shown as a maximum by the program"). The sign is
   auto-detected per signal so the C-point is treated as the dominant
   ejection excursion regardless of stored polarity.
4. **C-point** = ``dZ/dt`` maximum (peak ejection velocity).
5. **B-point** (aortic-valve opening) = point of maximum upstroke
   acceleration before C — the maximum of the second derivative of
   ``dZ/dt`` (Lozano et al., 2007).
6. **Q-onset** = on the ensemble ECG, the isoelectric-to-Q transition just
   before the R-peak. When no Q wave is resolvable, the VU-DAMS fallback of
   Q-point − 12 ms is used (manual TIP17).

PEP is the Q-onset-to-B interval in ms (R-to-B when no ECG is supplied),
one scalar per epoch, exported as the ``pep`` column. Implausible values
(outside ``[pep_min_ms, pep_max_ms]``) become ``NaN``.

The manual is explicit that automated B-point detection "simply will not
work for all signals" and that every ensemble complex is visually inspected
and manually corrected; the automated ``pep`` here should likewise be
spot-checked against the dZ/dt waveform in demanding applications.

References
----------
Sherwood, A., et al. (1990). Methodological guidelines for impedance
cardiography. *Psychophysiology*, 27(1), 1-23.
Riese, H., et al. (2004). Large-scale ensemble averaging of ambulatory
impedance cardiograms. *Behavior Research Methods*, 36(3), 467-477.
Berntson, G. G., et al. (2004). Cardiac autonomic balance versus regulatory
capacity. *Psychophysiology*, 45(4), 643-652.
Lozano, D. L., et al. (2007). Where to B in dZ/dt. *Psychophysiology*,
44(1), 113-119.
Nederend, I., et al. (2017). Impedance cardiography in healthy children and
adolescents. *Psychophysiology*, 54(11), 1610-1617.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.registry import epoch_metric


__all__ = ["pep_per_beat", "pep_ensemble", "pep"]


# ----------------------------------------------------------------------------
# Shared signal helpers
# ----------------------------------------------------------------------------

def _sampling_rate(times: np.ndarray) -> float:
    """Median sampling rate (Hz) of a monotonic time vector; 0 if undefined."""
    if times.size < 2:
        return 0.0
    dt = float(np.median(np.diff(times)))
    return 1.0 / dt if dt > 0 else 0.0


def _lowpass(x: np.ndarray, fs: float, cutoff: float = 60.0, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth low-pass; returns *x* unchanged if not applicable.

    Matches the VU-DAMS 60 Hz ICG low-pass. Skipped when the sampling rate is
    too low for the cut-off or the segment is too short for ``filtfilt``.
    """
    if fs <= 2.0 * cutoff or x.size < 4 * (order + 1):
        return x
    try:
        from scipy.signal import butter, filtfilt
        b, a = butter(order, cutoff / (fs / 2.0), btype="low")
        return filtfilt(b, a, x)
    except Exception:
        return x


def _detect_polarity(
    icg_times: np.ndarray,
    dzdt: np.ndarray,
    rpeak_times: np.ndarray,
    *,
    search_start_ms: float = 40.0,
    search_max_ms: float = 300.0,
) -> float:
    """Return +1 if the C-point sits as a maximum in ``dZ/dt``, else −1.

    The VU-AMS raw ``dZ/dt`` stores the C-point (peak ejection velocity) as a
    *minimum*. We compare, in the early-systole window after each R-peak, the
    positive versus negative excursion from a pre-R baseline and take the sign
    of the dominant deflection across beats.
    """
    if rpeak_times.size == 0 or dzdt.size < 8:
        return 1.0
    # Polarity is a global signal property; a sample of beats suffices. Use
    # binary search (not boolean masks) so this stays cheap on long signals.
    sample = rpeak_times[:-1] if rpeak_times.size > 1 else rpeak_times
    if sample.size > 25:
        sample = sample[np.linspace(0, sample.size - 1, 25).astype(int)]
    votes = 0.0
    n = 0
    for r in sample:
        lo = int(np.searchsorted(icg_times, r + search_start_ms / 1000.0))
        hi = int(np.searchsorted(icg_times, r + search_max_ms / 1000.0))
        if hi - lo < 5:
            continue
        seg = dzdt[lo:hi]
        b0 = int(np.searchsorted(icg_times, r - 0.05))
        b1 = int(np.searchsorted(icg_times, r))
        base = float(np.median(dzdt[b0:b1])) if b1 > b0 else 0.0
        pos = float(seg.max()) - base
        neg = base - float(seg.min())
        votes += 1.0 if pos >= neg else -1.0
        n += 1
    if n == 0:
        return 1.0
    return 1.0 if votes >= 0 else -1.0


def _ensemble_average(
    times: np.ndarray,
    values: np.ndarray,
    rpeak_times: np.ndarray,
    rel_grid: np.ndarray,
) -> tuple[np.ndarray, int]:
    """R-locked ensemble average of *values* onto *rel_grid* (seconds rel. R).

    Returns ``(mean_complex, n_beats)``; samples falling outside the signal are
    ignored per beat, so edge beats contribute only where data exist.
    """
    acc = np.zeros_like(rel_grid)
    cnt = np.zeros_like(rel_grid)
    n_used = 0
    for r in rpeak_times:
        samp = np.interp(r + rel_grid, times, values, left=np.nan, right=np.nan)
        ok = np.isfinite(samp)
        if not ok.any():
            continue
        acc[ok] += samp[ok]
        cnt[ok] += 1.0
        n_used += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(cnt > 0, acc / cnt, np.nan)
    return mean, n_used


def _b_point_index(rel: np.ndarray, ens: np.ndarray, c_idx: int, lo_idx: int) -> int | None:
    """Index of the B-point: max 2nd-derivative of ``dZ/dt`` on the upstroke
    ``[lo_idx, c_idx]`` before the C-point (Lozano et al., 2007)."""
    if c_idx - lo_idx < 4:
        return None
    up_t = rel[lo_idx : c_idx + 1]
    up = ens[lo_idx : c_idx + 1]
    d1 = np.gradient(up, up_t)
    d2 = np.gradient(d1, up_t)
    return lo_idx + int(np.argmax(d2))


def _q_onset_rel(
    ecg_rel: np.ndarray,
    ecg_ens: np.ndarray,
    *,
    q_search_ms: float = 100.0,
    smooth_n: int = 5,
    shallow_frac: float = 0.05,
) -> float:
    """Q-onset time (s, relative to R=0) on the ensemble ECG, or 0.0 (=R).

    Searches ``[−q_search_ms, −10 ms]`` for the Q trough, then walks back to
    the last isoelectric sample. Falls back to *Q-point − 12 ms* when the Q
    wave is too shallow to resolve an onset (VU-DAMS manual TIP17).
    """
    w = (ecg_rel >= -q_search_ms / 1000.0) & (ecg_rel <= -0.010)
    if w.sum() < 5:
        return 0.0
    seg_t = ecg_rel[w]
    seg = ecg_ens[w]
    if smooth_n > 1 and seg.size > smooth_n:
        seg = np.convolve(seg, np.ones(smooth_n) / smooth_n, mode="same")

    q_idx = int(np.argmin(seg))
    q_time = float(seg_t[q_idx])

    # R amplitude (peak near rel=0) for the shallow-Q test.
    r_region = ecg_ens[(ecg_rel >= -0.02) & (ecg_rel <= 0.02)]
    r_amp = float(np.nanmax(r_region)) if r_region.size else float(np.nanmax(ecg_ens))
    baseline = float(np.median(seg[: max(1, q_idx // 2)])) if q_idx >= 2 else float(seg[0])
    q_depth = baseline - float(seg[q_idx])
    span = r_amp - baseline

    # No resolvable Q wave → VU-DAMS fallback: Q-point − 12 ms.
    if span <= 0 or q_depth < shallow_frac * span or q_idx < 2:
        return q_time - 0.012

    pre = seg[: q_idx + 1]
    d1 = np.gradient(pre, seg_t[: q_idx + 1])
    non_neg = np.where(d1 >= 0)[0]
    if non_neg.size == 0 or int(non_neg[-1]) == 0:
        return q_time - 0.012      # never returned to baseline → fallback
    return float(seg_t[int(non_neg[-1])])


# ----------------------------------------------------------------------------
# Ensemble PEP (primary, VU-DAMS-aligned)
# ----------------------------------------------------------------------------

def pep_ensemble(
    icg_times: np.ndarray,
    dzdt_values: np.ndarray,
    rpeak_times: np.ndarray,
    *,
    ecg_times: np.ndarray | None = None,
    ecg_values: np.ndarray | None = None,
    pre_ms: float = 200.0,
    post_ms: float = 400.0,
    lp_cutoff: float = 60.0,
    q_search_ms: float = 100.0,
    search_start_ms: float = 40.0,
    search_max_ms: float = 300.0,
    min_beats: int = 5,
    pep_min_ms: float = 40.0,
    pep_max_ms: float = 180.0,
) -> float:
    """Single epoch PEP (ms) from the ensemble-averaged ICG/ECG complex.

    Parameters
    ----------
    icg_times, dzdt_values : np.ndarray
        ICG ``dZ/dt`` waveform (seconds, physical units).
    rpeak_times : np.ndarray
        R-peak times (seconds) for the epoch — the ensemble-averaging anchors.
    ecg_times, ecg_values : np.ndarray | None
        ECG waveform for Q-onset detection. When omitted the R-peak is the
        PEP reference (R-to-B interval).
    pre_ms, post_ms : float
        Ensemble window around each R-peak.
    lp_cutoff : float
        ICG low-pass cut-off (Hz); VU-DAMS default 60.
    min_beats : int
        Minimum beats required to form an ensemble; otherwise ``NaN``.

    Returns
    -------
    float
        Epoch PEP in ms, or ``NaN`` when no plausible B-point/ensemble exists.
    """
    icg_times = np.asarray(icg_times, dtype=float)
    dzdt = np.asarray(dzdt_values, dtype=float)
    rt = np.asarray(rpeak_times, dtype=float)

    fs = _sampling_rate(icg_times)
    if fs <= 0 or rt.size < min_beats or dzdt.size < 8:
        return float("nan")

    dt = 1.0 / fs
    rel = np.arange(-pre_ms / 1000.0, post_ms / 1000.0 + dt, dt)

    ens, n_used = _ensemble_average(icg_times, dzdt, rt, rel)
    if n_used < min_beats or not np.isfinite(ens).any():
        return float("nan")

    # Fill any residual gaps before filtering, then 60 Hz low-pass.
    ens = np.interp(rel, rel[np.isfinite(ens)], ens[np.isfinite(ens)])
    ens = _lowpass(ens, fs, cutoff=lp_cutoff)

    # Orient so the C-point is a maximum (raw VU-AMS dZ/dt has C as a min).
    ens = ens * _detect_polarity(
        icg_times, dzdt, rt,
        search_start_ms=search_start_ms, search_max_ms=search_max_ms,
    )

    # C-point: dZ/dt maximum in the ejection window.
    ej = (rel >= search_start_ms / 1000.0) & (rel <= search_max_ms / 1000.0)
    ej_idx = np.where(ej)[0]
    if ej_idx.size < 5:
        return float("nan")
    c_idx = ej_idx[int(np.argmax(ens[ej_idx]))]

    # B-point: max upstroke acceleration before C.
    b_idx = _b_point_index(rel, ens, c_idx, ej_idx[0])
    if b_idx is None:
        return float("nan")
    t_b = float(rel[b_idx])

    # Reference: Q-onset (ensemble ECG) when available, else R-peak (rel=0).
    t_ref = 0.0
    if ecg_times is not None and ecg_values is not None and np.asarray(ecg_times).size:
        ecg_t = np.asarray(ecg_times, dtype=float)
        ecg_v = np.asarray(ecg_values, dtype=float)
        ecg_ens, n_ecg = _ensemble_average(ecg_t, ecg_v, rt, rel)
        if n_ecg >= min_beats and np.isfinite(ecg_ens).any():
            ecg_ens = np.interp(
                rel, rel[np.isfinite(ecg_ens)], ecg_ens[np.isfinite(ecg_ens)]
            )
            t_ref = _q_onset_rel(rel, ecg_ens, q_search_ms=q_search_ms)

    val = (t_b - t_ref) * 1000.0
    return val if pep_min_ms <= val <= pep_max_ms else float("nan")


# ----------------------------------------------------------------------------
# Per-beat PEP (secondary; kept for inspection / non-ensemble use)
# ----------------------------------------------------------------------------

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
    """Per-beat PEP (Q-onset-to-B, or R-to-B) in ms — single-complex scoring.

    This is the un-averaged variant. It applies the same polarity correction
    as :func:`pep_ensemble`, but single-beat ``dZ/dt`` is noisy, so for
    reported metrics prefer the ensemble result. Returns one value per cardiac
    interval (length ``len(rpeak_times) - 1``); ``NaN`` where no plausible
    B-point could be located.
    """
    icg_times = np.asarray(icg_times, dtype=float)
    dzdt = np.asarray(dzdt_values, dtype=float)
    rt = np.asarray(rpeak_times, dtype=float)

    n_beats = max(0, rt.size - 1)
    pep = np.full(n_beats, np.nan)
    if n_beats == 0 or dzdt.size < 8:
        return pep

    # Orient once for the whole signal so C-points read as maxima.
    dzdt = dzdt * _detect_polarity(
        icg_times, dzdt, rt,
        search_start_ms=search_start_ms, search_max_ms=search_max_ms,
    )

    use_ecg = (
        ecg_times is not None and ecg_values is not None
        and np.asarray(ecg_times).size > 0
    )
    if use_ecg:
        ecg_t = np.asarray(ecg_times, dtype=float)
        ecg_v = np.asarray(ecg_values, dtype=float)

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

        b = _b_point_index(seg_t, seg, c, 0)
        if b is None:
            continue
        t_b = seg_t[b]

        # PEP reference: Q-onset when ECG is available, R-peak otherwise.
        if use_ecg:
            ref = r + _q_onset_per_beat(ecg_t, ecg_v, r, q_search_ms=q_search_ms)
        else:
            ref = r

        val = (t_b - ref) * 1000.0
        if pep_min_ms <= val <= pep_max_ms:
            pep[i] = val

    return pep


def _q_onset_per_beat(
    ecg_times: np.ndarray,
    ecg_values: np.ndarray,
    r_time: float,
    *,
    q_search_ms: float = 100.0,
    smooth_n: int = 5,
) -> float:
    """Q-onset *offset* (s, relative to R, ≤ 0) for a single beat; 0 if none."""
    t_end = r_time - 0.010
    t_start = r_time - q_search_ms / 1000.0
    lo = int(np.searchsorted(ecg_times, t_start))
    hi = int(np.searchsorted(ecg_times, t_end))
    if hi - lo < 5:
        return 0.0
    seg_t = ecg_times[lo:hi]
    seg = ecg_values[lo:hi]
    if smooth_n > 1 and seg.size > smooth_n:
        seg = np.convolve(seg, np.ones(smooth_n) / smooth_n, mode="same")
    q_idx = int(np.argmin(seg))
    if q_idx < 2:
        return float(seg_t[0] - r_time)
    pre = seg[: q_idx + 1]
    d1 = np.gradient(pre, seg_t[: q_idx + 1])
    non_neg = np.where(d1 >= 0)[0]
    onset_idx = int(non_neg[-1]) if non_neg.size else 0
    return float(seg_t[onset_idx] - r_time)


# ----------------------------------------------------------------------------
# Registered metric
# ----------------------------------------------------------------------------

@epoch_metric
def pep(ctx) -> float:
    """Pre-ejection period from the ensemble-averaged complex (ms; needs ICG dZ/dt)."""
    val = getattr(ctx, "pep_value", None)
    if val is None:
        # Bare-view call or no ICG: nothing to compute.
        return float("nan")
    return float(val)
