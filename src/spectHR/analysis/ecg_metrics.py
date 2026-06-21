# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/ecg_metrics.py
"""
ECG-derived HRV metrics, everything computed from the inter-beat-interval (IBI)
series that the R-peak detector extracts from the ECG.

All of these share one input series (the cleaned IBIs), so they live together
here; they are grouped below by the four HRV method families, each with its own
literature:

Time-domain (ms)
    ``count``  number of valid IBIs · ``mean`` · ``median`` · ``min`` · ``max``
    ``rmssd``  root-mean-square of successive differences
    ``sdnn``   SD of all IBIs · ``sdsd`` SD of successive differences
    ``nn50``/``pnn50`` · ``nn20``/``pnn20`` successive diffs above 50/20 ms
    ``mean_hr``/``sd_hr`` heart rate (bpm) · ``cvnn``/``cvsd`` coefficients of variation
    ``hrv_ti`` triangular index · ``tinn`` triangular interpolation (ms)

Stationarity (drift diagnostics)
    ``stationarity``   IBI-vs-time linear correlation (monotone drift)
    ``stationarity_z`` reverse-arrangements z-score (Bendat & Piersol); |z|>1.96
                       flags a non-stationary epoch at the 5 % level

Poincaré
    ``sd1`` minor axis · ``sd2`` major axis (Brennan) · ``sd_ratio`` SD1/SD2
    ``ellipse_area`` π·SD1·SD2 (ms²)
    ``csi``/``cvi``/``modified_csi`` cardiac sympathetic / vagal indices (Toichi 1997)

Non-linear
    ``dfa_a1`` short-term · ``dfa_a2`` long-term detrended-fluctuation scaling
               exponent (Peng et al. 1995; α1 over 4-16, α2 over 16-64 beats)

PRSA (phase-rectified signal averaging, Bauer et al. 2006)
    ``dc`` deceleration capacity (parasympathetic) · ``ac`` acceleration capacity

ECG waveform
    ``twave_amplitude`` mean T-wave amplitude per beat (CARSPAN, device-dependent)

Frequency-domain (band powers of the IBI PSD)
    ``band_powers`` group → one ``{band}_power`` column per configured band;
    ``band_rel`` → ``{band}_pct`` · ``band_peak`` → ``{band}_peak_hz``
    ``total_power`` · ``lf_nu``/``hf_nu`` normalised units · ``ln_hf``
    ``lf_hf_ratio`` LF/HF (report descriptively, *not* a clean sympatho-vagal
                    index, Billman 2013)

Every ``@epoch_metric`` here takes a single ``series``-like argument (``.times``,
``.ibi``, ``.labels``), or, on the table path, an
:class:`~spectHR.analysis.epoch_context.EpochContext` that also carries the
workspace ``psd_method`` and a cached PSD the frequency metrics reuse.

Conventions (read before "correcting" anything)
------------------------------------------------
* **Standard deviation uses the population estimator (``ddof=0``, divide by
  N), never the N-1 sample estimator.**  This is deliberate CARSPAN parity:
  every original SD routine divides by the count, not count-1 (``T_EventFile.pas``
  ``GetSampMeanAndStdDev`` → ``SqrSum/((IdxE-IdxB)+1) - Sqr(Mean)``;
  ``T_DataCorrect.pas`` ``SDSum/ValCount``; ``T_AnaFunctions.pas``
  ``DataSum2/NData.Count``).  ``sdnn``, ``sdsd``, ``sd1``/``sd2``, ``sd_hr``,
  ``cvnn``/``cvsd`` (and the BP/respiration SDs in the sibling modules) all
  follow it, so they stay mutually consistent (e.g. ``cvnn == 100·sdnn/mean``).
  The name "Samp" in the Pascal refers to signal *samples*, not the statistical
  sample estimator.  Do not switch any of these to ``ddof=1``.
* **Normalised units** (``lf_nu``/``hf_nu``) use the LF/(LF+HF) form, not the
  Task-Force LF/(TotalPower-VLF) form, so they are robust to whichever bands the
  workspace defines and always sum to 100; ``total_power`` is the sum of the
  configured named bands (excluding the ``FullRange`` umbrella band).
* **DFA** uses forward-only, non-overlapping windows (the remainder beats are
  dropped, not re-segmented from the tail); ``dfa_a1`` and ``dfa_a2`` share the
  one :func:`dfa_fluctuation` implementation so their exponents are comparable.

References
----------
Peng, C.-K., et al. (1995). Quantification of scaling exponents … *Chaos*,
5(1), 82-87.
Bauer, A., et al. (2006). Deceleration capacity of heart rate as a predictor of
mortality after myocardial infarction. *The Lancet*, 367(9523), 1674-1681.
Billman, G. E. (2013). The LF/HF ratio does not accurately measure cardiac
sympatho-vagal balance. *Frontiers in Physiology*, 4, 26.
"""
from __future__ import annotations

import builtins  # this module's `min`/`max` metrics shadow the builtins; qualify when needed

import numpy as np

from spectHR.analysis.epoch_context import EpochContext
from spectHR.analysis.ibi_helpers import ibi_clean_ms, successive_diffs_ms
from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.psd._config import _DEFAULT_PSD_METHOD
from spectHR.analysis.psd._engine import PSDEngine
from spectHR.analysis.registry import epoch_metric, epoch_metric_group


__all__ = [
    # time-domain
    "count", "mean", "median", "min", "max", "rmssd", "sdnn", "sdsd",
    "nn50", "pnn50", "nn20", "pnn20", "mean_hr", "sd_hr", "cvnn", "cvsd",
    "hrv_ti", "tinn",
    # stationarity
    "stationarity", "stationarity_z",
    # Poincaré
    "sd1", "sd2", "sd_ratio", "ellipse_area", "csi", "cvi", "modified_csi",
    # non-linear
    "dfa_fluctuation", "dfa_alpha1", "dfa_a1", "dfa_a2",
    # PRSA
    "dc", "ac",
    # ECG waveform
    "twave_amplitude",
    # frequency-domain
    "fullrange_power", "vlf_power", "lf_power", "hf_power",
    "lf_hf_ratio", "band_powers",
    "total_power", "lf_nu", "hf_nu", "ln_hf", "band_rel", "band_peak",
    "STANDARD_BAND_POWER_COLUMNS", "BAND_POWER_COLUMN_TOOLTIP",
]


# ===========================================================================
# Time-domain, magnitude statistics
# ===========================================================================


@epoch_metric
def count(series) -> float:
    """Total number of valid inter-beat intervals."""
    return float(ibi_clean_ms(series).size)


@epoch_metric
def mean(series) -> float:
    """Mean IBI (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.mean(ibi_ms)) if ibi_ms.size else np.nan


@epoch_metric
def median(series) -> float:
    """Median IBI (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.median(ibi_ms)) if ibi_ms.size else np.nan


@epoch_metric
def min(series) -> float:
    """Minimum IBI (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.min(ibi_ms)) if ibi_ms.size else np.nan


@epoch_metric
def max(series) -> float:
    """Maximum IBI (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.max(ibi_ms)) if ibi_ms.size else np.nan


# ===========================================================================
# Stationarity (drift diagnostics)
# ===========================================================================


@epoch_metric
def stationarity(series) -> float:
    """Correlation of IBI vs. time - drift indicator."""
    ibi_ms = ibi_clean_ms(series)
    if ibi_ms.size <= 2:
        return np.nan
    # Use the same length prefix of times as the cleaned IBI vector.
    t = series.times[: ibi_ms.size]
    return float(np.corrcoef(ibi_ms, t)[0, 1])


@epoch_metric
def stationarity_z(series) -> float:
    """Reverse-arrangements stationarity test statistic (Bendat & Piersol).

    The linear ``stationarity`` correlation above only catches a monotone
    drift in the mean. The reverse-arrangements test is a distribution-free
    test for any trend in the IBI series: it counts, over all pairs i < j,
    how often a later interval exceeds an earlier one and standardises that
    count against its null mean and variance.

    The return value is a z-score: under stationarity it is ~N(0, 1), so
    ``|z| > 1.96`` flags a non-stationary epoch at the 5% level, a warning
    that whole-epoch spectral estimates (which assume stationarity) should
    be interpreted with care. Returns ``NaN`` for epochs shorter than 10
    valid intervals.
    """
    ibi_ms = ibi_clean_ms(series)
    n = ibi_ms.size
    if n < 10:
        return np.nan
    # Count reverse arrangements A = #{(i, j): i < j, ibi[j] > ibi[i]}.
    a = 0
    for i in range(n - 1):
        a += int(np.count_nonzero(ibi_ms[i + 1:] > ibi_ms[i]))
    mean_a = n * (n - 1) / 4.0
    var_a = (2.0 * n ** 3 + 3.0 * n ** 2 - 5.0 * n) / 72.0
    if var_a <= 0:
        return np.nan
    return float((a - mean_a) / np.sqrt(var_a))


# ===========================================================================
# Time-domain, variability
#
# All SDs below (and the CV / Poincaré metrics derived from them) use numpy's
# default population estimator (ddof=0); this is CARSPAN parity, see the module
# docstring "Conventions". Do not switch to ddof=1.
# ===========================================================================


@epoch_metric
def rmssd(series) -> float:
    """Root mean square of successive differences (ms)."""
    d = successive_diffs_ms(series)
    return float(np.sqrt(np.mean(d * d))) if d.size else np.nan


@epoch_metric
def sdnn(series) -> float:
    """Standard deviation of all valid IBIs (ms)."""
    ibi_ms = ibi_clean_ms(series)
    return float(np.std(ibi_ms)) if ibi_ms.size else np.nan


@epoch_metric
def sdsd(series) -> float:
    """Standard deviation of successive differences (ms)."""
    d = successive_diffs_ms(series)
    return float(np.std(d)) if d.size else np.nan


# ===========================================================================
# Poincaré
# ===========================================================================


@epoch_metric
def sd1(series) -> float:
    """Poincaré SD1 (minor axis, ms) = std(dIBI) / sqrt(2)."""
    d = successive_diffs_ms(series)
    return float(np.std(d) / np.sqrt(2.0)) if d.size else np.nan


@epoch_metric
def sd2(series) -> float:
    """Poincaré SD2 (major axis, ms) via Brennan's identity:
    ``SD2² = 2·Var(IBI) − 0.5·Var(dIBI)``."""
    ibi_ms = ibi_clean_ms(series)
    d = successive_diffs_ms(series)
    if ibi_ms.size < 2 or not d.size:
        return np.nan
    val = 2.0 * float(np.var(ibi_ms)) - 0.5 * float(np.var(d))
    return float(np.sqrt(val)) if val > 0.0 else np.nan


@epoch_metric
def sd_ratio(series) -> float:
    """SD1 / SD2 - short-term vs long-term variability balance.

    Guards against degenerate uniform-IBI series whose Brennan residual is
    float-precision noise rather than a meaningful SD2.
    """
    s1 = sd1(series)
    s2 = sd2(series)
    if np.isnan(s1) or np.isnan(s2) or s2 == 0:
        return np.nan
    sdnn_val = sdnn(series)
    if np.isnan(sdnn_val) or sdnn_val < 1e-9:
        return np.nan
    return float(s1 / s2)


@epoch_metric
def ellipse_area(series) -> float:
    """Area of the Poincaré ellipse, ``π · SD1 · SD2`` (ms²)."""
    s1 = sd1(series)
    s2 = sd2(series)
    if np.isnan(s1) or np.isnan(s2):
        return np.nan
    return float(np.pi * s1 * s2)


# ===========================================================================
# Non-linear, detrended fluctuation analysis (DFA-α1)
# ===========================================================================


def dfa_fluctuation(x: np.ndarray, scales: np.ndarray) -> np.ndarray:
    """Detrended fluctuation ``F(n)`` of *x* for each box size in *scales*.

    The series is integrated (cumulative sum of mean-removed values), split
    into non-overlapping windows of length ``n``, locally detrended with a
    linear fit, and the root-mean-square residual taken across all windows.

    Returns ``NaN`` for any scale that does not fit at least two windows in
    the series.
    """
    x = np.asarray(x, dtype=float)
    n_pts = x.size
    y = np.cumsum(x - np.mean(x))

    out = np.full(len(scales), np.nan)
    for k, n in enumerate(scales):
        n = int(n)
        if n < 4 or n > n_pts // 2:
            continue
        n_seg = n_pts // n
        segs = y[: n_seg * n].reshape(n_seg, n)
        t = np.arange(n)
        # Linear local detrend per segment.
        rms = np.empty(n_seg)
        for s in range(n_seg):
            coef = np.polyfit(t, segs[s], 1)
            fit = np.polyval(coef, t)
            rms[s] = np.mean((segs[s] - fit) ** 2)
        out[k] = np.sqrt(np.mean(rms))
    return out


def dfa_alpha1(
    ibi_ms: np.ndarray,
    *,
    scale_min: int = 4,
    scale_max: int = 16,
) -> float:
    """Short-term DFA scaling exponent ``α1`` of an IBI series.

    Parameters
    ----------
    ibi_ms : np.ndarray
        Clean inter-beat intervals in ms (artefacts already removed).
    scale_min, scale_max : int
        Inclusive box-size range in beats (default 4-16, the standard
        short-term window).

    Returns
    -------
    float
        The slope of ``log F(n)`` vs ``log n`` over the configured scales,
        or ``NaN`` when the series is too short (fewer than ``2·scale_max``
        beats) or the fit is degenerate.
    """
    x = np.asarray(ibi_ms, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 2 * int(scale_max):
        return float("nan")

    scales = np.arange(int(scale_min), int(scale_max) + 1)
    f = dfa_fluctuation(x, scales)
    ok = np.isfinite(f) & (f > 0)
    if int(np.sum(ok)) < 3:
        return float("nan")
    coef = np.polyfit(np.log(scales[ok]), np.log(f[ok]), 1)
    return float(coef[0])


@epoch_metric
def dfa_a1(series) -> float:
    """DFA short-term scaling exponent α1 (Peng et al. 1995, box sizes 4-16 beats)."""
    return dfa_alpha1(ibi_clean_ms(series))


# ===========================================================================
# PRSA, phase-rectified signal averaging (deceleration / acceleration capacity)
# ===========================================================================

# Default half-window: 30 beats each side of the anchor (Bauer 2006).
# Overridden at runtime by CardioParameters.PrsaAnalysis.prsa_window in the workspace.
_T_DEFAULT = 30


def _prsa(ibi: np.ndarray, deceleration: bool, T: int = _T_DEFAULT) -> float:
    """Core PRSA computation.

    Parameters
    ----------
    ibi:
        Clean IBI series in milliseconds, length N.
    deceleration:
        ``True`` → DC anchors (IBI[i] > IBI[i-1]);
        ``False`` → AC anchors (IBI[i] < IBI[i-1]).
    T:
        Half-window size in beats (default 30).

    Returns the four-point PRSA capacity in milliseconds, or ``nan`` when
    fewer than 2·T+2 beats are available or no qualifying anchors exist.
    """
    N = len(ibi)
    if N < 2 * T + 2:
        return np.nan

    # Anchor indices: i in [T, N-T) satisfying the monotonicity condition.
    diffs = np.diff(ibi)                          # length N-1
    if deceleration:
        anchors = np.where(diffs[T - 1: N - T - 1] > 0)[0] + T
    else:
        anchors = np.where(diffs[T - 1: N - T - 1] < 0)[0] + T

    if anchors.size == 0:
        return np.nan

    # Stack windows and average.
    windows = np.stack([ibi[a - T: a + T] for a in anchors])  # (n, 2T)
    avg = windows.mean(axis=0)

    # Four-point formula centred on the anchor (index T within avg).
    capacity = (avg[T] + avg[T + 1] - avg[T - 1] - avg[T - 2]) / 4.0
    return float(capacity)


@epoch_metric
def dc(series) -> float:
    """Deceleration Capacity (DC) in ms, PRSA parasympathetic index.

    Anchors on beats where IBI increased (heart decelerated), averages a
    window of ±T beats (T = CardioParameters → PrsaAnalysis → prsa_window,
    default 30), and applies the four-point formula (Bauer et al. 2006).
    Larger positive values indicate stronger parasympathetic modulation.
    Returns NaN when fewer than 2·T+2 clean beats are available or no
    deceleration anchors exist.
    """
    ibi = ibi_clean_ms(series)
    T = int(getattr(series, "prsa_window", _T_DEFAULT))
    return _prsa(ibi, deceleration=True, T=T)


@epoch_metric
def ac(series) -> float:
    """Acceleration Capacity (AC) in ms, PRSA sympatho-vagal index.

    Anchors on beats where IBI decreased (heart accelerated), averages a
    window of ±T beats (T = CardioParameters → PrsaAnalysis → prsa_window,
    default 30), and applies the four-point formula (Bauer et al. 2006).
    AC is negative by convention; more negative values indicate stronger
    acceleration drive.  Returns NaN when fewer than 2·T+2 clean beats are
    available or no acceleration anchors exist.
    """
    ibi = ibi_clean_ms(series)
    T = int(getattr(series, "prsa_window", _T_DEFAULT))
    return _prsa(ibi, deceleration=False, T=T)


# ===========================================================================
# ECG waveform metrics (require the continuous ECG channel via EpochContext)
# ===========================================================================


@epoch_metric
def twave_amplitude(ctx) -> float:
    """Mean T-wave amplitude per beat (ECG channel), in ECG signal units.

    Faithful port of CARSPAN ``CalcDataColECGTWAVE`` / ``GetBaseLineValue``
    (``T_EventFile.pas``).  For each R-peak:

    * the **T-wave peak** is the maximum ECG sample in ``[R+150 ms, R+450 ms]``;
    * the **baseline** is the mean ECG over a 20 ms PR-segment window
      ``[Q-50 ms, Q-30 ms]``, where ``Q`` (QRS onset) is found by walking back
      from the R-peak to the first local minimum;
    * the amplitude is ``T peak - baseline``.

    The values are averaged across beats.  Because the baseline is taken on the
    isoelectric PR segment (not on the QRS upstroke), an upright T-wave gives a
    positive amplitude and only a genuinely **inverted** T-wave goes negative.

    Returns NaN when no ECG channel is available (``ctx.ecg_ts is None``) or no
    beat yields a usable window.
    """
    if not isinstance(ctx, EpochContext) or ctx.ecg_ts is None:
        return np.nan
    ecg_t = np.asarray(ctx.ecg_ts.times,  dtype=float)
    ecg_v = np.asarray(ctx.ecg_ts.values, dtype=float)
    n = ecg_t.size
    if n < 2:
        return np.nan
    rpeaks = np.asarray(ctx.rpeak_times, dtype=float)
    if rpeaks.size < 1:
        return np.nan

    # Nearest ECG sample to each R-peak time (vectorised).
    ri = np.clip(np.searchsorted(ecg_t, rpeaks), 0, n - 1)
    left = np.clip(ri - 1, 0, n - 1)
    take_left = (ri > 0) & (np.abs(ecg_t[left] - rpeaks) <= np.abs(ecg_t[ri] - rpeaks))
    ri = np.where(take_left, left, ri)

    # Bound the Q-point walk-back to the QRS region so a flat segment can never
    # turn the per-beat search into an O(n) scan.
    dt = float(np.median(np.diff(ecg_t)))
    max_back = builtins.max(1, int(round(0.20 / dt))) if dt > 0 else 1
    t0 = float(ecg_t[0])

    amps: list[float] = []
    for k in range(rpeaks.size):
        r_t = float(rpeaks[k])

        # Q-point (QRS onset): walk back to the first local minimum, as CARSPAN.
        q = int(ri[k])
        q_stop = builtins.max(1, q - max_back)
        while q > q_stop and ecg_v[q] >= ecg_v[q - 1]:
            q -= 1
        q_t = ecg_t[q]

        # Baseline: mean ECG over the PR segment [Q-50 ms, Q-30 ms].  The signal
        # is sorted in time, so slice it with searchsorted (O(log n)) rather than
        # masking the whole array per beat.  When the window runs off the start,
        # CARSPAN falls back to the first sample.
        b0 = int(np.searchsorted(ecg_t, q_t - 0.05, "left"))
        b1 = int(np.searchsorted(ecg_t, q_t - 0.03, "right"))
        if b1 > b0:
            baseline = float(ecg_v[b0:b1].mean())
        elif q_t - 0.05 < t0:
            baseline = float(ecg_v[0])
        else:
            continue

        # T-wave peak: max in the fixed [R+150 ms, R+450 ms] window (CARSPAN does
        # not cap this at the next R-peak).
        s0 = int(np.searchsorted(ecg_t, r_t + 0.15, "left"))
        s1 = int(np.searchsorted(ecg_t, r_t + 0.45, "right"))
        if s1 <= s0:
            continue
        amps.append(float(ecg_v[s0:s1].max()) - baseline)

    return float(np.mean(amps)) if amps else np.nan


# ===========================================================================
# Frequency-domain, band powers of the IBI PSD
#
# These are **dual-mode**: called directly with a bare series (and optionally an
# explicit ``psd_method``) they integrate the band on a freshly-computed PSD;
# called via the table they receive an EpochContext, read its workspace
# ``psd_method`` and reuse its cached PSD so all bands share one computation.
# ===========================================================================

# Previously the four standard bands were registered as individual
# @epoch_metric functions and listed here so the group metric could avoid
# double-emitting them.  All band powers now flow through band_powers (the
# @epoch_metric_group), so this set is empty.  Kept for import compatibility.
STANDARD_BAND_POWER_COLUMNS: frozenset[str] = frozenset()

# Suffix → tooltip for dynamically-named band-power columns.
# The Results widget uses this to annotate {band}_power column headers whose
# names depend on the workspace band configuration and are not known at import.
BAND_POWER_COLUMN_TOOLTIP: dict[str, str] = {
    "_power": (
        "Spectral power integrated over this frequency band (rectangular "
        "summation on the display-grid spectrum). Units are mMI² by default "
        "(dimensionless, normalised by squared mean heart rate) or ms² when "
        "the Welch units setting is switched. Computed by the active PSD "
        "method (CARSPAN, Welch, or Lomb-Scargle)."
    ),
}


def _resolve_method(series, psd_method):
    """Pick the PSD method for *series*.

    Resolution order:

    1. An explicit *psd_method* argument always wins.
    2. An :class:`EpochContext` carries ``psd_method`` (possibly ``None``); the
       table path uses it, and a configured ``None`` means "no band powers"
       (the caller returns ``NaN``).
    3. A bare ``Events`` series → fall back to the default method,
       matching the historical direct-call behaviour.

    Returns the method, or ``None`` to signal "configured but no method →
    yield NaN".
    """
    if psd_method is not None:
        return psd_method
    if isinstance(series, EpochContext):
        return series.psd_method             # may be None → caller yields NaN
    return _DEFAULT_PSD_METHOD               # bare series, standalone call


def _band_power(series, band_name: str, psd_method=None) -> float:
    """Integrate one named band using *psd_method* (or the default if None).

    Internal helper shared by the band-power metrics and any external callers
    that want a single-band scalar.  When *series* is an :class:`EpochContext`
    its cached :attr:`~EpochContext.psd` is reused; otherwise a PSD is computed
    on the spot.  Raises ``KeyError`` when the band name is absent from the
    method (mirroring the historical contract).
    """
    method = psd_method if psd_method is not None else _DEFAULT_PSD_METHOD
    if band_name not in method.bands:
        raise KeyError(f"Unknown band '{band_name}'.")
    band = method.bands[band_name]
    psd_res = getattr(series, "psd", None)   # cached on EpochContext, else None
    if psd_res is None:
        psd_res = PSDEngine(series).for_band_power(method)
    return float(
        band_power_rectangular(psd_res.freqs, psd_res.power, band.low, band.high)
    )


def _named_band_power(series, band_name: str, psd_method=None) -> float:
    """``_band_power`` wrapped to return ``NaN`` instead of raising/erroring."""
    try:
        method = _resolve_method(series, psd_method)
        if method is None:                   # table call without a method
            return np.nan
        if band_name not in method.bands:    # band renamed / absent
            return np.nan
        return _band_power(series, band_name, method)
    except (KeyError, AttributeError, ValueError):
        return np.nan


def fullrange_power(series, psd_method=None) -> float:
    """Power across the FullRange band (direct-call helper; not an epoch_metric)."""
    return _named_band_power(series, "FullRange", psd_method)


def vlf_power(series, psd_method=None) -> float:
    """Power in the VLF band (direct-call helper; not an epoch_metric)."""
    return _named_band_power(series, "VLF", psd_method)


def lf_power(series, psd_method=None) -> float:
    """Power in the LF band (direct-call helper; not an epoch_metric)."""
    return _named_band_power(series, "LF", psd_method)


def hf_power(series, psd_method=None) -> float:
    """Power in the HF band (direct-call helper; not an epoch_metric)."""
    return _named_band_power(series, "HF", psd_method)


@epoch_metric
def lf_hf_ratio(series, psd_method=None) -> float:
    """LF/HF ratio. Historically read as sympatho-vagal balance, but that
    interpretation is not supported by current evidence (Billman 2013;
    Reyes del Paso et al. 2013), LF reflects mixed autonomic influences,
    not a clean sympathetic index. Report the ratio descriptively."""
    try:
        method = _resolve_method(series, psd_method)
        if method is None:
            return np.nan
        if "LF" not in method.bands or "HF" not in method.bands:
            return np.nan
        lf = _band_power(series, "LF", method)
        hf = _band_power(series, "HF", method)
        if not np.isfinite(lf) or not np.isfinite(hf) or hf == 0.0:
            return np.nan
        return float(lf / hf)
    except (KeyError, AttributeError, ValueError):
        return np.nan


@epoch_metric_group
def band_powers(ctx) -> dict[str, float]:
    """``{band}_power`` column for every configured frequency band.

    Emits one ``{band_name.lower()}_power`` column per band in the configured
    PSD method.  Because all band powers flow through this group metric, the
    column set is always data-driven: renaming a band in the workspace
    changes the column name, and adding new bands adds new columns
    automatically.  No band names are hard-coded.

    Returns an empty dict when no PSD method is configured or the PSD could
    not be computed.  Group metrics are always called with an
    :class:`~spectHR.analysis.epoch_context.EpochContext`.
    """
    out: dict[str, float] = {}
    method = getattr(ctx, "psd_method", None)
    psd_res = getattr(ctx, "psd", None)
    if method is None or psd_res is None:
        return out
    log_bp = bool(getattr(ctx, "log_band_power", False))
    for band_name, band_spec in method.bands.items():
        col = f"{band_name.lower()}_power"
        try:
            val = float(band_power_rectangular(
                psd_res.freqs, psd_res.power, band_spec.low, band_spec.high,
            ))
            if log_bp and val > 0:
                val = float(np.log(val))
            out[col] = val
        except Exception:
            pass   # leave absent → NaN in the matrix
    return out


# ===========================================================================
# Frequency-domain completeness (PLAN.md phase 1a)
#
# Normalised units, total power, ln(HF) and per-band % / peak frequency, all
# read off the same cached PSD as band_powers / lf_hf_ratio.
# ===========================================================================


def _total_power(series, method) -> float:
    """Sum of every configured non-FullRange band power (the conventional total)."""
    total, found = 0.0, False
    for name in method.bands:
        if name == "FullRange":
            continue
        p = _band_power(series, name, method)
        if np.isfinite(p):
            total += p
            found = True
    return total if found else float("nan")


@epoch_metric
def total_power(series, psd_method=None) -> float:
    """Total spectral power: sum of all configured bands except FullRange (mMI² by default)."""
    try:
        method = _resolve_method(series, psd_method)
        if method is None:
            return np.nan
        return _total_power(series, method)
    except (KeyError, AttributeError, ValueError):
        return np.nan


def _lf_hf(series, psd_method):
    """``(method, LF, HF)`` or ``None`` when LF/HF cannot be evaluated."""
    method = _resolve_method(series, psd_method)
    if method is None or "LF" not in method.bands or "HF" not in method.bands:
        return None
    return method, _band_power(series, "LF", method), _band_power(series, "HF", method)


@epoch_metric
def lf_nu(series, psd_method=None) -> float:
    """LF power in normalised units: 100 * LF / (LF + HF)."""
    try:
        got = _lf_hf(series, psd_method)
        if got is None:
            return np.nan
        _, lf, hf = got
        s = lf + hf
        return float(100.0 * lf / s) if np.isfinite(s) and s > 0 else np.nan
    except (KeyError, AttributeError, ValueError):
        return np.nan


@epoch_metric
def hf_nu(series, psd_method=None) -> float:
    """HF power in normalised units: 100 * HF / (LF + HF)."""
    try:
        got = _lf_hf(series, psd_method)
        if got is None:
            return np.nan
        _, lf, hf = got
        s = lf + hf
        return float(100.0 * hf / s) if np.isfinite(s) and s > 0 else np.nan
    except (KeyError, AttributeError, ValueError):
        return np.nan


@epoch_metric
def ln_hf(series, psd_method=None) -> float:
    """Natural log of HF power, ln(HF)."""
    try:
        method = _resolve_method(series, psd_method)
        if method is None or "HF" not in method.bands:
            return np.nan
        hf = _band_power(series, "HF", method)
        return float(np.log(hf)) if np.isfinite(hf) and hf > 0 else np.nan
    except (KeyError, AttributeError, ValueError):
        return np.nan


@epoch_metric_group
def band_rel(ctx) -> dict[str, float]:
    """``{band}_pct``: each configured band's % of the total (non-FullRange) power."""
    out: dict[str, float] = {}
    method = getattr(ctx, "psd_method", None)
    psd_res = getattr(ctx, "psd", None)
    if method is None or psd_res is None:
        return out
    powers: dict[str, float] = {}
    for name, spec in method.bands.items():
        if name == "FullRange":
            continue
        try:
            powers[name] = float(band_power_rectangular(
                psd_res.freqs, psd_res.power, spec.low, spec.high))
        except Exception:
            pass
    total = sum(p for p in powers.values() if np.isfinite(p))
    if total <= 0:
        return out
    for name, p in powers.items():
        if np.isfinite(p):
            out[f"{name.lower()}_pct"] = float(100.0 * p / total)
    return out


@epoch_metric_group
def band_peak(ctx) -> dict[str, float]:
    """``{band}_peak_hz``: frequency of the maximum PSD value inside each band."""
    out: dict[str, float] = {}
    method = getattr(ctx, "psd_method", None)
    psd_res = getattr(ctx, "psd", None)
    if method is None or psd_res is None:
        return out
    freqs = np.asarray(psd_res.freqs, dtype=float)
    power = np.asarray(psd_res.power, dtype=float)
    for name, spec in method.bands.items():
        if name == "FullRange":
            continue
        mask = (freqs >= spec.low) & (freqs <= spec.high)
        if mask.any() and np.isfinite(power[mask]).any():
            out[f"{name.lower()}_peak_hz"] = float(
                freqs[mask][int(np.nanargmax(power[mask]))])
    return out


# ===========================================================================
# Time-domain staples (PLAN.md phase 1b)
# ===========================================================================


def _nn_pnn(series, threshold_ms: float):
    """``(count, percent)`` of successive |ΔIBI| above *threshold_ms*."""
    d = np.abs(successive_diffs_ms(series))
    if d.size == 0:
        return float("nan"), float("nan")
    nn = int(np.count_nonzero(d > threshold_ms))
    return float(nn), float(100.0 * nn / d.size)


@epoch_metric
def nn50(series) -> float:
    """Number of successive IBI differences greater than 50 ms."""
    return _nn_pnn(series, 50.0)[0]


@epoch_metric
def pnn50(series) -> float:
    """Percentage of successive IBI differences greater than 50 ms."""
    return _nn_pnn(series, 50.0)[1]


@epoch_metric
def nn20(series) -> float:
    """Number of successive IBI differences greater than 20 ms."""
    return _nn_pnn(series, 20.0)[0]


@epoch_metric
def pnn20(series) -> float:
    """Percentage of successive IBI differences greater than 20 ms."""
    return _nn_pnn(series, 20.0)[1]


@epoch_metric
def mean_hr(series) -> float:
    """Mean heart rate in bpm = 60000 / mean(IBI in ms)."""
    ibi = ibi_clean_ms(series)
    if ibi.size == 0:
        return np.nan
    m = float(np.mean(ibi))
    return float(60000.0 / m) if m > 0 else np.nan


@epoch_metric
def sd_hr(series) -> float:
    """SD of the per-beat instantaneous heart rate (bpm)."""
    ibi = ibi_clean_ms(series)
    ibi = ibi[ibi > 0]
    return float(np.std(60000.0 / ibi)) if ibi.size >= 2 else np.nan


@epoch_metric
def cvnn(series) -> float:
    """Coefficient of variation of the IBIs: 100 * SDNN / mean (percent)."""
    ibi = ibi_clean_ms(series)
    if ibi.size < 2:
        return np.nan
    m = float(np.mean(ibi))
    return float(100.0 * np.std(ibi) / m) if m > 0 else np.nan


@epoch_metric
def cvsd(series) -> float:
    """Coefficient of variation of successive differences: 100 * SDSD / mean (percent)."""
    ibi = ibi_clean_ms(series)
    d = successive_diffs_ms(series)
    if ibi.size < 2 or d.size == 0:
        return np.nan
    m = float(np.mean(ibi))
    return float(100.0 * np.std(d) / m) if m > 0 else np.nan


_TI_BIN_MS = 1000.0 / 128.0   # 7.8125 ms, the standard HRV histogram bin


def _ibi_histogram(ibi_ms: np.ndarray):
    """``(counts, centres)`` of the IBI histogram on the 1/128 s grid, or None."""
    if ibi_ms.size < 2:
        return None
    lo, hi = float(np.min(ibi_ms)), float(np.max(ibi_ms))
    if hi <= lo:
        return None
    edges = np.arange(lo, hi + _TI_BIN_MS, _TI_BIN_MS)
    if edges.size < 2:
        return None
    counts, edges = np.histogram(ibi_ms, bins=edges)
    centres = 0.5 * (edges[:-1] + edges[1:])
    return counts.astype(float), centres


@epoch_metric
def hrv_ti(series) -> float:
    """HRV triangular index: total IBIs / height of the modal histogram bin (1/128 s bins)."""
    h = _ibi_histogram(ibi_clean_ms(series))
    if h is None:
        return np.nan
    counts, _ = h
    peak = float(counts.max()) if counts.size else 0.0
    return float(counts.sum() / peak) if peak > 0 else np.nan


@epoch_metric
def tinn(series) -> float:
    """Triangular Interpolation of the NN histogram (ms): base width of the
    least-squares triangle fitted to the IBI histogram (Task Force 1996)."""
    h = _ibi_histogram(ibi_clean_ms(series))
    if h is None:
        return np.nan
    counts, centres = h
    x = int(np.argmax(counts))
    y = float(counts[x])
    if y <= 0:
        return np.nan
    last = counts.size - 1

    # Left side: triangle rises 0 -> y from bin N (<= x) up to the mode.
    left = np.arange(0, x + 1)
    best_n, best_err = x, np.inf
    for n_lo in range(0, x + 1):
        q = np.zeros(x + 1)
        if x > n_lo:
            on = left >= n_lo
            q[on] = y * (left[on] - n_lo) / (x - n_lo)
        else:
            q[x] = y
        err = float(np.sum((counts[: x + 1] - q) ** 2))
        if err < best_err:
            best_err, best_n = err, n_lo

    # Right side: triangle falls y -> 0 from the mode down to bin M (>= x).
    right = np.arange(x, last + 1)
    best_m, best_err = x, np.inf
    for n_hi in range(x, last + 1):
        q = np.zeros(last - x + 1)
        if n_hi > x:
            on = right <= n_hi
            q[on] = y * (n_hi - right[on]) / (n_hi - x)
        else:
            q[0] = y
        err = float(np.sum((counts[x:] - q) ** 2))
        if err < best_err:
            best_err, best_m = err, n_hi

    return float(centres[best_m] - centres[best_n])


# ===========================================================================
# Poincaré complements (PLAN.md phase 1c): Toichi (1997) CSI / CVI
# ===========================================================================


@epoch_metric
def csi(series) -> float:
    """Cardiac Sympathetic Index L/T (T = 4·SD1, L = 4·SD2; Toichi 1997)."""
    s1, s2 = sd1(series), sd2(series)
    if np.isnan(s1) or np.isnan(s2) or s1 <= 0:
        return np.nan
    return float(s2 / s1)            # (4·SD2) / (4·SD1)


@epoch_metric
def cvi(series) -> float:
    """Cardiac Vagal Index log10(L·T) = log10(16·SD1·SD2) (Toichi 1997)."""
    s1, s2 = sd1(series), sd2(series)
    if np.isnan(s1) or np.isnan(s2) or s1 <= 0 or s2 <= 0:
        return np.nan
    return float(np.log10(16.0 * s1 * s2))


@epoch_metric
def modified_csi(series) -> float:
    """Modified Cardiac Sympathetic Index L²/T (Toichi 1997)."""
    s1, s2 = sd1(series), sd2(series)
    if np.isnan(s1) or np.isnan(s2) or s1 <= 0:
        return np.nan
    t, ell = 4.0 * s1, 4.0 * s2
    return float(ell * ell / t)


# ===========================================================================
# Non-linear: long-term DFA (PLAN.md phase 1d)
# ===========================================================================


@epoch_metric
def dfa_a2(series) -> float:
    """DFA long-term scaling exponent α2 (Peng et al. 1995, box sizes 16-64 beats)."""
    return dfa_alpha1(ibi_clean_ms(series), scale_min=16, scale_max=64)
