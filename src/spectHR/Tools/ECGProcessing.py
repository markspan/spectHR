# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/Tools/ECGProcessing.py
"""
Standalone ECG signal-processing utilities.

This module contains algorithms that operate on raw ECG waveform data
independently of any dataset or series class, making them testable and
reusable outside the ``TimeSeries`` context.

Public surface
--------------
detect_ecg_polarity(times, values, *, bandpass, min_peak_distance, return_debug)
    Determine whether an ECG signal is correctly oriented or inverted.

``TimeSeries.detect_ecg_polarity`` is a thin wrapper that calls this function;
existing call sites need no changes.
"""
from __future__ import annotations

from typing import Union

import numpy as np
import scipy.signal as signal

from spectHR.Tools.Logger import logger


__all__ = ["detect_ecg_polarity"]


# ---------------------------------------------------------------------------
# Heuristic weights
# ---------------------------------------------------------------------------
# Three independent heuristics are combined into a single score.
# Positive total → signal is inverted; negative → normal orientation.
# Weights reflect relative reliability: peak prominence is the most direct
# indicator (1.0), Hilbert envelope energy is secondary (0.8), and percentile
# asymmetry is the weakest signal (0.5).

_POLARITY_WEIGHT_PEAK:     float = 1.0
_POLARITY_WEIGHT_ENVELOPE: float = 0.8
_POLARITY_WEIGHT_EXTREMA:  float = 0.5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_ecg_polarity(
    times: np.ndarray,
    values: np.ndarray,
    *,
    bandpass: tuple[float, float] = (5.0, 20.0),
    min_peak_distance: float = 0.25,
    return_debug: bool = False,
) -> Union[str, tuple[str, dict]]:
    """Determine whether an ECG signal is correctly oriented or inverted.

    Parameters
    ----------
    times : np.ndarray
        Sample timestamps in seconds. Used to estimate the sampling rate.
    values : np.ndarray
        Raw ECG amplitude values (same length as *times*).
    bandpass : tuple[float, float], optional
        Bandpass filter cutoffs in Hz used to emphasise QRS complexes.
        Default ``(5.0, 20.0)``.
    min_peak_distance : float, optional
        Minimum distance between peaks in seconds. Default ``0.25``.
    return_debug : bool, optional
        If ``True``, also return a dictionary with the intermediate
        diagnostic scores used to reach the decision.

    Returns
    -------
    polarity : {"normal", "inverted"}
        Estimated ECG polarity.
    debug : dict, optional
        Only returned when *return_debug* is ``True``. Contains
        ``peak_score``, ``envelope_score``, ``extrema_score``,
        ``total_score``, ``n_pos_peaks``, ``n_neg_peaks``.

    Notes
    -----
    The function is intentionally conservative and robust: no single
    heuristic determines polarity. Three independent signals are
    combined with fixed weights:

    1. Peak-prominence dominance (weight 1.0): sum of positive-peak
       prominences minus sum of negative-peak prominences on the
       bandpass-filtered signal.
    2. Hilbert-envelope energy asymmetry (weight 0.8): mean envelope
       amplitude for positive vs. negative signal segments.
    3. Percentile extrema asymmetry (weight 0.5): p95 + p05 of the
       filtered signal (positive when the upper tail dominates).

    A positive aggregate score indicates an inverted ECG.
    """
    times = np.asarray(times, dtype=float)
    values = np.asarray(values, dtype=float)

    if values.ndim != 1:
        raise ValueError("ECG signal must be 1-D.")

    # Estimate sampling rate from timestamps.
    if times.size < 2:
        raise ValueError("Need at least 2 samples to estimate sampling rate.")
    diffs = np.diff(times)
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        raise ValueError(
            "Cannot estimate sampling rate: no positive time deltas found."
        )
    fs = float(1.0 / np.mean(diffs))

    # Trim the outer quarter to avoid edge artefacts, then mean-centre.
    ecg = values.copy()
    ecg = ecg[ecg.size // 4 : -ecg.size // 4] if ecg.size > 100 else ecg
    ecg -= np.nanmedian(ecg)

    # ------------------------------------------------------------------
    # 1. Bandpass filter (QRS emphasis)
    # ------------------------------------------------------------------
    nyq = 0.5 * fs
    b, a = signal.butter(
        3,
        [bandpass[0] / nyq, bandpass[1] / nyq],
        btype="bandpass",
    )
    ecg_f = signal.filtfilt(b, a, ecg)

    # ------------------------------------------------------------------
    # 2. Peak polarity dominance
    # ------------------------------------------------------------------
    distance_samples = int(min_peak_distance * fs)

    pos_peaks, pos_props = signal.find_peaks(
        ecg_f,
        distance=distance_samples,
        prominence=np.std(ecg_f),
    )
    neg_peaks, neg_props = signal.find_peaks(
        -ecg_f,
        distance=distance_samples,
        prominence=np.std(ecg_f),
    )

    pos_prom = np.sum(pos_props["prominences"]) if len(pos_peaks) else 0.0
    neg_prom = np.sum(neg_props["prominences"]) if len(neg_peaks) else 0.0
    peak_score = pos_prom - neg_prom

    # ------------------------------------------------------------------
    # 3. Upper vs lower envelope energy
    # ------------------------------------------------------------------
    analytic = signal.hilbert(ecg_f)
    envelope = np.abs(analytic)

    upper_energy = np.mean(envelope[ecg_f > 0]) if np.any(ecg_f > 0) else 0.0
    lower_energy = np.mean(envelope[ecg_f < 0]) if np.any(ecg_f < 0) else 0.0
    envelope_score = upper_energy - lower_energy

    # ------------------------------------------------------------------
    # 4. Extrema asymmetry
    # ------------------------------------------------------------------
    p95 = np.percentile(ecg_f, 95)
    p05 = np.percentile(ecg_f, 5)
    extrema_score = p95 + p05  # positive when the upper tail dominates

    # ------------------------------------------------------------------
    # 5. Aggregate decision
    # ------------------------------------------------------------------
    total_score = (
        _POLARITY_WEIGHT_PEAK     * peak_score
        + _POLARITY_WEIGHT_ENVELOPE * envelope_score
        + _POLARITY_WEIGHT_EXTREMA  * extrema_score
    )

    polarity = "normal" if total_score < 0 else "inverted"

    logger.debug(
        "detect_ecg_polarity: peak=%.3f env=%.3f ext=%.3f total=%.3f → %s",
        peak_score, envelope_score, extrema_score, total_score, polarity,
    )

    debug = dict(
        peak_score=peak_score,
        envelope_score=envelope_score,
        extrema_score=extrema_score,
        total_score=total_score,
        n_pos_peaks=len(pos_peaks),
        n_neg_peaks=len(neg_peaks),
    )

    return (polarity, debug) if return_debug else polarity
