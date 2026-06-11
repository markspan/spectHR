# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for the headless Session→Session pre-processing transforms.

These live in :mod:`spectHR.DataSet.preprocessing` (no Qt), so unlike the
widget tests they run directly in-process.
"""
from __future__ import annotations

import numpy as np

from spectHR.session import Epoch, Events, Samples, Session
from spectHR.DataSet.preprocessing import (
    apply_beat_detection,
    apply_bp_calibration,
    apply_ecg_polarity,
    apply_rsp_source,
    filter_ecg,
    resolve_ecg,
    resolve_resp,
)
from spectHR.config import CardioParams


def _synth_ecg(duration=20.0, fs=250.0, hr=60.0):
    """Upright ECG: tall narrow positive R-spikes."""
    t = np.arange(0.0, duration, 1.0 / fs)
    sig = np.zeros_like(t)
    for beat in np.arange(0.5, duration, 60.0 / hr):
        sig += np.exp(-0.5 * ((t - beat) / 0.008) ** 2)
    return t, sig


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------


def test_resolve_canonical_keys():
    t, v = _synth_ecg()
    s = Session(name="c", samples={"ecg": Samples(t, v, "ecg"),
                                   "resp": Samples(t, v, "resp")})
    assert resolve_ecg(s).name == "ecg"
    assert resolve_resp(s).name == "resp"


def test_resolve_device_suffixed_keys():
    t, v = _synth_ecg()
    s = Session(name="x", samples={"ecg-[8554112A]": Samples(t, v, "ecg-[8554112A]"),
                                   "RSP-[8554112A]": Samples(t, v, "RSP-[8554112A]")})
    assert s.ecg is None and s.resp is None              # canonical lookup misses
    assert resolve_ecg(s).name == "ecg-[8554112A]"
    assert resolve_resp(s).name == "RSP-[8554112A]"


def test_resolve_missing_returns_none():
    s = Session(name="empty")
    assert resolve_ecg(s) is None and resolve_resp(s) is None


# ---------------------------------------------------------------------------
# ECG polarity
# ---------------------------------------------------------------------------


def test_polarity_flips_inverted_device_suffixed_channel():
    t, v = _synth_ecg()
    inv = Session(
        name="inv",
        samples={"ecg-[X9]": Samples(t, -v, "ecg-[X9]")},
        epochs={"experiment": Epoch("experiment", 0.0, 20.0, True),
                "rest": Epoch("rest", 2.0, 18.0, True)},
    )
    fixed = apply_ecg_polarity(inv)
    assert fixed is not inv                              # new Session returned
    assert np.allclose(fixed.samples["ecg-[X9]"].values, v)   # negated upright
    assert fixed.samples["ecg-[X9]"].times.flags.writeable is False


def test_polarity_leaves_upright_untouched():
    t, v = _synth_ecg()
    s = Session(name="ok", samples={"ecg": Samples(t, v, "ecg")})
    assert apply_ecg_polarity(s) is s                   # same object, no copy


def test_polarity_no_ecg_is_noop():
    t, v = _synth_ecg()
    s = Session(name="bp", samples={"bp": Samples(t, v, "bp")})
    assert apply_ecg_polarity(s) is s


# ---------------------------------------------------------------------------
# Prefilter + beat detection
# ---------------------------------------------------------------------------


def test_filter_ecg_highpass_removes_baseline_wander():
    t = np.arange(0.0, 30.0, 1.0 / 130.0)
    wander = 3.0 * np.sin(2 * np.pi * 0.1 * t)
    beats = sum(np.exp(-0.5 * ((t - b) / 0.01) ** 2) for b in np.arange(0.5, 30.0, 0.8))
    ecg = Samples(t, beats + wander, "ecg")
    out = filter_ecg(ecg, CardioParams())               # highpass 0.5 Hz default
    assert np.ptp(out.values) < np.ptp(ecg.values)


def test_filter_ecg_disabled_returns_input():
    t, v = _synth_ecg()
    ecg = Samples(t, v, "ecg")
    cardio = CardioParams(ecg_filter_type=None)
    assert filter_ecg(ecg, cardio) is ecg


def test_beat_detection_fills_hrv_from_device_suffixed_ecg():
    t, v = _synth_ecg(duration=20.0)
    s = Session(name="d", samples={"ecg-[Z9]": Samples(t, v, "ecg-[Z9]")})
    out = apply_beat_detection(s)
    assert out is not s
    assert out.events.get("hrv") is not None
    assert out.events["hrv"].times.size > 10


def test_beat_detection_skips_when_hrv_present():
    t, v = _synth_ecg()
    hrv = Events(np.arange(0.5, 20.0, 0.8),
                 np.full(np.arange(0.5, 20.0, 0.8).shape, "N", dtype=object))
    s = Session(name="h", samples={"ecg": Samples(t, v, "ecg")}, events={"hrv": hrv})
    assert apply_beat_detection(s) is s


def test_beat_detection_no_ecg_is_noop():
    s = Session(name="x")
    assert apply_beat_detection(s) is s


# ---------------------------------------------------------------------------
# BP calibration / RSP source
# ---------------------------------------------------------------------------


def test_bp_calibration_scales_to_mmhg():
    t = np.arange(0.0, 5.0, 0.01)
    raw = np.full_like(t, 800.0)
    s = Session(name="bp", samples={"bp": Samples(t, raw, "bp")})
    out = apply_bp_calibration(s, {"Calibration": {"bp_scale": 0.125, "bp_zero": 0.0}})
    assert np.allclose(out.samples["bp"].values, 100.0)  # 800 * 0.125


def test_bp_calibration_zero_scale_is_noop():
    t = np.arange(0.0, 5.0, 0.01)
    s = Session(name="bp", samples={"bp": Samples(t, np.full_like(t, 800.0), "bp")})
    assert apply_bp_calibration(s, {"Calibration": {"bp_scale": 0.0}}) is s


def test_rsp_source_copies_icg_to_resp():
    t = np.arange(0.0, 5.0, 0.01)
    icg = Samples(t, np.sin(t), "icg")
    s = Session(name="r", samples={"icg": icg})
    out = apply_rsp_source(s, {"RespirationAnalysis": {"rsp_source": "icg"}})
    assert "resp" in out.samples
    assert np.allclose(out.samples["resp"].values, icg.values)


def test_rsp_source_missing_channel_is_noop():
    s = Session(name="r")
    assert apply_rsp_source(s, {"RespirationAnalysis": {"rsp_source": "icg"}}) is s
