import numpy as np
import pytest

from spectHR.DataSet.Series.RespirationSeries import RespirationSeries


class DummyRespTS:
    """Minimal TimeSeries stub for respiration."""
    def __init__(self, times, values):
        self.times = np.asarray(times, dtype=float)
        self.values = np.asarray(values, dtype=float)


def synthetic_rsp_signal(duration=20.0, fs=10.0):
    t = np.arange(0, duration, 1 / fs)
    rsp = np.sin(2 * np.pi * 0.25 * t)  # slow breathing
    return t, rsp


# ---------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------

def test_respirationseries_construction_runs():
    t, rsp = synthetic_rsp_signal()
    ts = DummyRespTS(t, rsp)

    rs = RespirationSeries.from_timeseries(ts)

    assert rs is not None
    assert hasattr(rs, "phases")


def test_respirationseries_phases_have_required_fields():
    t, rsp = synthetic_rsp_signal()
    ts = DummyRespTS(t, rsp)

    rs = RespirationSeries.from_timeseries(ts)

    for phase in rs.phases:
        assert hasattr(phase, "start")
        assert hasattr(phase, "end")
        assert hasattr(phase, "label")
        assert phase.start < phase.end


# ---------------------------------------------------------------------
# Phase semantics
# ---------------------------------------------------------------------

def test_respiration_phases_within_signal_range():
    t, rsp = synthetic_rsp_signal()
    ts = DummyRespTS(t, rsp)

    rs = RespirationSeries.from_timeseries(ts)

    for phase in rs.phases:
        assert phase.start >= t.min()
        assert phase.end <= t.max()


def test_respiration_labels_are_categorical():
    t, rsp = synthetic_rsp_signal()
    ts = DummyRespTS(t, rsp)

    rs = RespirationSeries.from_timeseries(ts)

    valid_labels = {"INH", "EXH"}
    for phase in rs.phases:
        assert phase.label in valid_labels


# ---------------------------------------------------------------------
# View semantics
# ---------------------------------------------------------------------

def test_respiration_view_by_time():
    t, rsp = synthetic_rsp_signal()
    ts = DummyRespTS(t, rsp)

    rs = RespirationSeries.from_timeseries(ts)
    view = rs.view(5.0, 10.0)

    for phase in view.phases:
        assert phase.end >= 5.0
        assert phase.start <= 10.0


def test_respiration_view_is_zero_copy():
    t, rsp = synthetic_rsp_signal()
    ts = DummyRespTS(t, rsp)

    rs = RespirationSeries.from_timeseries(ts)
    view = rs.view(5.0, 10.0)

    # Mutate parent → view should reflect it
    if rs.phases:
        rs.phases[0].label = "TEST"
        assert view.phases[0].label == "TEST"


# ---------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------

def test_respirationseries_handles_short_signal():
    t = np.array([0.0, 0.1])
    rsp = np.array([0.0, 0.1])
    ts = DummyRespTS(t, rsp)

    rs = RespirationSeries.from_timeseries(ts)

    # No phases is acceptable
    assert hasattr(rs, "phases")


def test_respirationseries_handles_flat_signal():
    t = np.linspace(0, 10, 100)
    rsp = np.zeros_like(t)
    ts = DummyRespTS(t, rsp)

    rs = RespirationSeries.from_timeseries(ts)

    # No crash; phases may be empty
    assert hasattr(rs, "phases")
