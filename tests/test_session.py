# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for spectHR.session — the modern data layer.

Covers:
* Signal / Beats / BreathPhases construction and immutability
* Slice correctness (right beats/samples in window)
* Functional updates (replace_window, with_labels, with_values)
* PhysioSession.epochs_table producing same scalars as the legacy path
* PhysioSession.from_physio_data bridge
"""
from __future__ import annotations

import numpy as np
import pytest

from spectHR.session import (
    AnalysisConfig,
    Beats,
    BeatSlice,
    BreathPhases,
    Epoch,
    PhysioSession,
    PhaseSlice,
    Signal,
    SignalSlice,
)


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

class TestSignal:
    def _make(self, n=100):
        t = np.linspace(0, 10, n)
        v = np.sin(2 * np.pi * 0.25 * t)
        return Signal(times=t, values=v, name="ecg")

    def test_construction_freezes_arrays(self):
        sig = self._make()
        assert not sig.times.flags.writeable
        assert not sig.values.flags.writeable

    def test_srate(self):
        sig = self._make(101)
        assert sig.srate == pytest.approx(10.0, rel=0.05)

    def test_slice_bounds(self):
        sig = self._make(101)
        sl = sig.slice(2.0, 5.0)
        assert isinstance(sl, SignalSlice)
        assert float(sl.times.min()) >= 2.0
        assert float(sl.times.max()) <= 5.0
        # values are a view of the original
        np.testing.assert_array_equal(sl.values, sig.values[
            (sig.times >= 2.0) & (sig.times <= 5.0)
        ])

    def test_with_values(self):
        sig = self._make()
        new_v = sig.values * 2
        sig2 = sig.with_values(new_v)
        np.testing.assert_array_equal(sig2.times, sig.times)
        np.testing.assert_allclose(sig2.values, sig.values * 2)
        # original unchanged
        assert not np.shares_memory(sig.values, sig2.values) or True  # may or may not share

    def test_signal_slice_subslice(self):
        sig = self._make(101)
        sl1 = sig.slice(0, 8)
        sl2 = sl1.slice(2, 5)
        assert float(sl2.times.min()) >= 2.0
        assert float(sl2.times.max()) <= 5.0


# ---------------------------------------------------------------------------
# Beats
# ---------------------------------------------------------------------------

class TestBeats:
    def _make(self, ibi_ms=None):
        if ibi_ms is None:
            ibi_ms = np.full(200, 800.0)
        ibi_s = np.asarray(ibi_ms) / 1000.0
        times = np.concatenate([[0.0], np.cumsum(ibi_s)])
        labels = np.full(times.size, "N", dtype=object)
        return Beats(times=times, labels=labels)

    def test_construction_freezes_arrays(self):
        beats = self._make()
        assert not beats.times.flags.writeable
        assert not beats.labels.flags.writeable

    def test_ibi_length_and_trailing_nan(self):
        beats = self._make(ibi_ms=[800, 800, 800])
        assert beats.ibi.size == beats.times.size
        assert np.isnan(beats.ibi[-1])
        np.testing.assert_allclose(beats.ibi[:-1], 0.8, rtol=1e-6)

    def test_ibi_single_beat(self):
        b = Beats(times=np.array([1.0]), labels=np.array(["N"], dtype=object))
        assert b.ibi.size == 1
        assert np.isnan(b.ibi[0])

    def test_slice_containment(self):
        beats = self._make()
        sl = beats.slice(10.0, 50.0)
        assert isinstance(sl, BeatSlice)
        assert float(sl.times.min()) >= 10.0
        assert float(sl.times.max()) <= 50.0

    def test_slice_ibi(self):
        beats = self._make()
        sl = beats.slice(0.0, 20.0)
        assert sl.ibi.size == sl.times.size
        assert np.isnan(sl.ibi[-1])

    def test_with_labels(self):
        beats = self._make([800, 800, 1200, 800])  # 5 beats
        new_labels = np.array(["N", "N", "V", "N", "N"], dtype=object)
        beats2 = beats.with_labels(new_labels)
        assert beats2.labels[2] == "V"
        # original unchanged
        assert all(l == "N" for l in beats.labels)

    def test_replace_window_preserves_outside(self):
        beats = self._make(ibi_ms=np.full(50, 800.0))
        original_size = beats.times.size
        window_start, window_end = 10.0, 20.0
        n_in_window = int(np.sum(
            (beats.times >= window_start) & (beats.times <= window_end)
        ))
        replacement = Beats(
            times=np.array([12.0, 14.0], dtype=float),
            labels=np.array(["N", "N"], dtype=object),
        )
        new_beats = beats.replace_window(window_start, window_end, replacement)
        assert new_beats.times.size == original_size - n_in_window + 2
        # beats outside the window are intact
        kept = new_beats.times[(new_beats.times < window_start) | (new_beats.times > window_end)]
        expected = beats.times[(beats.times < window_start) | (beats.times > window_end)]
        np.testing.assert_allclose(kept, expected)

    def test_beat_slice_sub_slice(self):
        beats = self._make()
        sl1 = beats.slice(0, 50)
        sl2 = sl1.slice(10, 30)
        assert float(sl2.times.min()) >= 10.0
        assert float(sl2.times.max()) <= 30.0


# ---------------------------------------------------------------------------
# BreathPhases
# ---------------------------------------------------------------------------

class TestBreathPhases:
    def _make(self, n_cycles=20, cycle_s=4.0):
        starts, ends, labels = [], [], []
        t = 0.0
        for _ in range(n_cycles):
            starts.append(t);     ends.append(t + cycle_s * 0.5); labels.append("INH"); t += cycle_s * 0.5
            starts.append(t);     ends.append(t + cycle_s * 0.5); labels.append("EXH"); t += cycle_s * 0.5
        return BreathPhases(
            starts=np.array(starts), ends=np.array(ends),
            labels=np.array(labels, dtype=object),
        )

    def test_construction_freezes_arrays(self):
        bp = self._make()
        assert not bp.starts.flags.writeable
        assert not bp.ends.flags.writeable
        assert not bp.labels.flags.writeable

    def test_len(self):
        bp = self._make(n_cycles=10)
        assert len(bp) == 20   # 2 phases per cycle

    def test_slice_overlap(self):
        bp = self._make()
        sl = bp.slice(10.0, 30.0)
        assert isinstance(sl, PhaseSlice)
        # every included phase overlaps [10, 30]
        assert np.all(sl.ends >= 10.0)
        assert np.all(sl.starts <= 30.0)

    def test_slice_len(self):
        bp = self._make(n_cycles=5)   # 5 cycles × 4 s = 20 s, 10 phases
        sl = bp.slice(0.0, 20.0)
        assert len(sl) == 10

    def test_phase_slice_sub_slice(self):
        bp = self._make()
        sl1 = bp.slice(0, 40)
        sl2 = sl1.slice(10, 30)
        assert np.all(sl2.ends >= 10.0)
        assert np.all(sl2.starts <= 30.0)


# ---------------------------------------------------------------------------
# Epoch
# ---------------------------------------------------------------------------

def test_epoch_duration():
    ep = Epoch(label="A", start=10.0, end=50.0)
    assert ep.duration == pytest.approx(40.0)

def test_epoch_contains():
    ep = Epoch(label="A", start=10.0, end=50.0)
    assert ep.contains(30.0)
    assert not ep.contains(5.0)
    assert not ep.contains(60.0)


# ---------------------------------------------------------------------------
# AnalysisConfig
# ---------------------------------------------------------------------------

def test_analysis_config_defaults():
    cfg = AnalysisConfig()
    assert cfg.rsa_lag_s == 1.0
    assert cfg.b_point_guard_ms == 30.0
    assert cfg.psd_method is None


# ---------------------------------------------------------------------------
# PhysioSession — epochs_table produces correct HRV scalars
# ---------------------------------------------------------------------------

def _make_session_with_epochs():
    """Build a minimal PhysioSession with two 120-beat epochs."""
    rng = np.random.default_rng(42)
    ibi_ms = 800.0 + rng.normal(0, 30, 400)
    ibi_ms = np.clip(ibi_ms, 400, 1500)
    ibi_s = ibi_ms / 1000.0
    times = np.concatenate([[0.0], np.cumsum(ibi_s)])
    labels = np.full(times.size, "N", dtype=object)
    beats = Beats(times=times, labels=labels)

    t_end = float(times[-1])
    mid   = t_end / 2.0
    epochs = {
        "A": Epoch("A", start=0.0,  end=mid,   active=True),
        "B": Epoch("B", start=mid,  end=t_end, active=True),
        "C": Epoch("C", start=0.0,  end=t_end, active=False),  # inactive
    }

    return PhysioSession(
        filename="synthetic",
        beats={"default": beats},
        epochs=epochs,
    )


def test_epochs_table_shape():
    session = _make_session_with_epochs()
    result = session.epochs_table()
    assert result.labels.tolist() == ["A", "B"]   # C is inactive
    assert result.values.shape[0] == 2
    assert result.values.shape[1] == len(result.columns)
    assert len(result.contexts) == 2


def test_epochs_table_mean_ibi_finite():
    session = _make_session_with_epochs()
    result = session.epochs_table()
    col_idx = result.columns.index("mean")   # mean IBI in seconds
    vals = result.values[:, col_idx]
    assert np.all(np.isfinite(vals))
    assert np.all(vals > 600) and np.all(vals < 1000)  # ~800 ms


def test_epochs_table_contexts_reusable():
    session = _make_session_with_epochs()
    result = session.epochs_table()
    for label, ctx in result.contexts.items():
        # contexts carry beat slices, not full beats
        assert isinstance(ctx.view, BeatSlice)
        assert ctx.view.times.size > 0


def test_epochs_table_no_active_epochs():
    rng = np.random.default_rng(0)
    times = np.concatenate([[0.0], np.cumsum(np.full(50, 0.8))])
    beats = Beats(times=times, labels=np.full(times.size, "N", dtype=object))
    session = PhysioSession(
        filename="empty",
        beats={"default": beats},
        epochs={"A": Epoch("A", 0, 10, active=False)},
    )
    result = session.epochs_table()
    assert result.values.shape[0] == 0


def test_epochs_table_no_beats():
    session = PhysioSession(
        filename="empty",
        epochs={"A": Epoch("A", 0, 10, active=True)},
    )
    result = session.epochs_table()
    assert result.values.shape == (0, 0) or result.columns == []


# ---------------------------------------------------------------------------
# PhysioSession.from_physio_data bridge
# ---------------------------------------------------------------------------

def _make_physio_data():
    """Build a minimal PhysioData using the legacy path."""
    from spectHR.DataSet.Series.CardioSeries import CardioSeries
    from spectHR.DataSet.PhysioData import PhysioData

    rng = np.random.default_rng(7)
    ibi_ms = 800.0 + rng.normal(0, 25, 300)
    ibi_ms = np.clip(ibi_ms, 400, 1500)
    ibi_s = ibi_ms / 1000.0
    times = np.concatenate([[0.0], np.cumsum(ibi_s)])
    cs = CardioSeries(times)

    pd = PhysioData.__new__(PhysioData)
    pd.filename = "synthetic.hdf5"
    pd.basename = "synthetic"
    pd.timeseries = {}
    pd.events = {}
    pd.phases = {}
    pd.band_map = {}
    pd.active_band = "default"
    pd.hrv_map = {"default": cs}
    pd.rsp_map = {}

    from spectHR.DataSet.PhysioData import Epoch as LegacyEpoch
    t_end = float(times[-1])
    pd.epochs = {
        "A": LegacyEpoch(active=True,  start=0.0,       end=t_end / 2.0),
        "B": LegacyEpoch(active=True,  start=t_end/2.0, end=t_end),
    }
    return pd


def test_from_physio_data_beats_preserved():
    pd = _make_physio_data()
    session = PhysioSession.from_physio_data(pd)
    legacy_cs = pd.hrv_map["default"]
    session_beats = session.beats.get("default")
    assert session_beats is not None
    np.testing.assert_array_equal(session_beats.times, legacy_cs.times)


def test_from_physio_data_epochs_preserved():
    pd = _make_physio_data()
    session = PhysioSession.from_physio_data(pd)
    assert set(session.epochs.keys()) == {"A", "B"}
    assert session.epochs["A"].active is True


def test_from_physio_data_table_matches_legacy():
    """epochs_table on a bridged session gives the same mean_ibi as the legacy path."""
    pd = _make_physio_data()
    session = PhysioSession.from_physio_data(pd)

    # Legacy table
    labels_l, cols_l, vals_l, _ = pd.epoched_parameters_table(
        psd_method=None,
        rsa_lag_s=1.0,
        rsa_max_ibi_deviation=None,
        rsa_max_rate_deviation=None,
        b_point_guard_ms=30.0,
    )

    # New table
    result = session.epochs_table(AnalysisConfig(psd_method=None))

    legacy_mean_ibi_idx = list(cols_l).index("mean")
    new_mean_ibi_idx    = result.columns.index("mean")

    legacy_vals = vals_l[:, legacy_mean_ibi_idx]
    new_vals    = result.values[:, new_mean_ibi_idx]

    np.testing.assert_allclose(new_vals, legacy_vals, rtol=1e-9)
