# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Regression tests for the ECG-waveform metric ``twave_amplitude``.

The metric is computed whenever an ECG channel is present (EVT+NFF, XDF, EDF,
...).  It is exercised end-to-end through ``Session.epochs_table`` because that
path swallows any metric exception into ``NaN``: a unit bug (e.g. the ``min``/
``max`` HRV metrics shadowing the builtins, which once made ``twave_amplitude``
raise on every beat) would otherwise hide as a silently blank column.
"""
from __future__ import annotations

import numpy as np

from spectHR.session import Epoch, Events, Samples, Session


def _synthetic_ecg(duration=30.0, fs=200.0, rr=0.8, t_amp=0.3):
    """Flat-baseline ECG: a tall R-spike per beat and a T-wave bump ~300 ms later."""
    t = np.arange(0.0, duration, 1.0 / fs)
    sig = np.zeros_like(t)
    peaks = np.arange(0.5, duration - 1.0, rr)
    for r in peaks:
        # Narrow R-spike so its tail stays out of the 50 ms pre-R baseline window.
        sig += 1.0 * np.exp(-0.5 * ((t - r) / 0.004) ** 2)          # R-spike
        sig += t_amp * np.exp(-0.5 * ((t - (r + 0.30)) / 0.04) ** 2)  # T-wave
    return t, sig, peaks


def _session_with_ecg(**kw):
    t, sig, peaks = _synthetic_ecg(**kw)
    labels = np.full(peaks.shape, "N", dtype=object)
    return Session(
        name="s",
        samples={"ecg": Samples(t, sig, "ecg")},
        events={"hrv": Events(peaks, labels)},
        epochs={"whole": Epoch("whole", 0.0, float(t[-1]), True)},
    )


def _twave_column(session):
    table = session.epochs_table()
    assert "twave_amplitude" in table.columns
    return table.values[:, table.columns.index("twave_amplitude")]


def test_twave_amplitude_is_finite_with_ecg_present():
    """An ECG channel must yield a real T-wave amplitude, not NaN."""
    vals = _twave_column(_session_with_ecg(t_amp=0.3))
    assert vals.shape == (1,)
    assert np.isfinite(vals[0]), "twave_amplitude is NaN despite an ECG channel"
    # Baseline is ~0 and the T-wave peak is 0.3, so the recovered amplitude
    # should land near 0.3 (well above the R-spike-free baseline).
    assert 0.15 < vals[0] < 0.4


def test_twave_amplitude_tracks_t_wave_height():
    """A taller T-wave gives a larger amplitude."""
    small = _twave_column(_session_with_ecg(t_amp=0.2))[0]
    large = _twave_column(_session_with_ecg(t_amp=0.6))[0]
    assert large > small + 0.2


def test_twave_amplitude_nan_without_ecg():
    """No ECG channel -> NaN (documented behaviour)."""
    peaks = np.arange(0.5, 30.0, 0.8)
    s = Session(
        name="n",
        events={"hrv": Events(peaks, np.full(peaks.shape, "N", object))},
        epochs={"whole": Epoch("whole", 0.0, 30.0, True)},
    )
    assert np.isnan(_twave_column(s)[0])
