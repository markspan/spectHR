# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
tests/test_bp_metrics.py -- beat-by-beat BP / RESP parameters.

Covers the CARSPAN-faithful blood-pressure and respiration parameter
calculators in ``spectHR.analysis.bp_metrics``:

- SBP/DBP/PP value definitions (max, min-before-max, max-min)
- MAP as the integral mean between successive diastolic minima
- Flat-line rejection (zero/low coefficient of variation -> NaN beat)
- Respiratory volume MVO (per cardiac interval) and SVO (window at R-peak)
- Per-epoch nanmean aggregation and empty/degenerate edge cases
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.bp_metrics import (
    bp_beat_parameters,
    bp_epoch_metrics,
    is_flatline,
    resp_beat_parameters,
    resp_epoch_metrics,
)


class _TS:
    """Minimal TimeSeries-like with .times / .values."""

    def __init__(self, times, values):
        self.times = np.asarray(times, dtype=float)
        self.values = np.asarray(values, dtype=float)


def _synthetic_bp(n_beats=4, fs=100.0, dia=80.0, sys=120.0):
    """Build a clean BP waveform: each 1 s beat rises dia -> sys -> dia."""
    rpeaks = np.arange(n_beats + 1, dtype=float)
    t = np.arange(0.0, float(n_beats), 1.0 / fs)
    phase = t % 1.0
    val = dia + (sys - dia) * np.sin(np.pi * phase)
    return rpeaks, t, val


# ---------------------------------------------------------------------------
# Blood pressure
# ---------------------------------------------------------------------------

def test_bp_beat_values_match_definitions():
    rpeaks, t, val = _synthetic_bp()
    beats = bp_beat_parameters(t, val, rpeaks)

    assert np.allclose(beats["sbp"], 120.0, atol=1e-6)
    assert np.allclose(beats["dbp"], 80.0, atol=1e-6)
    assert np.allclose(beats["pp"], 40.0, atol=1e-6)
    # PP == SBP - DBP for every beat.
    assert np.allclose(beats["pp"], beats["sbp"] - beats["dbp"], equal_nan=True)


def test_bp_map_is_integral_mean_not_textbook():
    """MAP is the waveform mean between diastoles, not (SBP + 2*DBP)/3."""
    rpeaks, t, val = _synthetic_bp()
    beats = bp_beat_parameters(t, val, rpeaks)

    textbook = (120.0 + 2.0 * 80.0) / 3.0          # ~93.3
    integral = 80.0 + 40.0 * (2.0 / np.pi)          # ~105.5 (mean of sin lobe)

    finite = beats["map"][np.isfinite(beats["map"])]
    assert finite.size > 0
    assert np.allclose(finite, integral, atol=1.0)
    assert not np.allclose(finite, textbook, atol=1.0)


def test_bp_map_last_beat_is_nan():
    """The final interval has no following diastole, so MAP is NaN there."""
    rpeaks, t, val = _synthetic_bp()
    beats = bp_beat_parameters(t, val, rpeaks)
    assert np.isnan(beats["map"][-1])


def test_bp_epoch_metrics_keys_and_values():
    rpeaks, t, val = _synthetic_bp()
    out = bp_epoch_metrics(_TS(t, val), rpeaks)
    assert set(out) == {"bp_sbp", "bp_dbp", "bp_pp", "bp_map"}
    assert abs(out["bp_sbp"] - 120.0) < 1e-6
    assert abs(out["bp_dbp"] - 80.0) < 1e-6
    assert abs(out["bp_pp"] - 40.0) < 1e-6


def test_bp_empty_inputs_return_nan():
    out = bp_epoch_metrics(_TS([], []), np.array([]))
    assert all(np.isnan(v) for v in out.values())


# ---------------------------------------------------------------------------
# Flat-line guard
# ---------------------------------------------------------------------------

def test_flatline_constant_signal_is_flat():
    t = np.arange(0.0, 1.0, 0.01)
    flat = np.full_like(t, 100.0)
    assert is_flatline(t, flat, 0, flat.size - 1) is True


def test_flatline_varying_signal_is_not_flat():
    _, t, val = _synthetic_bp(n_beats=1)
    assert is_flatline(t, val, 0, val.size - 1) is False


def test_flatline_beat_becomes_nan():
    """A constant beat in the middle is rejected to NaN, others survive."""
    fs = 100.0
    rpeaks = np.array([0.0, 1.0, 2.0, 3.0])
    t = np.arange(0.0, 3.0, 1.0 / fs)
    phase = t % 1.0
    val = 80.0 + 40.0 * np.sin(np.pi * phase)
    # Clamp the second beat [1,2) to a constant -> flat line.
    val[(t >= 1.0) & (t < 2.0)] = 95.0
    beats = bp_beat_parameters(t, val, rpeaks)
    assert np.isnan(beats["sbp"][1])
    assert np.isfinite(beats["sbp"][0])
    assert np.isfinite(beats["sbp"][2])


# ---------------------------------------------------------------------------
# Respiration
# ---------------------------------------------------------------------------

def test_resp_mvo_and_svo_shapes():
    rpeaks = np.array([0.0, 1.0, 2.0, 3.0])
    tr = np.arange(0.0, 3.0, 0.01)
    vr = np.sin(2.0 * np.pi * 0.25 * tr)
    beats = resp_beat_parameters(tr, vr, rpeaks)
    assert beats["mvo"].size == rpeaks.size - 1
    assert beats["svo"].size == rpeaks.size


def test_resp_epoch_metrics_keys():
    rpeaks = np.array([0.0, 1.0, 2.0, 3.0])
    tr = np.arange(0.0, 3.0, 0.01)
    vr = np.sin(2.0 * np.pi * 0.25 * tr)
    out = resp_epoch_metrics(_TS(tr, vr), rpeaks)
    assert set(out) == {"resp_mvo", "resp_svo"}
    assert all(np.isfinite(v) for v in out.values())


def test_resp_empty_inputs_return_nan():
    out = resp_epoch_metrics(_TS([], []), np.array([]))
    assert all(np.isnan(v) for v in out.values())
