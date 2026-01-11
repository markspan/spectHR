import numpy as np
import pytest

from spectHR.DataSet.Series.TimeSeries import TimeSeries, TimeSeriesView


# ---------------------------------------------------------
# Construction & validation
# ---------------------------------------------------------

def test_timeseries_basic_construction():
    ts = TimeSeries(times=[0.0, 1.0, 2.0], values=[10.0, 20.0, 30.0])

    assert isinstance(ts.times, np.ndarray)
    assert isinstance(ts.values, np.ndarray)
    assert ts.times.dtype == float
    assert ts.values.dtype == float
    assert ts.times.shape == ts.values.shape


def test_timeseries_length_mismatch_raises():
    with pytest.raises(ValueError, match="same length"):
        TimeSeries(times=[0.0, 1.0], values=[1.0])


def test_timeseries_empty_allowed():
    ts = TimeSeries(times=[], values=[])

    assert ts.times.size == 0
    assert ts.values.size == 0


# ---------------------------------------------------------
# Flip
# ---------------------------------------------------------

def test_flip_inverts_values():
    ts = TimeSeries(times=[0.0, 1.0, 2.0], values=[1.0, -2.0, 3.0])

    ts.flip()

    np.testing.assert_allclose(ts.values, [-1.0, 2.0, -3.0])


# ---------------------------------------------------------
# Sampling rate
# ---------------------------------------------------------

def test_srate_regular_sampling():
    ts = TimeSeries(times=[0.0, 0.5, 1.0, 1.5], values=[1, 2, 3, 4])

    assert ts.srate == pytest.approx(2.0)


def test_srate_irregular_sampling():
    ts = TimeSeries(times=[0.0, 0.4, 1.1], values=[1, 2, 3])

    expected = 1.0 / np.mean([0.4, 0.7])
    assert ts.srate == pytest.approx(expected)


def test_srate_single_sample():
    ts = TimeSeries(times=[0.0], values=[1.0])

    assert ts.srate is None


def test_srate_non_increasing_times():
    ts = TimeSeries(times=[1.0, 1.0, 1.0], values=[1, 2, 3])

    assert ts.srate is None


# ---------------------------------------------------------
# View creation
# ---------------------------------------------------------

def test_view_full_range():
    ts = TimeSeries(times=[0.0, 1.0, 2.0], values=[10, 20, 30])

    view = ts.view()

    assert isinstance(view, TimeSeriesView)
    assert len(view) == 3
    np.testing.assert_allclose(view.times, ts.times)
    np.testing.assert_allclose(view.values, ts.values)


def test_view_time_slice():
    ts = TimeSeries(times=[0.0, 1.0, 2.0, 3.0], values=[10, 20, 30, 40])

    view = ts.view(1.0, 2.0)

    np.testing.assert_allclose(view.times, [1.0, 2.0])
    np.testing.assert_allclose(view.values, [20.0, 30.0])


def test_view_empty_timeseries():
    ts = TimeSeries(times=[], values=[])

    view = ts.view()

    assert isinstance(view, TimeSeriesView)
    assert len(view) == 0


# ---------------------------------------------------------
# View semantics (shared storage)
# ---------------------------------------------------------

def test_view_getitem():
    ts = TimeSeries(times=[0.0, 1.0, 2.0], values=[10, 20, 30])
    view = ts.view(1.0, 2.0)

    assert view[0] == 20.0
    assert view[1] == 30.0


def test_view_setitem_updates_parent():
    ts = TimeSeries(times=[0.0, 1.0, 2.0], values=[10.0, 20.0, 30.0])
    view = ts.view(1.0, 2.0)

    view[0] = 99.0

    assert ts.values[1] == 99.0
    assert view.values[0] == 99.0


def test_view_length():
    ts = TimeSeries(times=[0.0, 1.0, 2.0], values=[10, 20, 30])
    view = ts.view(0.0, 1.0)

    assert len(view) == 2


def test_view_repr():
    ts = TimeSeries(times=[0.0, 1.0], values=[10, 20])
    view = ts.view()

    assert "TimeSeriesView" in repr(view)
