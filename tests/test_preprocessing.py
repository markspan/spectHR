# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for the headless Session→Session pre-processing transforms.

These live in :mod:`spectHR.DataSet.preprocessing` (no Qt), so unlike the
widget tests they run directly in-process.
"""
from __future__ import annotations

import numpy as np

from spectHR.session import Epoch, Events, Intervals, Samples, Session
from spectHR.DataSet.preprocessing import (
    apply_beat_detection,
    apply_bp_calibration,
    apply_breath_phases,
    apply_ecg_polarity,
    apply_rsp_source,
    filter_ecg,
    invert_ecg,
    recompute_breath_phases,
    resolve_ecg,
    resolve_resp,
    retrigger_beats,
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


def test_retrigger_beats_forces_redetection():
    t, v = _synth_ecg(20.0)
    # A session whose hrv is bogus (one beat): retrigger must redetect properly.
    bogus = Events(np.array([1.0]), np.array(["N"], dtype=object))
    s = Session(name="r", samples={"ecg": Samples(t, v, "ecg")}, events={"hrv": bogus})
    out = retrigger_beats(s)
    assert out.events["hrv"].times.size > 10
    # apply_beat_detection alone would leave the bogus hrv untouched:
    assert apply_beat_detection(s).events["hrv"].times.size == 1


def test_invert_ecg_flips_and_detects():
    t, v = _synth_ecg(20.0)
    # R-peaks negative -> only detectable as upright after inversion.
    s = Session(name="i", samples={"ecg": Samples(t, -v, "ecg")})
    out = invert_ecg(s)
    assert np.allclose(out.samples["ecg"].values, v)         # flipped upright
    assert out.events.get("hrv") is not None
    assert out.events["hrv"].times.size > 10


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
    """With no native respiration, resp is derived from the ICG channel."""
    t = np.arange(0.0, 5.0, 0.01)
    icg = Samples(t, np.sin(t), "icg")
    s = Session(name="r", samples={"icg": icg})
    out = apply_rsp_source(s, {"RespirationAnalysis": {"rsp_source": "icg"}})
    assert "resp" in out.samples
    assert np.allclose(out.samples["resp"].values, icg.values)


def test_rsp_source_keeps_native_resp_over_icg():
    """A native respiration channel must not be overwritten by the ICG.

    Regression: once apply_canonical_channels aliases a VU-AMS dzdt channel to
    ``icg``, rsp_source="icg" would otherwise replace a real breathing trace
    with the heart-rate-paced ICG derivative.
    """
    t = np.arange(0.0, 5.0, 0.01)
    native = Samples(t, np.sin(0.3 * t), "resp")
    icg = Samples(t, np.sin(5.0 * t), "icg")
    s = Session(name="r", samples={"resp": native, "icg": icg})
    out = apply_rsp_source(s, {"RespirationAnalysis": {"rsp_source": "icg"}})
    assert out is s                                   # untouched
    assert np.allclose(out.resp.values, native.values)


def test_rsp_source_missing_channel_is_noop():
    s = Session(name="r")
    assert apply_rsp_source(s, {"RespirationAnalysis": {"rsp_source": "icg"}}) is s


# ---------------------------------------------------------------------------
# Breath-phase segmentation
# ---------------------------------------------------------------------------


def test_breath_phases_detected_from_resp():
    """A resp channel + R-peaks yields a 'breath' Intervals (INH/EXH)."""
    fs = 50.0
    t = np.arange(0.0, 120.0, 1.0 / fs)
    resp = np.sin(2 * np.pi * 0.25 * t)            # 0.25 Hz breathing
    peaks = np.arange(0.5, 120.0, 0.8)             # ~75 bpm R-peaks
    labels = np.full(peaks.shape, "N", dtype=object)
    s = Session(
        name="b",
        samples={"resp": Samples(t, resp, "resp")},
        events={"hrv": Events(peaks, labels)},
    )
    out = apply_breath_phases(s, None)
    assert out.breath is not None
    assert set(np.unique(out.breath.labels)) <= {"INH", "EXH"}
    assert out.breath.labels.size > 4              # several breaths over 120 s


def test_retrigger_then_breath_recompute_spans_full_recording():
    """The retrigger path re-evaluates breath over the *new* R-top coverage.

    Mirrors an EVT recording whose breath phases were limited to the annotated
    R-top window: once ``retrigger_beats`` redetects across the whole ECG,
    ``recompute_breath_phases`` (the step ``MainWindow._reprocess`` now chains)
    re-segments the full respiration instead of staying limited.
    """
    fs = 50.0
    dur = 120.0
    t = np.arange(0.0, dur, 1.0 / fs)
    te, ecg = _synth_ecg(duration=dur, fs=fs, hr=75.0)   # beats across the whole span
    resp = np.sin(2 * np.pi * 0.25 * t)
    # Pre-existing breath phases limited to the first few seconds (the EVT case).
    limited = Intervals(
        starts=np.array([1.0, 3.0]),
        ends=np.array([3.0, 5.0]),
        labels=np.array(["INH", "EXH"], dtype=object),
    )
    s = Session(
        name="evt",
        samples={"ecg": Samples(te, ecg, "ecg"), "resp": Samples(t, resp, "resp")},
        events={"hrv": Events(np.array([1.0]), np.array(["N"], dtype=object))},  # bogus
        intervals={"breath": limited},
    )
    out = recompute_breath_phases(retrigger_beats(s), None)
    assert out.breath is not None
    assert float(out.breath.ends[-1]) > 0.75 * dur      # now spans the whole recording


def test_breath_phases_noop_without_resp():
    peaks = np.arange(0.5, 30.0, 0.8)
    s = Session(name="n", events={"hrv": Events(peaks, np.full(peaks.shape, "N", object))})
    assert apply_breath_phases(s, None) is s


def test_breath_phases_noop_without_beats():
    t = np.arange(0.0, 30.0, 0.02)
    s = Session(name="n", samples={"resp": Samples(t, np.sin(t), "resp")})
    assert apply_breath_phases(s, None) is s


# ---------------------------------------------------------------------------
# Canonical channel aliasing
# ---------------------------------------------------------------------------


def test_canonical_channels_alias_device_suffixed_and_icg():
    """ecg-[dev]/dzdt-[dev]/rsp-[dev] become accessible as ecg/icg/resp."""
    from spectHR.DataSet.preprocessing import apply_canonical_channels

    t = np.arange(0.0, 5.0, 0.01)
    s = Session(name="vu", samples={
        "ecg-[vuams]":  Samples(t, np.sin(t),       "ecg-[vuams]"),
        "dzdt-[vuams]": Samples(t, np.cos(t),       "dzdt-[vuams]"),
        "rsp-[vuams]":  Samples(t, np.sin(0.3 * t), "rsp-[vuams]"),
    })
    assert s.ecg is None and s.icg is None and s.resp is None   # canonical misses
    out = apply_canonical_channels(s)
    assert out.ecg is not None and out.icg is not None and out.resp is not None
    # Aliases reuse the same Samples object (no copy).
    assert out.icg is out.samples["dzdt-[vuams]"]


def test_canonical_channels_noop_when_canonical_present():
    t = np.arange(0.0, 5.0, 0.01)
    s = Session(name="c", samples={"ecg": Samples(t, np.sin(t), "ecg")})
    from spectHR.DataSet.preprocessing import apply_canonical_channels
    assert apply_canonical_channels(s) is s


# ---------------------------------------------------------------------------
# Per-epoch breath detection (posture-adaptive PCA)
# ---------------------------------------------------------------------------


def _accel_session(per_epoch_breaths=True):
    """Two epochs whose breathing sits on a *different* accelerometer axis."""
    fs = 25.0
    t = np.arange(0.0, 120.0, 1.0 / fs)
    half = t.size // 2
    z = np.zeros_like(t)
    # Epoch 1 (0-60 s): breathing on X.  Epoch 2 (60-120 s): breathing on Y.
    breath = np.sin(2 * np.pi * 0.25 * t)
    x = np.where(np.arange(t.size) < half, breath, z) + 0.01 * np.random.default_rng(0).normal(size=t.size)
    y = np.where(np.arange(t.size) >= half, breath, z) + 0.01 * np.random.default_rng(1).normal(size=t.size)
    peaks = np.arange(0.5, 120.0, 0.8)
    return Session(
        name="acc",
        samples={
            "mxr": Samples(t, x, "mxr"), "myr": Samples(t, y, "myr"),
            "mzr": Samples(t, z, "mzr"),
            "ecg": Samples(t, np.sin(t), "ecg"),
        },
        events={"hrv": Events(peaks, np.full(peaks.shape, "N", object))},
        epochs={
            "experiment": Epoch("experiment", 0.0, 120.0, True),
            "a": Epoch("a", 0.0, 60.0, True),
            "b": Epoch("b", 60.0, 120.0, True),
        },
    )


def test_accel_axes_resolved_and_pca():
    from spectHR.DataSet.preprocessing import resolve_accel_axes
    from spectHR.signal.respiration import accel_to_respiration
    s = _accel_session()
    axes = resolve_accel_axes(s)
    assert axes is not None and len(axes) == 3
    acc = np.column_stack([a.values for a in axes])
    rsp = accel_to_respiration(acc, 25.0)
    assert rsp.shape[0] == acc.shape[0]
    assert np.isfinite(rsp).all()


def test_breath_phases_per_epoch_uses_accel_pca():
    s = _accel_session()
    params = {"RespirationAnalysis": {"per_epoch": True, "rsp_source": "accelerometer"}}
    out = apply_breath_phases(s, params)
    assert out.breath is not None
    # The "experiment" epoch is skipped; phases come from epochs a and b, each
    # PCA'd on its own posture, so breaths are found across the whole span.
    starts = np.asarray(out.breath.starts, dtype=float)
    assert starts.size > 4
    assert starts.min() < 60.0 and starts.max() > 60.0   # both epochs contributed


def test_breath_phases_global_default_still_works():
    s = _accel_session()
    # Global (default) accelerometer PCA over the whole recording.
    out = apply_breath_phases(s, {"RespirationAnalysis": {"rsp_source": "accelerometer"}})
    assert out.breath is not None and out.breath.labels.size > 0
