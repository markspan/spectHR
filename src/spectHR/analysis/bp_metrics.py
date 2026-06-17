# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/bp_metrics.py
"""
Beat-by-beat **blood-pressure** parameters (the BP waveform series).

This module ports the CARSPAN (``T_EventFile.pas``) blood-pressure data-column
algorithms to spectHR's time-domain data model.  CARSPAN gates every value on
the R-peaks of the active cardio series: each cardiac interval ``[R_i, R_{i+1}]``
yields exactly one value, which makes the parameters directly comparable to the
HRV metrics computed on the same R-peaks.

Registered epoch metrics (one CSV/HDF5 column each, the function name)
---------------------------------------------------------------------
* ``bp_sbp`` — systolic blood pressure: epoch mean of the per-beat maxima.
* ``bp_dbp`` — diastolic blood pressure: epoch mean of the foot minima that
  precede each systolic peak.
* ``bp_pp``  — pulse pressure (SBP − DBP), epoch mean over beats.
* ``bp_map`` — mean arterial pressure: the true integral mean of the waveform
  between two successive diastolic minima (CARSPAN ``CalcDataColBPMPR``), **not**
  the textbook ``(SBP + 2·DBP) / 3`` approximation.

Respiration (``resp_mvo`` / ``resp_svo``) and respiratory sinus arrhythmia
(``rsa`` / ``rsa0``) used to live here too; they are now in
:mod:`spectHR.analysis.respiration_metrics` so each module covers one series.

Flat-line guard
---------------
CARSPAN's ``IsFlatLine`` slides a 300 ms / 10 ms-step window across each cardiac
interval and rejects the beat when the mean is zero or the coefficient of
variation (``std / mean``) drops below 0.005 anywhere — the signature of a
disconnected or clamped pressure transducer.  Because the test is
scale-invariant it works directly on the physically-scaled values spectHR
stores (CARSPAN ran it on raw, unscaled samples).  Rejected beats become
``NaN`` here (rather than CARSPAN's ``0``) so that per-epoch ``nanmean``
aggregation simply ignores them instead of being dragged toward zero.

Aggregation
-----------
:func:`bp_epoch_metrics` returns the ``nanmean`` of the beat-by-beat values that
fall inside an epoch, keyed with the column names that flow through
:meth:`~spectHR.session.Session.epochs_table` into the CSV and HDF5 exports.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from spectHR.analysis._beat_sampling import median_dt, nanmean, rpeak_sample_indices
from spectHR.analysis.registry import epoch_metric

# CARSPAN IsFlatLine constants (T_EventFile.pas).
_FLATLINE_WINDOW_S = 0.300  # Twin  - 300 ms analysis window
_FLATLINE_STEP_S = 0.010  # Tstep - 10 ms slide step
_FLATLINE_VC = 0.005  # variation-coefficient threshold


# ---------------------------------------------------------------------------
# Flat-line guard
# ---------------------------------------------------------------------------


def is_flatline(
    sig_times: np.ndarray,
    sig_values: np.ndarray,
    idx_b: int,
    idx_e: int,
    dt: Optional[float] = None,
) -> bool:
    """Return True when ``sig_values[idx_b:idx_e]`` looks like a flat line.

    Faithful port of CARSPAN ``TEventFile.IsFlatLine``: a 300 ms window is slid
    in 10 ms steps from *idx_b* toward *idx_e*; the beat is flagged as soon as
    one window has a zero mean or a coefficient of variation below 0.005.  When
    the interval is shorter than the window the test runs once.

    *dt* is the (uniform) sample interval in seconds.  When ``None`` it is
    derived from ``sig_times`` via :func:`median_dt`; callers that test many
    beats of the same signal should compute it once and pass it in, since the
    median is an O(N log N) scan of the *whole* waveform and is otherwise
    repeated for every beat.
    """
    n = sig_values.size
    if idx_e <= idx_b or idx_b >= n:
        return True

    if dt is None:
        dt = median_dt(sig_times)
    if dt is None or dt <= 0:
        return True

    n_win = max(1, int(round(_FLATLINE_WINDOW_S / dt)))
    n_step = max(1, int(round(_FLATLINE_STEP_S / dt)))

    b = idx_b
    e = b + n_win
    if e >= idx_e:
        e = idx_e - 1
    if e >= n:  # R-peak past end of signal
        return True

    while e < idx_e:
        seg = sig_values[b : e + 1]
        if seg.size:
            mean = float(np.mean(seg))
            std = float(np.std(seg))  # population std (CARSPAN /N)
            if mean == 0.0:
                return True
            if abs(std / mean) < _FLATLINE_VC:
                return True
        b += n_step
        e = b + n_win

    return False


# ---------------------------------------------------------------------------
# Blood-pressure beat-by-beat parameters
# ---------------------------------------------------------------------------


def bp_beat_parameters(
    bp_times: np.ndarray,
    bp_values: np.ndarray,
    rpeak_times: np.ndarray,
) -> dict[str, np.ndarray]:
    """Compute per-beat SBP, DBP, PP and MAP for the given R-peaks.

    Parameters
    ----------
    bp_times, bp_values : np.ndarray
        The blood-pressure waveform (seconds, physical units), sorted by time.
    rpeak_times : np.ndarray
        R-peak times (seconds) that delimit the cardiac intervals.

    Returns
    -------
    dict[str, np.ndarray]
        ``"sbp"``, ``"dbp"``, ``"pp"`` and ``"map"`` arrays, each of length
        ``len(rpeak_times) - 1`` (one value per cardiac interval).  Flat-line
        and degenerate beats are ``NaN``.  ``"map"`` additionally carries
        ``NaN`` in its final slot, which needs the *next* beat's diastolic
        minimum and therefore has no value for the last interval.

    Notes
    -----
    CARSPAN iterates ``for i := 1 to RPeaks.Count - 1`` with an off-by-one that
    makes the first loop interval degenerate; we instead compute one clean value
    per genuine interval ``[R_i, R_{i+1}]``.  The value *definitions* (max,
    min-before-max, max-min, mean between successive diastoles) are reproduced
    exactly.
    """
    bp_times = np.asarray(bp_times, dtype=float)
    bp_values = np.asarray(bp_values, dtype=float)
    rpeak_times = np.asarray(rpeak_times, dtype=float)

    n_beats = max(0, rpeak_times.size - 1)
    sbp = np.full(n_beats, np.nan)
    dbp = np.full(n_beats, np.nan)
    pp = np.full(n_beats, np.nan)
    mapr = np.full(n_beats, np.nan)
    if n_beats == 0 or bp_values.size < 2:
        return {"sbp": sbp, "dbp": dbp, "pp": pp, "map": mapr}

    idx = rpeak_sample_indices(bp_times, rpeak_times)

    # Sample interval is uniform across the waveform; compute it once and
    # reuse for every beat's flat-line test (otherwise is_flatline rescans
    # the whole bp_times array per beat - the profile hot path).
    dt = median_dt(bp_times)

    # Diastolic-minimum sample index per beat - reused by the MAP pass.
    dia_idx = np.full(n_beats, -1, dtype=int)

    for i in range(n_beats):
        lo, hi = int(idx[i]), int(idx[i + 1])
        if hi <= lo:
            continue
        if is_flatline(bp_times, bp_values, lo, hi, dt=dt):
            continue

        seg = bp_values[lo : hi + 1]  # inclusive, as CARSPAN IdxB..IdxE
        if seg.size == 0:
            continue

        max_local = int(np.argmax(seg))
        max_global = lo + max_local
        sys_val = float(bp_values[max_global])

        # Diastole: minimum sample *before* (up to and including) the systole.
        pre = bp_values[lo : max_global + 1]
        min_local = int(np.argmin(pre))
        min_global = lo + min_local
        dia_val = float(bp_values[min_global])

        sbp[i] = sys_val
        dbp[i] = dia_val
        pp[i] = sys_val - dia_val
        dia_idx[i] = min_global

    # MAP: mean of raw samples between two successive diastolic minima.
    for i in range(n_beats - 1):
        d0, d1 = int(dia_idx[i]), int(dia_idx[i + 1])
        if d0 < 0 or d1 < 0 or d1 <= d0:
            continue
        seg = bp_values[d0 : d1 + 1]
        if seg.size:
            mapr[i] = float(np.mean(seg))

    return {"sbp": sbp, "dbp": dbp, "pp": pp, "map": mapr}


def bp_epoch_metrics(
    bp_ts,
    rpeak_times: np.ndarray,
) -> dict[str, float]:
    """Aggregate per-beat BP parameters into per-epoch scalars.

    Parameters
    ----------
    bp_ts : TimeSeries-like
        Object exposing ``.times`` and ``.values`` for the BP waveform.
    rpeak_times : np.ndarray
        R-peak times (seconds) restricted to the epoch of interest.

    Returns
    -------
    dict[str, float]
        ``{"bp_sbp", "bp_dbp", "bp_pp", "bp_map"}`` - the ``nanmean`` of the
        beat-by-beat values (NaN when no valid beat falls in the epoch).
    """
    beats = bp_beat_parameters(
        np.asarray(bp_ts.times, dtype=float),
        np.asarray(bp_ts.values, dtype=float),
        np.asarray(rpeak_times, dtype=float),
    )
    return {
        "bp_sbp": nanmean(beats["sbp"]),
        "bp_dbp": nanmean(beats["dbp"]),
        "bp_pp": nanmean(beats["pp"]),
        "bp_map": nanmean(beats["map"]),
    }


# ---------------------------------------------------------------------------
# Registered single-valued epoch metrics
# ---------------------------------------------------------------------------
#
# Each metric reads the per-beat parameter dict cached on the
# :class:`~spectHR.analysis.epoch_context.EpochContext` (so the underlying
# ``bp_beat_parameters`` pass runs at most once per epoch) and returns the epoch
# ``nanmean`` of one parameter.  When the BP channel is absent the context
# yields ``None`` and the metric reports ``NaN``.  The column name is the
# function name.


def _bp_metric(ctx, key: str) -> float:
    beats = getattr(ctx, "bp_beats", None)
    if not beats:
        return float("nan")
    return nanmean(beats[key])


@epoch_metric
def bp_sbp(ctx) -> float:
    """Systolic blood pressure, epoch mean of the per-beat maxima (CARSPAN)."""
    return _bp_metric(ctx, "sbp")


@epoch_metric
def bp_dbp(ctx) -> float:
    """Diastolic blood pressure, epoch mean of the per-beat foot minima (CARSPAN)."""
    return _bp_metric(ctx, "dbp")


@epoch_metric
def bp_pp(ctx) -> float:
    """Pulse pressure (SBP - DBP), epoch mean over beats (CARSPAN)."""
    return _bp_metric(ctx, "pp")


@epoch_metric
def bp_map(ctx) -> float:
    """Mean arterial pressure, epoch mean of the waveform integral mean (CARSPAN)."""
    return _bp_metric(ctx, "map")
