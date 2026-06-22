# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for ECG polarity detection (:func:`detect_ecg_polarity`).

Pure spectHR signal logic, no Qt.  The Session-level transform
:func:`spectHR.dataset.preprocessing.apply_ecg_polarity` that calls this is
covered in ``test_preprocessing.py``.
"""
from __future__ import annotations

import numpy as np

from spectHR.signal.ecg import detect_ecg_polarity


def _synth_ecg(duration: float = 20.0, fs: float = 250.0, hr_bpm: float = 60.0):
    """Upright ECG: tall narrow positive R-spikes on a quiet baseline."""
    t = np.arange(0.0, duration, 1.0 / fs)
    sig = np.zeros_like(t)
    rr = 60.0 / hr_bpm
    for beat in np.arange(0.5, duration, rr):
        sig += np.exp(-0.5 * ((t - beat) / 0.008) ** 2)  # sharp R spike
    sig += 0.01 * np.random.default_rng(0).standard_normal(t.size)
    return t, sig


def test_upright_signal_is_normal():
    t, v = _synth_ecg()
    assert detect_ecg_polarity(t, v) == "normal"


def test_inverted_signal_is_inverted():
    t, v = _synth_ecg()
    assert detect_ecg_polarity(t, -v) == "inverted"


def test_segment_tuple_is_accepted():
    t, v = _synth_ecg(duration=40.0)
    assert detect_ecg_polarity(t, v, segment=(10.0, 30.0)) == "normal"
    assert detect_ecg_polarity(t, -v, segment=(10.0, 30.0)) == "inverted"


def test_segment_epoch_like_is_accepted():
    class _Ep:
        start, end = 10.0, 30.0

    t, v = _synth_ecg(duration=40.0)
    assert detect_ecg_polarity(t, v, segment=_Ep()) == "normal"


def test_return_debug_reports_skewness_sign():
    t, v = _synth_ecg()
    pol, dbg = detect_ecg_polarity(t, v, return_debug=True)
    assert pol == "normal"
    assert dbg["skewness"] > 0
    assert dbg["decision_source"] in ("skewness", "peak_count", "raw_skewness")
    assert dbg["segment_source"] in ("epoch", "middle_third", "full")


def test_flat_signal_defaults_to_normal():
    t = np.arange(0.0, 10.0, 1.0 / 250.0)
    v = np.zeros_like(t)
    # No QRS to decide on, must not crash and must not spuriously flip.
    assert detect_ecg_polarity(t, v) == "normal"


def test_too_short_uses_raw_skewness():
    # Below the filter minimum: still decides on raw median-centred skewness.
    t = np.arange(0.0, 0.1, 1.0 / 250.0)  # 25 samples
    v = np.zeros_like(t)
    v[12] = 5.0  # one positive spike
    pol, dbg = detect_ecg_polarity(t, v, return_debug=True)
    assert dbg["decision_source"] == "raw_skewness"
    assert pol == "normal"
