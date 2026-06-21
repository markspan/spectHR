# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/respiration_metrics.py
"""
Respiration-series metrics: breathing-frequency context, respiratory volume,
and respiratory sinus arrhythmia (RSA).

Everything here derives from the respiration channel (or its INH/EXH phase
segmentation), on its own or coupled to the R-peaks, so all respiration-
related parameters live in one module rather than alongside blood pressure.

Registered epoch metrics (one CSV/HDF5 column each, the function name)
---------------------------------------------------------------------
Breathing-frequency context (Grossman & Taylor, 2007)
* ``resp_freq``, mean breathing frequency in Hz.
* ``resp_rate_bpm``, the same rate in breaths per minute (60 * resp_freq).
* ``rrv``, respiration-rate variability: SD of the per-cycle breath durations (s).
* ``hf_resp_in_band``, 1.0/0.0 flag: is the mean breathing frequency inside
  the configured HF band?  A 0.0 warns that the epoch's HF power may not index
  RSA at all (NaN when undeterminable).

Respiratory volume (CARSPAN ``CalcDataColRESMVO/RESSVO``), gated on the R-peaks
* ``resp_mvo``, mean respiratory volume per cardiac interval ``[R_i, R_{i+1}]``
  (CARSPAN's ``RESPVO`` is an exact duplicate of ``RESMVO``; only MVO is exposed).
* ``resp_svo``, sample respiratory volume: the mean over the ``ResSamples // 2``
  samples ending at each R-peak.

Respiratory sinus arrhythmia (Grossman et al., 1990 peak-to-valley)
* ``rsa``, mean over *valid* breath cycles (positive peak-to-valley, ms).
* ``rsa0``, RSA with every invalid breath (negative or undetectable) counted as
  zero over the total breath count, reducing over-estimation bias (VU-DAMS RSA0).

HF-HRV context, why ``resp_freq`` / ``hf_resp_in_band`` matter
---------------------------------------------------------------
HF-HRV amplitude depends not only on vagal tone but also on the rate and depth
of breathing (Grossman & Taylor, 2007): the same vagal drive produces a smaller
HF peak when breathing is fast or shallow, and a breathing frequency that drifts
*out of* the HF band (0.15-0.40 Hz, i.e. 9-24 breaths/min) breaks the assumption
that HF power indexes RSA at all.  The actual statistical *correction* of HF for
respiration is left to the analyst's statistics package (R / JASP); these two
columns are the inputs that make that correction possible.

References
----------
Grossman, P., van Beek, J., & Wientjes, C. (1990). A comparison of three
quantification methods for estimation of respiratory sinus arrhythmia.
*Psychophysiology*, 27(6), 702-714.

Grossman, P., & Taylor, E. W. (2007). Toward understanding respiratory sinus
arrhythmia: relations to cardiac vagal tone, evolution and biobehavioral
functions. *Biological Psychology*, 74(2), 263-285.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from spectHR.analysis._beat_sampling import nanmean, rpeak_sample_indices
from spectHR.analysis.registry import epoch_metric
from spectHR.Tools.RespirationSegmentation import mean_breath_frequency_hz


__all__ = [
    "resp_freq",
    "resp_rate_bpm",
    "rrv",
    "hf_resp_in_band",
    "resp_mvo",
    "resp_svo",
    "rsa",
    "rsa0",
    "resp_beat_parameters",
    "resp_epoch_metrics",
    "grossman_rsa_per_breath",
]

# Columns whose float value (1.0 / 0.0) should be displayed as True / False.
BOOLEAN_METRIC_COLUMNS: frozenset[str] = frozenset({"hf_resp_in_band"})

# CARSPAN default DataCol.ResSamples (TEventFile sets ResSamples := 10).
_DEFAULT_RES_SAMPLES = 10


# ---------------------------------------------------------------------------
# Breathing-frequency context (Grossman & Taylor 2007)
# ---------------------------------------------------------------------------


def _mean_breath_hz(ctx):
    """Mean breathing frequency (Hz) for the epoch, or None."""
    phases = getattr(ctx, "rsp_phases", None)
    if phases is None or len(phases) < 2:
        return None
    try:
        return mean_breath_frequency_hz(phases)
    except Exception:
        return None


@epoch_metric
def resp_freq(ctx) -> float:
    """Mean breathing frequency in Hz (blank when no respiration channel)."""
    f = _mean_breath_hz(ctx)
    return float(f) if f is not None else float("nan")


@epoch_metric
def resp_rate_bpm(ctx) -> float:
    """Mean breathing rate in breaths per minute (60 * resp_freq)."""
    f = _mean_breath_hz(ctx)
    return float(60.0 * f) if f is not None else float("nan")


@epoch_metric
def rrv(ctx) -> float:
    """Respiration-rate variability: SD of the per-cycle breath durations (s).

    Cycle durations mirror :func:`resp_freq` (each phase paired with its
    successor, ``ends[1:] - starts[:-1]``).  NaN with fewer than two cycles.
    Population SD (``ddof=0``), as in :mod:`spectHR.analysis.ecg_metrics`.
    """
    phases = getattr(ctx, "rsp_phases", None)
    if phases is None:
        return float("nan")
    try:
        starts = np.asarray(phases.starts, dtype=float)
        ends = np.asarray(phases.ends, dtype=float)
    except Exception:
        return float("nan")
    if starts.size < 3 or ends.size < 3:
        return float("nan")
    periods = ends[1:] - starts[:-1]
    periods = periods[periods > 0]
    return float(np.std(periods)) if periods.size >= 2 else float("nan")


@epoch_metric
def hf_resp_in_band(ctx) -> float:
    """True if mean breathing frequency lies inside the HF band, else False (Grossman & Taylor 2007). A False value flags that the epoch's HF power may not reflect RSA."""
    f = _mean_breath_hz(ctx)
    if f is None:
        return float("nan")
    method = getattr(ctx, "psd_method", None)
    bands = getattr(method, "bands", None) if method is not None else None
    if not bands or "HF" not in bands:
        return float("nan")
    hf = bands["HF"]
    return 1.0 if (hf.low <= f <= hf.high) else 0.0


# ---------------------------------------------------------------------------
# Respiratory volume beat-by-beat parameters (CARSPAN RESMVO / RESSVO)
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

    idx = rpeak_sample_indices(rsp_times, rpeak_times)

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
        "resp_mvo": nanmean(beats["mvo"]),
        "resp_svo": nanmean(beats["svo"]),
    }


def _resp_metric(ctx, key: str) -> float:
    beats = getattr(ctx, "resp_beats", None)
    if not beats:
        return float("nan")
    return nanmean(beats[key])


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

# VU-DAMS default thresholds for the two automatic rejection guards.
# Both are expressed as fractional deviations (0.50 = 50 %).
# Source: VU-DAMS manual v2 / DAMS 5.0, Appendix A.
_STRICT_IBI_DEV: float = 0.50   # max consecutive-IBI deviation (code -5)
_STRICT_RATE_DEV: float = 0.50  # max respiration-rate deviation from 20-breath running avg (code -6)


def grossman_rsa_per_breath(
    rpeak_times: np.ndarray,
    rpeak_labels: np.ndarray,
    rsp_phases,
    *,
    lag_s: float = _DEFAULT_RSA_LAG_S,
    max_ibi_deviation: Optional[float] = None,
    max_rate_deviation: Optional[float] = None,
) -> np.ndarray:
    """Per-breath RSA in ms using the Grossman et al. (1990) peak-to-valley method.

    For each INH→EXH breath cycle:

    * **Shortest IBI**, the minimum IBI within ``[INH_start, INH_end + lag_s]``
      that sits on an *accelerating* slope (IBI shorter than the preceding one).
    * **Longest IBI**, the maximum IBI within ``[EXH_start, EXH_end + lag_s]``
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
    max_ibi_deviation : float or None
        VU-DAMS code -5 guard (Automatic IBI Artefact Detection, default 50 %).
        An IBI[j] is **excluded from the shortest/longest candidate pool** (but
        does not by itself reject the whole breath) when it deviates from the
        preceding IBI by more than this fraction:
        ``|IBI[j] / IBI[j-1] - 1| > max_ibi_deviation``.
        ``None`` disables the guard (default, legacy behaviour).
    max_rate_deviation : float or None
        VU-DAMS code -6 guard (Automatic Respiration Rate Artefact Detection,
        default 50 %).  A **whole breath is rejected** (→ NaN) when its
        respiration rate deviates from the running average of the 20 preceding
        breaths by more than this fraction:
        ``|avg_dur / breath_dur - 1| > max_rate_deviation``.
        The first breath is never rejected (no preceding average available).
        ``None`` disables the guard (default, legacy behaviour).

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

    # Code -5: pre-compute which IBIs are artefact-free.
    # An IBI is an artefact when it deviates more than max_ibi_deviation from
    # the preceding IBI.  Artefact IBIs are excluded from the shortest/longest
    # candidate pools but do NOT by themselves reject the whole breath.
    valid_ibi = np.ones(ibi_ms.size, dtype=bool)
    if max_ibi_deviation is not None:
        for j in range(1, ibi_ms.size):
            if ibi_ms[j - 1] > 0:
                dev = abs(ibi_ms[j] / ibi_ms[j - 1] - 1.0)
                if dev > max_ibi_deviation:
                    valid_ibi[j] = False

    # Collect all INH→EXH pairs so we can compute the running average.
    breath_pairs: list[tuple[float, float, float, float]] = []
    for i in range(len(starts) - 1):
        if labels[i] == "INH" and labels[i + 1] == "EXH":
            breath_pairs.append((
                float(starts[i]), float(ends[i]),
                float(starts[i + 1]), float(ends[i + 1]),
            ))

    results: list[float] = []

    for bi, (inh_s, inh_e, exh_s, exh_e) in enumerate(breath_pairs):
        breath_dur = exh_e - inh_s

        # Code -6: irregular respiration rate.
        # Reject if rate deviates > max_rate_deviation from the running average
        # of the 20 preceding breath durations.  Skip for the very first breath
        # (no preceding average available).
        if max_rate_deviation is not None and bi > 0 and breath_dur > 0:
            window = breath_pairs[max(0, bi - 20): bi]
            avg_dur = float(np.mean([p[3] - p[0] for p in window]))
            if avg_dur > 0 and abs(avg_dur / breath_dur - 1.0) > max_rate_deviation:
                results.append(np.nan)
                continue

        wi_lo, wi_hi = inh_s, inh_e + lag_s
        we_lo, we_hi = exh_s, exh_e + lag_s

        # Apply the IBI artefact mask (code -5) when building candidate sets.
        inh_idx = np.where(
            (clean_t[:-1] >= wi_lo) & (clean_t[:-1] <= wi_hi) & valid_ibi
        )[0]
        exh_idx = np.where(
            (clean_t[:-1] >= we_lo) & (clean_t[:-1] <= we_hi) & valid_ibi
        )[0]

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
    # RSA0 (VU-DAMS): every *invalid* breath, negative RSA OR an undetectable
    # shortest/longest IBI, is **included** in the mean with value zero, i.e.
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
