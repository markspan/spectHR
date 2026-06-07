# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/bp_metrics.py
"""
Beat-by-beat blood-pressure and respiration parameters.

This module ports the CARSPAN (``T_EventFile.pas``) beat-by-beat data-column
algorithms to spectHR's time-domain data model.  CARSPAN gates every value on
the R-peaks of the active cardio series: each cardiac interval ``[R_i, R_{i+1}]``
yields exactly one value, which makes the parameters directly comparable to the
HRV metrics computed on the same R-peaks.

Blood pressure (``CalcDataColBPSYS/BPDIA/BPPUL/BPMPR``)
------------------------------------------------------
* **SBP** systolic - the maximum sample in ``[R_i, R_{i+1}]``.
* **DBP** diastolic - the minimum sample *before* the systolic maximum,
  i.e. the foot of the pressure wave that precedes the systolic peak.
* **PP**  pulse pressure - ``SBP - DBP`` for that beat.
* **MAP** mean arterial pressure - the mean of the **raw** samples between two
  successive diastolic minima.  This is CARSPAN's ``CalcDataColBPMPR``; it is
  **not** the textbook ``(SBP + 2*DBP) / 3`` approximation but the true
  integral mean of the waveform over a full beat-to-beat cycle.

Respiration (``CalcDataColRESMVO/RESSVO/RESPVO``)
-------------------------------------------------
* **MVO** mean respiratory volume - the mean of the respiration signal over the
  cardiac interval ``[R_i, R_{i+1}]``.  (CARSPAN's ``RESPVO`` is an exact
  duplicate of ``RESMVO``; only ``MVO`` is exposed here.)
* **SVO** sample respiratory volume - the mean of the respiration signal over a
  short window of ``ResSamples / 2`` samples ending at each R-peak.

Flat-line guard
---------------
CARSPAN's ``IsFlatLine`` slides a 300 ms / 10 ms-step window across each cardiac
interval and rejects the beat when the mean is zero or the coefficient of
variation (``std / mean``) drops below 0.005 anywhere - the signature of a
disconnected or clamped pressure transducer.  Because the test is
scale-invariant it works directly on the physically-scaled values spectHR
stores (CARSPAN ran it on raw, unscaled samples).  Rejected beats become
``NaN`` here (rather than CARSPAN's ``0``) so that per-epoch ``nanmean``
aggregation simply ignores them instead of being dragged toward zero.

Aggregation
-----------
:func:`bp_epoch_metrics` / :func:`resp_epoch_metrics` return the ``nanmean`` of
the beat-by-beat values that fall inside an epoch, keyed with the column names
that flow through
:meth:`~spectHR.DataSet.PhysioData.PhysioData.epoched_parameters_table` into the CSV and
HDF5 exports.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from spectHR.analysis.registry import epoch_metric

# CARSPAN IsFlatLine constants (T_EventFile.pas).
_FLATLINE_WINDOW_S = 0.300  # Twin  - 300 ms analysis window
_FLATLINE_STEP_S = 0.010  # Tstep - 10 ms slide step
_FLATLINE_VC = 0.005  # variation-coefficient threshold

# CARSPAN default DataCol.ResSamples (TEventFile sets ResSamples := 10).
_DEFAULT_RES_SAMPLES = 10


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _median_dt(times: np.ndarray) -> Optional[float]:
    """Median positive sample interval of *times* (seconds), or None."""
    if times.size < 2:
        return None
    dt = np.diff(times)
    dt = dt[(dt > 0) & np.isfinite(dt)]
    if dt.size == 0:
        return None
    return float(np.median(dt))


def _rpeak_sample_indices(sig_times: np.ndarray, rpeak_times: np.ndarray) -> np.ndarray:
    """Map R-peak times onto the nearest sample index of *sig_times*.

    ``np.searchsorted`` gives the insertion point; we clamp it to the valid
    index range so callers can slice ``values`` safely.
    """
    idx = np.searchsorted(sig_times, rpeak_times)
    return np.clip(idx, 0, sig_times.size - 1)


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
    derived from ``sig_times`` via :func:`_median_dt`; callers that test many
    beats of the same signal should compute it once and pass it in, since the
    median is an O(N log N) scan of the *whole* waveform and is otherwise
    repeated for every beat.
    """
    n = sig_values.size
    if idx_e <= idx_b or idx_b >= n:
        return True

    if dt is None:
        dt = _median_dt(sig_times)
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

    idx = _rpeak_sample_indices(bp_times, rpeak_times)

    # Sample interval is uniform across the waveform; compute it once and
    # reuse for every beat's flat-line test (otherwise is_flatline rescans
    # the whole bp_times array per beat - the profile hot path).
    dt = _median_dt(bp_times)

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
        "bp_sbp": _nanmean(beats["sbp"]),
        "bp_dbp": _nanmean(beats["dbp"]),
        "bp_pp": _nanmean(beats["pp"]),
        "bp_map": _nanmean(beats["map"]),
    }


# ---------------------------------------------------------------------------
# Respiration beat-by-beat parameters
# ---------------------------------------------------------------------------


def resp_beat_parameters(
    rsp_times: np.ndarray,
    rsp_values: np.ndarray,
    rpeak_times: np.ndarray,
    *,
    res_samples: int = _DEFAULT_RES_SAMPLES,
) -> dict[str, np.ndarray]:
    """Compute per-beat respiratory-volume parameters for the given R-peaks.

    Parameters
    ----------
    rsp_times, rsp_values : np.ndarray
        The respiration waveform (seconds, physical units), sorted by time.
    rpeak_times : np.ndarray
        R-peak times (seconds).
    res_samples : int
        CARSPAN ``DataCol.ResSamples`` (default 10).  The SVO window spans
        ``res_samples // 2`` samples ending at each R-peak.

    Returns
    -------
    dict[str, np.ndarray]
        ``"mvo"`` - mean respiration over each cardiac interval ``[R_i, R_{i+1}]``
        (length ``len(rpeak_times) - 1``).
        ``"svo"`` - mean respiration over the ``res_samples // 2`` samples ending
        at each R-peak (length ``len(rpeak_times)``).
    """
    rsp_times = np.asarray(rsp_times, dtype=float)
    rsp_values = np.asarray(rsp_values, dtype=float)
    rpeak_times = np.asarray(rpeak_times, dtype=float)

    n_int = max(0, rpeak_times.size - 1)
    mvo = np.full(n_int, np.nan)
    svo = np.full(rpeak_times.size, np.nan)
    if rsp_values.size < 2 or rpeak_times.size == 0:
        return {"mvo": mvo, "svo": svo}

    # Shift the signal so its minimum is 0.  CARSPAN's MVO/SVO are designed
    # for impedance signals that are always positive (= actual lung volume).
    # Z-scored surrogates (e.g. accelerometer-derived RSP from Polar) are
    # centred at 0, so beats landing during exhalation yield negative means.
    # Shifting by the signal minimum makes MVO/SVO non-negative without
    # altering the waveform shape used by all other analyses. Only done when
    # negative values are present, to preserve the original scale when it is
    # already positive.
    rsp_min = rsp_values.min()
    if rsp_min < 0:
        rsp_values = rsp_values - rsp_min

    idx = _rpeak_sample_indices(rsp_times, rpeak_times)

    # MVO: mean over each cardiac interval.
    for i in range(n_int):
        lo, hi = int(idx[i]), int(idx[i + 1])
        if hi < lo:
            continue
        seg = rsp_values[lo : hi + 1]
        if seg.size:
            mvo[i] = float(np.mean(seg))

    # SVO: mean over the half-window of samples ending at each R-peak.
    half = max(1, int(res_samples) // 2)
    for i in range(rpeak_times.size):
        e = int(idx[i])
        b = max(0, e - half)
        seg = rsp_values[b : e + 1]
        if seg.size:
            svo[i] = float(np.mean(seg))

    return {"mvo": mvo, "svo": svo}


def resp_epoch_metrics(
    rsp_ts,
    rpeak_times: np.ndarray,
    *,
    res_samples: int = _DEFAULT_RES_SAMPLES,
) -> dict[str, float]:
    """Aggregate per-beat respiration parameters into per-epoch scalars.

    Returns ``{"resp_mvo", "resp_svo"}`` - the ``nanmean`` of the beat-by-beat
    respiratory-volume values (NaN when the epoch carries no usable beats).
    """
    beats = resp_beat_parameters(
        np.asarray(rsp_ts.times, dtype=float),
        np.asarray(rsp_ts.values, dtype=float),
        np.asarray(rpeak_times, dtype=float),
        res_samples=res_samples,
    )
    return {
        "resp_mvo": _nanmean(beats["mvo"]),
        "resp_svo": _nanmean(beats["svo"]),
    }


# ---------------------------------------------------------------------------
# Registered single-valued epoch metrics
# ---------------------------------------------------------------------------
#
# Each metric reads the per-beat parameter dict cached on the
# :class:`~spectHR.analysis.epoch_context.EpochContext` (so the underlying
# ``bp_beat_parameters`` / ``resp_beat_parameters`` pass runs at most once per
# epoch) and returns the epoch ``nanmean`` of one parameter.  When the
# corresponding waveform channel is absent the context yields ``None`` and the
# metric reports ``NaN``.  The column name is the function name.


def _bp_metric(ctx, key: str) -> float:
    beats = getattr(ctx, "bp_beats", None)
    if not beats:
        return float("nan")
    return _nanmean(beats[key])


def _resp_metric(ctx, key: str) -> float:
    beats = getattr(ctx, "resp_beats", None)
    if not beats:
        return float("nan")
    return _nanmean(beats[key])


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


@epoch_metric
def resp_mvo(ctx) -> float:
    """Mean respiratory volume per cardiac interval, epoch mean (CARSPAN) (no unit!)."""
    return _resp_metric(ctx, "mvo")


@epoch_metric
def resp_svo(ctx) -> float:
    """Sample respiratory volume at each R-peak, epoch mean (CARSPAN) (no unit!)."""
    return _resp_metric(ctx, "svo")


# ---------------------------------------------------------------------------
# Grossman (1990) peak-to-valley RSA
# ---------------------------------------------------------------------------

_DEFAULT_RSA_LAG_S: float = 1.0  # dZ-HR phase shift; VU-DAMS default 1000 ms


def grossman_rsa_per_breath(
    rpeak_times: np.ndarray,
    rpeak_labels: np.ndarray,
    rsp_phases,
    *,
    lag_s: float = _DEFAULT_RSA_LAG_S,
) -> np.ndarray:
    """Per-breath RSA in ms using the Grossman et al. (1990) peak-to-valley method.

    For each INH→EXH breath cycle:

    * **Shortest IBI** — the minimum IBI within ``[INH_start, INH_end + lag_s]``
      that sits on an *accelerating* slope (IBI shorter than the preceding one).
    * **Longest IBI**  — the maximum IBI within ``[EXH_start, EXH_end + lag_s]``
      that sits on a *decelerating* slope (IBI longer than the preceding one).
    * **RSA** = longest − shortest (ms).  Negative values and breaths where
      either IBI could not be located are stored as ``NaN``.

    Parameters
    ----------
    rpeak_times : np.ndarray
        R-peak timestamps in seconds (epoch view, may include artefact beats).
    rpeak_labels : np.ndarray
        Per-beat classification labels; beats labelled ``"T"`` or ``"TL"`` are
        excluded before the search.
    rsp_phases :
        A ``RespirationSeriesView`` (or any object exposing ``.starts``,
        ``.ends``, ``.labels`` arrays) covering the same epoch.
    lag_s : float
        Phase-shift applied to the end of each INH and EXH window (default
        1.0 s, matching VU-DAMS).  Increasing this helps at low respiratory
        rates; the VU-DAMS manual suggests adjusting it for children.

    Returns
    -------
    np.ndarray
        One value per detected INH→EXH pair.  ``NaN`` for invalid breaths.
    """
    from spectHR.analysis.ibi_helpers import valid_label_mask

    clean_t = np.asarray(rpeak_times, dtype=float)[
        valid_label_mask(np.asarray(rpeak_labels, dtype=object))
    ]

    if clean_t.size < 3:
        return np.array([], dtype=float)

    ibi_ms = np.diff(clean_t) * 1000.0  # ibi_ms[j] starts at clean_t[j]

    starts = np.asarray(rsp_phases.starts, dtype=float)
    ends = np.asarray(rsp_phases.ends, dtype=float)
    labels = np.asarray(rsp_phases.labels, dtype=object)

    results: list[float] = []

    for i in range(len(starts) - 1):
        if labels[i] != "INH" or labels[i + 1] != "EXH":
            continue

        inh_s, inh_e = float(starts[i]), float(ends[i])
        exh_s, exh_e = float(starts[i + 1]), float(ends[i + 1])

        wi_lo, wi_hi = inh_s, inh_e + lag_s
        we_lo, we_hi = exh_s, exh_e + lag_s

        inh_idx = np.where((clean_t[:-1] >= wi_lo) & (clean_t[:-1] <= wi_hi))[0]
        exh_idx = np.where((clean_t[:-1] >= we_lo) & (clean_t[:-1] <= we_hi))[0]

        # Shortest IBI on an accelerating slope (IBI[j] < IBI[j-1])
        shortest: float | None = None
        for j in inh_idx:
            if j > 0 and ibi_ms[j] < ibi_ms[j - 1]:
                if shortest is None or ibi_ms[j] < shortest:
                    shortest = float(ibi_ms[j])

        # Longest IBI on a decelerating slope (IBI[j] > IBI[j-1])
        longest: float | None = None
        for j in exh_idx:
            if j > 0 and ibi_ms[j] > ibi_ms[j - 1]:
                if longest is None or ibi_ms[j] > longest:
                    longest = float(ibi_ms[j])

        if shortest is None or longest is None:
            # Undetectable IBI (no qualifying accelerating/decelerating beat).
            # NaN here is excluded from the positive-only RSA mean but counts
            # as zero in RSA0 (which divides by the total breath count).
            results.append(np.nan)
        else:
            # Keep the raw difference, including negatives, so the per-breath
            # export stays informative.  RSA discards negatives; RSA0 counts
            # them (and the NaN above) as zero over the total breath count.
            results.append(float(longest - shortest))

    return np.asarray(results, dtype=float)


def _rsa_metric(ctx, key: str) -> float:
    beats = getattr(ctx, "rsa_beats", None)
    if beats is None or beats.size == 0:
        return float("nan")
    if key == "rsa":
        # Mean of positive-only values (VU-DAMS RSA: excludes negative and missing).
        valid = beats[np.isfinite(beats) & (beats > 0)]
        return float(np.mean(valid)) if valid.size > 0 else float("nan")
    # RSA0 (VU-DAMS): every *invalid* breath — negative RSA OR an undetectable
    # shortest/longest IBI — is **included** in the mean with value zero, i.e.
    # the denominator is the total number of breath cycles in the label
    # (manual §5.4.1: "included in the mean calculation with value zero").
    # Returns NaN only when no breath was measurable at all.
    if not np.any(np.isfinite(beats)):
        return float("nan")
    contrib = np.where(np.isfinite(beats) & (beats > 0), beats, 0.0)
    return float(np.mean(contrib))


@epoch_metric
def rsa(ctx) -> float:
    """Respiratory sinus arrhythmia: mean over valid breath cycles (Grossman 1990 peak-to-valley, ms)."""
    return _rsa_metric(ctx, "rsa")


@epoch_metric
def rsa0(ctx) -> float:
    """RSA with every invalid breath (negative or undetectable) counted as zero over the total breath count; reduces over-estimation bias (VU-DAMS RSA0, ms)."""
    return _rsa_metric(ctx, "rsa0")


# ---------------------------------------------------------------------------
# Aggregation helper
# ---------------------------------------------------------------------------


def _nanmean(arr: np.ndarray) -> float:
    """``np.nanmean`` that returns NaN (not a warning) for an all-NaN array."""
    a = np.asarray(arr, dtype=float)
    if a.size == 0 or not np.any(np.isfinite(a)):
        return float("nan")
    return float(np.nanmean(a))
