# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for spectHR.session.

Coverage:
  Samples, immutability, windowing, srate, with_values
  Events, immutability, windowing, ibi caching, of(), replace_window
  Intervals, immutability, windowing (overlap semantics), of(), windows_of()
  Session, scoped_to(), epochs_table() shape and values
"""
from __future__ import annotations

import numpy as np
import pytest

from spectHR.session import (
    AnalysisConfig,
    Epoch,
    Events,
    Intervals,
    MetricsTable,
    Samples,
    Session,
)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_samples(n: int = 1000, srate: float = 500.0, name: str = "ecg") -> Samples:
    times  = np.arange(n, dtype=np.float64) / srate
    values = np.sin(2 * np.pi * 1.0 * times)
    return Samples(times=times, values=values, name=name)


def make_events(n_beats: int = 250, mean_ibi_ms: float = 800.0, seed: int = 0) -> Events:
    rng = np.random.default_rng(seed)
    ibi_ms = mean_ibi_ms + rng.normal(0, 25, n_beats)
    ibi_s  = np.clip(ibi_ms, 400, 1500) / 1000.0
    times  = np.concatenate([[0.0], np.cumsum(ibi_s)])
    labels = np.full(times.size, "N", dtype=object)
    return Events(times=times, labels=labels)


def make_intervals(n_cycles: int = 30, cycle_s: float = 4.0) -> Intervals:
    """30 INH/EXH pairs with 2 s each phase."""
    half = cycle_s / 2.0
    n    = n_cycles * 2
    starts = np.array([i * half for i in range(n)], dtype=np.float64)
    ends   = starts + half
    labels = np.array(["INH" if i % 2 == 0 else "EXH" for i in range(n)], dtype=object)
    return Intervals(starts=starts, ends=ends, labels=labels)


def make_session(n_beats: int = 300, seed: int = 7) -> Session:
    hrv    = make_events(n_beats, seed=seed)
    breath = make_intervals(n_cycles=40)
    t_end  = float(hrv.times[-1])
    mid    = t_end / 2.0
    return Session(
        name="test",
        events={"hrv": hrv},
        intervals={"breath": breath},
        epochs={
            "A": Epoch("A", start=0.0, end=mid,   active=True),
            "B": Epoch("B", start=mid, end=t_end, active=True),
            "C": Epoch("C", start=0.0, end=t_end, active=False),  # excluded
        },
    )


# ===========================================================================
# Samples
# ===========================================================================

class TestSamples:

    def test_arrays_are_read_only(self):
        sig = make_samples()
        with pytest.raises((ValueError, TypeError)):
            sig.times[0] = 99.0
        with pytest.raises((ValueError, TypeError)):
            sig.values[0] = 99.0

    def test_window_returns_same_type(self):
        sig = make_samples()
        w = sig.window(0.1, 0.5)
        assert isinstance(w, Samples)

    def test_window_bounds(self):
        sig = make_samples(n=1000, srate=500.0)
        w = sig.window(0.2, 0.8)
        assert float(w.times[0])  >= 0.2
        assert float(w.times[-1]) <= 0.8

    def test_window_is_zero_copy(self):
        sig = make_samples()
        w   = sig.window(0.0, 0.5)
        assert np.shares_memory(sig.times, w.times)
        assert np.shares_memory(sig.values, w.values)

    def test_window_result_is_read_only(self):
        w = make_samples().window(0.0, 0.5)
        with pytest.raises((ValueError, TypeError)):
            w.times[0] = 0.0

    def test_chained_window(self):
        sig = make_samples(n=1000, srate=500.0)
        w1  = sig.window(0.0, 1.0)
        w2  = w1.window(0.2, 0.8)
        assert float(w2.times[0])  >= 0.2
        assert float(w2.times[-1]) <= 0.8

    def test_srate(self):
        sig = make_samples(n=1001, srate=500.0)
        assert sig.srate == pytest.approx(500.0, rel=0.01)

    def test_srate_too_short(self):
        sig = Samples(times=np.array([0.0]), values=np.array([1.0]))
        assert sig.srate is None

    def test_with_values(self):
        sig  = make_samples()
        sig2 = sig.with_values(sig.values * 2.0)
        np.testing.assert_array_equal(sig2.times, sig.times)
        np.testing.assert_allclose(sig2.values, sig.values * 2.0)

    def test_empty_window(self):
        sig = make_samples(n=100, srate=100.0)
        w   = sig.window(5.0, 5.5)   # outside the recording
        assert w.times.size == 0
        assert w.values.size == 0


# ===========================================================================
# Events
# ===========================================================================

class TestEvents:

    def test_arrays_are_read_only(self):
        ev = make_events()
        with pytest.raises((ValueError, TypeError)):
            ev.times[0] = 0.0
        with pytest.raises((ValueError, TypeError)):
            ev.labels[0] = "X"

    def test_window_returns_same_type(self):
        ev = make_events()
        w  = ev.window(10.0, 50.0)
        assert isinstance(w, Events)

    def test_window_containment(self):
        ev = make_events()
        w  = ev.window(10.0, 50.0)
        assert np.all(w.times >= 10.0)
        assert np.all(w.times <= 50.0)

    def test_window_is_zero_copy(self):
        ev = make_events()
        w  = ev.window(0.0, ev.times[-1] / 2.0)
        assert np.shares_memory(ev.times, w.times)
        assert np.shares_memory(ev.labels, w.labels)

    def test_chained_window(self):
        ev = make_events()
        w1 = ev.window(0.0, 100.0)
        w2 = w1.window(20.0, 60.0)
        assert np.all(w2.times >= 20.0)
        assert np.all(w2.times <= 60.0)

    def test_ibi_length_and_trailing_nan(self):
        ev = make_events(n_beats=10)
        assert ev.ibi.size == ev.times.size
        assert np.isnan(ev.ibi[-1])
        assert np.all(ev.ibi[:-1] > 0)

    def test_ibi_is_cached(self):
        ev = make_events()
        assert ev.ibi is ev.ibi   # same object → cached

    def test_ibi_single_event(self):
        ev = Events(times=np.array([1.0]), labels=np.array(["N"], dtype=object))
        assert ev.ibi.size == 1
        assert np.isnan(ev.ibi[0])

    def test_of_filters_label(self):
        ev = make_events(n_beats=20)
        # Inject a few artefact labels
        labels = ev.labels.copy()
        labels[3] = "A"
        labels[7] = "A"
        ev2 = ev.with_labels(labels)
        normal = ev2.of("N")
        artef  = ev2.of("A")
        assert artef.times.size == 2
        assert normal.times.size + artef.times.size == ev2.times.size

    def test_with_labels(self):
        ev  = make_events(n_beats=5)
        new = np.array(["N", "V", "N", "N", "N", "N"], dtype=object)
        ev2 = ev.with_labels(new)
        assert ev2.labels[1] == "V"
        assert all(l == "N" for l in ev.labels)   # original unchanged

    def test_replace_window(self):
        ev = make_events(n_beats=100)
        n_orig = ev.times.size
        win_start, win_end = 20.0, 30.0
        n_in = int(np.sum((ev.times >= win_start) & (ev.times <= win_end)))
        replacement = Events(
            times=np.array([22.0, 25.0, 28.0], dtype=np.float64),
            labels=np.array(["N", "V", "N"], dtype=object),
        )
        ev2 = ev.replace_window(win_start, win_end, replacement)
        assert ev2.times.size == n_orig - n_in + 3
        assert np.all(np.diff(ev2.times) > 0)     # still sorted

    def test_empty_window_ibi(self):
        ev = make_events()
        w  = ev.window(1000.0, 2000.0)   # outside recording
        assert w.ibi.size == 1
        assert np.isnan(w.ibi[0])


# ===========================================================================
# Intervals
# ===========================================================================

class TestIntervals:

    def test_arrays_are_read_only(self):
        iv = make_intervals()
        with pytest.raises((ValueError, TypeError)):
            iv.starts[0] = 0.0

    def test_len(self):
        iv = make_intervals(n_cycles=10)
        assert len(iv) == 20   # 2 phases per cycle

    def test_window_returns_same_type(self):
        iv = make_intervals()
        w  = iv.window(10.0, 30.0)
        assert isinstance(w, Intervals)

    def test_window_includes_overlapping_phases(self):
        iv = make_intervals()
        w  = iv.window(10.0, 30.0)
        # Every included phase overlaps [10, 30]
        assert np.all(w.ends   >= 10.0)
        assert np.all(w.starts <= 30.0)

    def test_window_is_zero_copy(self):
        iv = make_intervals(n_cycles=50)
        w  = iv.window(10.0, 50.0)
        assert np.shares_memory(iv.starts, w.starts)

    def test_window_full_coverage(self):
        iv = make_intervals(n_cycles=5)   # 10 phases × 2 s = 20 s total
        w  = iv.window(0.0, 20.0)
        assert len(w) == 10

    def test_of_label(self):
        iv  = make_intervals(n_cycles=10)
        inh = iv.of("INH")
        exh = iv.of("EXH")
        assert len(inh) == 10
        assert len(exh) == 10
        assert np.all(inh.labels == "INH")

    def test_windows_of_yields_pairs(self):
        iv   = make_intervals(n_cycles=5)
        wins = list(iv.windows_of("INH"))
        assert len(wins) == 5
        for t0, t1 in wins:
            assert t1 > t0

    def test_windows_of_iteration_pattern(self):
        """Show the intended per-phase computation pattern."""
        ev = make_events(n_beats=200, mean_ibi_ms=800.0, seed=1)
        iv = make_intervals(n_cycles=20)

        # Compute mean IBI within each INH phase, the natural pattern
        means = []
        for t0, t1 in iv.windows_of("INH"):
            phase_beats = ev.window(t0, t1)
            if phase_beats.ibi.size > 1:
                means.append(float(np.nanmean(phase_beats.ibi[:-1])))

        assert len(means) > 0
        assert all(0.4 < m < 1.5 for m in means)   # physiological

    def test_empty_window(self):
        iv = make_intervals()
        w  = iv.window(1000.0, 2000.0)   # outside recording
        assert len(w) == 0


# ===========================================================================
# Session
# ===========================================================================

class TestSession:

    def test_hrv_property(self):
        s = make_session()
        assert s.hrv is s.events["hrv"]

    def test_breath_property(self):
        s = make_session()
        assert s.breath is s.intervals["breath"]

    def test_missing_channel_returns_none(self):
        s = make_session()
        assert s.ecg is None
        assert s.bp  is None

    def test_scoped_to_windows_all_channels(self):
        s    = make_session()
        ep   = s.scoped_to("A")
        epoch = s.epochs["A"]
        assert np.all(ep.events["hrv"].times  >= epoch.start)
        assert np.all(ep.events["hrv"].times  <= epoch.end)
        assert np.all(ep.intervals["breath"].starts <= epoch.end)
        assert np.all(ep.intervals["breath"].ends   >= epoch.start)

    def test_scoped_to_has_no_epochs(self):
        s  = make_session()
        ep = s.scoped_to("A")
        assert ep.epochs == {}

    def test_scoped_to_is_zero_copy(self):
        s  = make_session()
        ep = s.scoped_to("A")
        # Windowed arrays are views into the originals
        assert np.shares_memory(s.events["hrv"].times, ep.events["hrv"].times)

    def test_epochs_table_excludes_inactive(self):
        s   = make_session()
        tbl = s.epochs_table()
        assert "C" not in tbl.labels.tolist()
        assert set(tbl.labels.tolist()) == {"A", "B"}

    def test_epochs_table_shape(self):
        s   = make_session()
        tbl = s.epochs_table()
        assert isinstance(tbl, MetricsTable)
        assert tbl.values.shape == (2, len(tbl.columns))

    def test_epochs_table_contexts_are_windowed(self):
        s   = make_session()
        tbl = s.epochs_table()
        for label, ctx in tbl.contexts.items():
            epoch = s.epochs[label]
            assert np.all(ctx.view.times >= epoch.start)
            assert np.all(ctx.view.times <= epoch.end)

    def test_epochs_table_finite_scalars(self):
        s   = make_session()
        tbl = s.epochs_table()
        # Time-domain metrics on clean N-labelled IBIs should all be finite
        time_cols = ["count", "mean", "rmssd", "sdnn"]
        for col in time_cols:
            if col in tbl.columns:
                idx  = tbl.columns.index(col)
                vals = tbl.values[:, idx]
                assert np.all(np.isfinite(vals)), f"{col} has non-finite values"

    def test_epochs_table_mean_ibi_range(self):
        s   = make_session()
        tbl = s.epochs_table()
        idx  = tbl.columns.index("mean")
        vals = tbl.values[:, idx]
        # Synthetic IBIs ~800 ms
        assert np.all(vals > 600) and np.all(vals < 1000)

    def test_epochs_table_no_active_epochs(self):
        hrv = make_events(50)
        s   = Session(
            name="empty",
            events={"hrv": hrv},
            epochs={"A": Epoch("A", 0, 10, active=False)},
        )
        tbl = s.epochs_table()
        assert tbl.values.shape[0] == 0

    def test_epochs_table_no_hrv(self):
        s   = Session(name="no_hrv", epochs={"A": Epoch("A", 0, 10, active=True)})
        tbl = s.epochs_table()
        assert tbl.columns == []

    def test_epochs_table_with_psd(self):
        from spectHR.analysis.psd import BandSpec, PsdMethod
        bands  = {"FullRange": BandSpec(0.02, 0.5), "HF": BandSpec(0.15, 0.4)}
        method = PsdMethod(algorithm="welch", bands=bands)
        config = AnalysisConfig(psd_method=method)

        rng   = np.random.default_rng(42)
        ibi_s = 0.8 + rng.normal(0, 0.03, 500)
        times = np.concatenate([[0.0], np.cumsum(np.clip(ibi_s, 0.4, 1.5))])
        hrv   = Events(times=times, labels=np.full(times.size, "N", dtype=object))
        s     = Session(
            name="psd_test",
            events={"hrv": hrv},
            epochs={"A": Epoch("A", 0.0, float(times[-1]), active=True)},
        )
        tbl = s.epochs_table(config)
        if "hf_power" in tbl.columns:
            idx = tbl.columns.index("hf_power")
            assert np.isfinite(tbl.values[0, idx])

    def test_phase_metric_via_scoped_to(self):
        """Demonstrate per-phase computation using scoped_to + windows_of."""
        s  = make_session()
        ep = s.scoped_to("A")
        breath = ep.intervals.get("breath")
        if breath is None or not any(True for _ in breath.windows_of("INH")):
            pytest.skip("no breath phases in epoch A")

        per_breath_means = []
        for t0, t1 in breath.windows_of("INH"):
            beats = ep.events["hrv"].window(t0, t1)
            ibi   = beats.ibi
            valid = ibi[np.isfinite(ibi)]
            if valid.size > 0:
                per_breath_means.append(float(valid.mean()))

        assert len(per_breath_means) > 0
        assert all(0.4 < m < 1.5 for m in per_breath_means)
