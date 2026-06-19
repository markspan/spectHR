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

Stationarity (drift diagnostics)
    ``stationarity``   IBI-vs-time linear correlation (monotone drift)
    ``stationarity_z`` reverse-arrangements z-score (Bendat & Piersol); |z|>1.96
                       flags a non-stationary epoch at the 5 % level

Poincaré
    ``sd1`` minor axis · ``sd2`` major axis (Brennan) · ``sd_ratio`` SD1/SD2
    ``ellipse_area`` π·SD1·SD2 (ms²)

Non-linear
    ``dfa_a1`` short-term detrended-fluctuation scaling exponent α1
               (Peng et al. 1995, box sizes 4-16 beats)

PRSA (phase-rectified signal averaging, Bauer et al. 2006)
    ``dc`` deceleration capacity (parasympathetic) · ``ac`` acceleration capacity

Frequency-domain (band powers of the IBI PSD)
    ``band_powers`` group → one ``{band}_power`` column per configured band
    ``lf_hf_ratio`` LF/HF (report descriptively, *not* a clean sympatho-vagal
                    index, Billman 2013)

Every ``@epoch_metric`` here takes a single ``series``-like argument (``.times``,
``.ibi``, ``.labels``), or, on the table path, an
:class:`~spectHR.analysis.epoch_context.EpochContext` that also carries the
workspace ``psd_method`` and a cached PSD the frequency metrics reuse.

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
    "nn_stats",
    # stationarity
    "stationarity", "stationarity_z",
    # Poincaré
    "sd1", "sd2", "sd_ratio", "ellipse_area",
    # non-linear
    "dfa_fluctuation", "dfa_alpha1", "dfa_a1", "dfa_a2",
    "sample_entropy",
    # PRSA
    "dc", "ac",
    # ECG waveform
    "twave_amplitude",
    # frequency-domain
    "fullrange_power", "vlf_power", "lf_power", "hf_power",
    "lf_hf_ratio", "band_powers", "band_freq_stats",
    "STANDARD_BAND_POWER_COLUMNS", "BAND_POWER_COLUMN_TOOLTIP",
    "NN_STATS_COLUMN_TOOLTIPS", "BAND_FREQ_STATS_COLUMN_TOOLTIPS",
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


@epoch_metric_group
def nn_stats(series) -> dict[str, float]:
    """NN50/pNN50 and NN20/pNN20 threshold-crossing counts.

    ``nn50`` / ``nn20`` are counts of successive differences exceeding 50 ms
    or 20 ms respectively; ``pnn50`` / ``pnn20`` are the corresponding
    percentages of the total number of differences.  Part of the standard
    Task Force (1996) time-domain HRV parameters.
    """
    d = np.abs(successive_diffs_ms(series))
    n = d.size
    if n == 0:
        return {"nn50": np.nan, "pnn50": np.nan, "nn20": np.nan, "pnn20": np.nan}
    nn50 = int(np.sum(d > 50.0))
    nn20 = int(np.sum(d > 20.0))
    return {
        "nn50":  float(nn50),
        "pnn50": float(nn50 / n * 100.0),
        "nn20":  float(nn20),
        "pnn20": float(nn20 / n * 100.0),
    }


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


@epoch_metric
def dfa_a2(series) -> float:
    """DFA long-term scaling exponent α2 (box sizes 17-64 beats).

    The long-term counterpart to ``dfa_a1``: computed over the same
    detrended-fluctuation algorithm but at box sizes 17–64 beats.  Healthy
    young adults typically show α2 ≈ 1.0 at rest; the long-term exponent is
    more sensitive to slow autonomic modulation than α1.  Requires at least
    128 clean beats, otherwise blank.
    """
    return dfa_alpha1(ibi_clean_ms(series), scale_min=17, scale_max=64)


def _sample_entropy(x: np.ndarray, m: int = 2, r_factor: float = 0.2) -> float:
    """SampEn via Richman & Moorman (2000). Pure NumPy, fully vectorised.

    Counts template matches of length *m* (B) and *m+1* (A) using the
    Chebyshev (max-norm) distance with tolerance ``r = r_factor × σ``.
    Returns ``nan`` when *x* is shorter than 10 points or constant,
    ``inf`` when no length-*m* template matches extend to length *m+1*
    (maximum complexity, extremely rare in physiological series).
    """
    n = x.size
    if n < 10:
        return float("nan")
    r = r_factor * float(np.std(x, ddof=0))
    if r == 0.0:
        return 0.0

    # Build overlapping template windows via stride tricks.
    T  = np.lib.stride_tricks.sliding_window_view(x, m + 1)  # (n-m, m+1)
    Tm = T[:, :m]                                              # (n-m, m)

    # Pairwise Chebyshev distances — O(N²) but fully vectorised.
    # For typical HRV epoch lengths (50–500 beats) the arrays are small.
    B_dist = np.max(np.abs(Tm[:, None] - Tm[None, :]), axis=2)
    A_dist = np.max(np.abs(T[:, None]  - T[None, :]),  axis=2)

    nm = B_dist.shape[0]
    B = int(np.sum(B_dist <= r)) - nm   # exclude self-matches on diagonal
    A = int(np.sum(A_dist <= r)) - nm

    if B <= 0:
        return float("nan")
    if A <= 0:
        return float("inf")
    return float(-np.log(A / B))


@epoch_metric
def sample_entropy(series) -> float:
    """Sample Entropy (SampEn, m=2, r=0.2·σ) of the cleaned IBI series.

    A template-matching complexity measure (Richman & Moorman, 2000):
    lower values indicate higher regularity (more self-similar patterns);
    higher values indicate greater complexity.  The embedding dimension is
    m=2 and the tolerance is r=0.2×σ_IBI, the standard physiological
    convention.

    Returns NaN for epochs shorter than 50 beats (estimates below that
    length are unreliable).  Requires no external dependencies; the
    computation is pure NumPy.

    References
    ----------
    Richman, J. S., & Moorman, J. R. (2000). Physiological time-series
    analysis using approximate entropy and sample entropy. *American Journal
    of Physiology — Heart and Circulatory Physiology*, 278(6), H2039–H2049.
    """
    ibi = ibi_clean_ms(series)
    if ibi.size < 50:
        return np.nan
    return _sample_entropy(ibi)


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

    For each beat, the T-wave peak is located in the ST segment
    (150–500 ms after the R-peak, capped 100 ms before the next R-peak).
    Amplitude is measured relative to the pre-R baseline (mean ECG in the
    50 ms window before each R-peak), then averaged across all beats.

    Returns NaN when no ECG channel is available (``ctx.ecg_ts is None``)
    or fewer than two R-peaks are present in the epoch.  Ported from
    CARSPAN ``CalcDataColECGTWAVE`` (``T_AnaFunctions.pas``).
    """
    if not isinstance(ctx, EpochContext) or ctx.ecg_ts is None:
        return np.nan
    ecg_t = np.asarray(ctx.ecg_ts.times,  dtype=float)
    ecg_v = np.asarray(ctx.ecg_ts.values, dtype=float)
    if ecg_t.size < 2:
        return np.nan
    rpeaks = np.asarray(ctx.rpeak_times, dtype=float)
    if rpeaks.size < 2:
        return np.nan

    amps: list[float] = []
    for i in range(len(rpeaks) - 1):
        r_t    = rpeaks[i]
        r_next = rpeaks[i + 1]

        # Pre-R baseline: 50 ms before R-peak.
        bl_mask = (ecg_t >= r_t - 0.05) & (ecg_t < r_t)
        if not bl_mask.any():
            continue
        baseline = float(np.mean(ecg_v[bl_mask]))

        # ST segment search window.  np.minimum avoids shadowing the
        # module-level `min` epoch_metric.
        st_lo = r_t + 0.15
        st_hi = float(np.minimum(r_t + 0.50, r_next - 0.10))
        if st_hi <= st_lo:
            continue
        st_mask = (ecg_t >= st_lo) & (ecg_t <= st_hi)
        if not st_mask.any():
            continue
        amps.append(float(np.max(ecg_v[st_mask])) - baseline)

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

# Exact-match tooltips for the columns emitted by the nn_stats group metric.
NN_STATS_COLUMN_TOOLTIPS: dict[str, str] = {
    "nn50":  "Number of successive IBI differences exceeding 50 ms (Task Force 1996).",
    "pnn50": "Percentage of successive IBI differences exceeding 50 ms (nn50 / total × 100).",
    "nn20":  "Number of successive IBI differences exceeding 20 ms.",
    "pnn20": "Percentage of successive IBI differences exceeding 20 ms (nn20 / total × 100).",
}

# Suffix- and exact-match tooltips for the columns emitted by band_freq_stats.
BAND_FREQ_STATS_COLUMN_TOOLTIPS: dict[str, str] = {
    "_peak_hz":   (
        "Dominant (peak-power) frequency within this band, in Hz. "
        "Identifies where in the band the IBI spectrum has its maximum."
    ),
    "_rel_power": (
        "Band power as a fraction of the total power across all component "
        "bands (FullRange excluded; 0–1).  Component band relative powers "
        "sum to 1. Scale-independent and directly comparable across sessions."
    ),
    "total_power": (
        "Sum of spectral power across all component frequency bands "
        "(FullRange excluded). Same units as the individual band powers."
    ),
    "lf_norm": (
        "Normalised LF power: LF / (LF + HF).  Bounded [0, 1]; the LF and "
        "HF normalised values sum to one.  Only present when both LF and HF "
        "bands are configured."
    ),
    "hf_norm": (
        "Normalised HF power: HF / (LF + HF).  Bounded [0, 1]; the LF and "
        "HF normalised values sum to one.  Only present when both LF and HF "
        "bands are configured."
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


@epoch_metric_group
def band_freq_stats(ctx) -> dict[str, float]:
    """Per-band peak frequency, relative power, normalised LF/HF, and total power.

    Emits alongside the absolute band powers of ``band_powers``:

    ``{band}_peak_hz``
        Dominant (peak-power) frequency within each band, in Hz.
    ``{band}_rel_power``
        Band power as a proportion of the sum across all bands (0–1).
    ``total_power``
        Sum of all component band powers, *excluding* FullRange (which
        overlaps all other bands and would double-count).  Matches the HRV
        convention where total power = VLF + LF + HF (+ ULF if present).
    ``lf_norm`` / ``hf_norm``
        LF / (LF + HF) and HF / (LF + HF), emitted only when both ``LF``
        and ``HF`` bands are present in the configuration.  Unlike the raw
        ratio, normalised power is bounded [0, 1] and the two values sum to
        one — making them directly comparable across studies that use
        different absolute power scales.
    """
    out: dict[str, float] = {}
    method = getattr(ctx, "psd_method", None)
    psd_res = getattr(ctx, "psd", None)
    if method is None or psd_res is None:
        return out

    freqs = np.asarray(psd_res.freqs, dtype=float)
    power = np.asarray(psd_res.power, dtype=float)

    raw_powers: dict[str, float] = {}
    for band_name, band_spec in method.bands.items():
        lo, hi = float(band_spec.low), float(band_spec.high)
        mask = (freqs >= lo) & (freqs <= hi)
        if not mask.any():
            continue
        # Peak frequency within the band
        peak_idx = int(np.argmax(power[mask]))
        out[f"{band_name.lower()}_peak_hz"] = float(freqs[mask][peak_idx])
        # Absolute band power (rectangular integration, same as band_powers)
        try:
            raw_powers[band_name] = float(
                band_power_rectangular(freqs, power, lo, hi)
            )
        except Exception:
            pass

    # "FullRange" is an umbrella band that overlaps all component bands.
    # Including it in the denominator would double-count its power, giving
    # fullrange_rel_power ≈ 0.5 instead of a meaningful fraction.
    # HRV convention: total_power = Σ(component bands), FullRange excluded.
    component_powers = {k: v for k, v in raw_powers.items() if k != "FullRange"}
    total = float(sum(component_powers.values())) if component_powers else 0.0
    out["total_power"] = total

    if total > 0.0:
        for band_name, bp in component_powers.items():
            out[f"{band_name.lower()}_rel_power"] = float(bp / total)

    lf = raw_powers.get("LF")
    hf = raw_powers.get("HF")
    if lf is not None and hf is not None:
        denom = lf + hf
        if denom > 0.0:
            out["lf_norm"] = float(lf / denom)
            out["hf_norm"] = float(hf / denom)

    return out
