# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/signal/ecg.py
"""Standalone ECG signal-processing utilities.

:func:`detect_ecg_polarity` determines whether a raw ECG signal has normal
or inverted polarity, using the skewness of the bandpass-filtered signal as
the primary indicator.
"""
from __future__ import annotations

import numpy as np
import scipy.signal as signal
import scipy.stats

from spectHR.logger import logger


__all__ = ["detect_ecg_polarity"]

# filtfilt with a 3rd-order Butterworth (len(b) = len(a) = 4) needs at least
# 3*max(len(b),len(a)) = 12 samples; scipy adds edge padding on top of that.
# 50 samples is a comfortable minimum that avoids the scipy padlen check.
_MIN_SAMPLES_FOR_FILTER = 50

# Skewness magnitude below which the primary decision is treated as unreliable
# and the peak-count tiebreaker is used instead.
_SKEW_RELIABLE = 0.10


def detect_ecg_polarity(
    times: np.ndarray,
    values: np.ndarray,
    *,
    segment=None,
    bandpass: tuple[float, float] = (5.0, 20.0),
    min_peak_distance: float = 0.25,
    return_debug: bool = False,
) -> "str | tuple[str, dict]":
    """Determine whether an ECG signal is correctly oriented or inverted.

    Parameters
    ----------
    times : np.ndarray
        Sample timestamps in seconds. Used to estimate the sampling rate.
    values : np.ndarray
        Raw ECG amplitude values (same length as *times*).
    segment : Epoch-like or (float, float) or None, optional
        Time range to analyse. Can be:

        * An ``Epoch`` object (or any object with ``.start`` / ``.end``
          attributes in seconds).
        * A ``(start, end)`` tuple of floats in seconds.
        * ``None`` (default), falls back to the middle third of the
          recording, which avoids settling artefacts at both ends.

        The middle-third fallback is always used when the segment
        contains fewer than ``_MIN_SAMPLES_FOR_FILTER`` samples.
    bandpass : tuple[float, float], optional
        Bandpass filter cutoffs in Hz used to emphasise QRS complexes.
        Default ``(5.0, 20.0)``.
    min_peak_distance : float, optional
        Minimum distance between detected peaks in seconds, used only
        as a tiebreaker when skewness is near zero. Default ``0.25``.
    return_debug : bool, optional
        If ``True``, also return a dictionary of intermediate diagnostics.

    Returns
    -------
    polarity : {"normal", "inverted"}
        Estimated ECG polarity.
    debug : dict, optional
        Only returned when *return_debug* is ``True``. Contains
        ``skewness``, ``peak_score``, ``n_pos_peaks``, ``n_neg_peaks``,
        ``decision_source`` (``"skewness"``, ``"peak_count"``, or
        ``"raw_skewness"`` when the signal was too short to filter), and
        ``segment_source`` (``"epoch"``, ``"middle_third"``, or
        ``"full"`` for very short recordings).

    Notes
    -----
    **Algorithm** - two-stage decision on the selected segment:

    1. *Skewness* (primary): after a 5-20 Hz bandpass filter the QRS
       complexes dominate the amplitude distribution. A normal ECG has
       tall positive R-spikes -> positive skewness; an inverted ECG has
       negative skewness. No threshold is required - only the sign
       matters, and the cubic weighting of skewness means the tall
       R-peaks override noise.

    2. *Peak-prominence count* (tiebreaker): used only when
       ``|skewness| < 0.1`` (very short recordings or very noisy
       signals where the skewness sign is unreliable). The total
       positive-peak prominence is compared to the negative-peak
       prominence; whichever is larger indicates the upright direction.
    """
    times  = np.asarray(times,  dtype=float)
    values = np.asarray(values, dtype=float)

    if values.ndim != 1:
        raise ValueError("ECG signal must be 1-D.")
    if times.size < 2:
        raise ValueError("Need at least 2 samples to estimate sampling rate.")

    diffs = np.diff(times)
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        raise ValueError(
            "Cannot estimate sampling rate: no positive time deltas found."
        )
    fs = float(1.0 / np.mean(diffs))

    # ------------------------------------------------------------------
    # Select the segment to analyse
    # ------------------------------------------------------------------
    segment_source = "middle_third"
    ecg = values.copy()

    if segment is not None:
        # Accept either an Epoch-like object or a (start, end) tuple.
        if hasattr(segment, "start") and hasattr(segment, "end"):
            t_start, t_end = float(segment.start), float(segment.end)
        else:
            t_start, t_end = float(segment[0]), float(segment[1])

        mask = (times >= t_start) & (times <= t_end)
        if mask.sum() >= _MIN_SAMPLES_FOR_FILTER:
            ecg = ecg[mask]
            segment_source = "epoch"
        else:
            # Segment too short - fall through to middle-third fallback.
            logger.debug(
                "detect_ecg_polarity: segment [%.2f, %.2f] has only %d samples "
                "(need %d); falling back to middle third.",
                t_start, t_end, int(mask.sum()), _MIN_SAMPLES_FOR_FILTER,
            )

    if segment_source == "middle_third":
        # Use the middle third of the full recording, trimming one third
        # from each end to avoid start-up/settling artefacts.
        n = ecg.size
        trim = n // 3
        if n > 2 * trim and trim > 0:
            ecg = ecg[trim : n - trim]
            segment_source = "middle_third"
        else:
            # Very short recording - use everything.
            segment_source = "full"

    ecg -= np.nanmedian(ecg)

    # ------------------------------------------------------------------
    # 1. Bandpass filter (QRS emphasis, 5-20 Hz) when long enough.
    # ------------------------------------------------------------------
    n_pos_peaks = 0
    n_neg_peaks = 0
    peak_score  = 0.0

    if ecg.size >= _MIN_SAMPLES_FOR_FILTER:
        nyq  = 0.5 * fs
        low  = max(bandpass[0] / nyq, 1e-4)
        high = min(bandpass[1] / nyq, 1.0 - 1e-4)
        b, a = signal.butter(3, [low, high], btype="bandpass")
        ecg_f = signal.filtfilt(b, a, ecg)
        decision_source = "skewness"
    else:
        ecg_f = ecg  # too short to filter; use raw median-centred signal
        decision_source = "raw_skewness"

    # ------------------------------------------------------------------
    # 2. Primary: skewness of the (filtered) signal
    #
    # Normal ECG  -> R-peaks are tall positive spikes -> skewness > 0
    # Inverted ECG -> R-peaks are tall negative spikes -> skewness < 0
    # ------------------------------------------------------------------
    skew = float(scipy.stats.skew(ecg_f))

    if abs(skew) >= _SKEW_RELIABLE:
        polarity = "normal" if skew > 0 else "inverted"
    else:
        # ------------------------------------------------------------------
        # 3. Tiebreaker: peak-prominence dominance
        # ------------------------------------------------------------------
        decision_source  = "peak_count"
        distance_samples = max(int(min_peak_distance * fs), 1)
        prom_threshold   = np.std(ecg_f)

        pos_peaks, pos_props = signal.find_peaks(
            ecg_f, distance=distance_samples, prominence=prom_threshold)
        neg_peaks, neg_props = signal.find_peaks(
            -ecg_f, distance=distance_samples, prominence=prom_threshold)

        n_pos_peaks = len(pos_peaks)
        n_neg_peaks = len(neg_peaks)
        pos_prom = float(np.sum(pos_props["prominences"])) if n_pos_peaks else 0.0
        neg_prom = float(np.sum(neg_props["prominences"])) if n_neg_peaks else 0.0
        peak_score = pos_prom - neg_prom

        # Flat/featureless signal - default to "normal" to avoid
        # unnecessary flipping when we genuinely cannot decide.
        if pos_prom == 0.0 and neg_prom == 0.0:
            polarity = "normal"
        else:
            polarity = "normal" if pos_prom >= neg_prom else "inverted"

    logger.debug(
        "detect_ecg_polarity: seg=%s skew=%.3f source=%s -> %s",
        segment_source, skew, decision_source, polarity,
    )

    if return_debug:
        # Compute peak stats even when skewness was decisive so the
        # caller can always inspect them.
        if decision_source in ("skewness", "raw_skewness"):
            distance_samples = max(int(min_peak_distance * fs), 1)
            prom_threshold   = np.std(ecg_f)
            pos_peaks, pos_props = signal.find_peaks(
                ecg_f, distance=distance_samples, prominence=prom_threshold)
            neg_peaks, neg_props = signal.find_peaks(
                -ecg_f, distance=distance_samples, prominence=prom_threshold)
            n_pos_peaks = len(pos_peaks)
            n_neg_peaks = len(neg_peaks)
            pos_prom = float(np.sum(pos_props["prominences"])) if n_pos_peaks else 0.0
            neg_prom = float(np.sum(neg_props["prominences"])) if n_neg_peaks else 0.0
            peak_score = pos_prom - neg_prom

        debug = dict(
            skewness=skew,
            peak_score=peak_score,
            n_pos_peaks=n_pos_peaks,
            n_neg_peaks=n_neg_peaks,
            decision_source=decision_source,
            segment_source=segment_source,
        )
        return polarity, debug

    return polarity
