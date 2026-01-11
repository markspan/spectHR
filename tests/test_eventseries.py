import numpy as np
import pytest

from spectHR.DataSet.Series.EventSeries import EventSeries


# ---------------------------------------------------------
# Valid construction
# ---------------------------------------------------------

def test_eventseries_basic_construction():
    times = [0.1, 1.5, 2.7]
    labels = ["start", "stop", "marker"]

    ev = EventSeries(times=times, labels=labels)

    assert isinstance(ev.times, np.ndarray)
    assert ev.times.dtype == float
    assert ev.times.ndim == 1
    assert ev.labels == labels


def test_times_converted_to_numpy_array():
    ev = EventSeries(times=[1, 2, 3], labels=["a", "b", "c"])
    assert isinstance(ev.times, np.ndarray)
    np.testing.assert_array_equal(ev.times, np.array([1.0, 2.0, 3.0]))


# ---------------------------------------------------------
# Error handling
# ---------------------------------------------------------

def test_times_must_be_1d():
    times = [[0.0, 1.0], [2.0, 3.0]]
    labels = ["a", "b"]

    with pytest.raises(ValueError, match="1-D"):
        EventSeries(times=times, labels=labels)


def test_times_and_labels_length_must_match():
    times = [0.0, 1.0, 2.0]
    labels = ["a", "b"]

    with pytest.raises(ValueError, match="same length"):
        EventSeries(times=times, labels=labels)


# ---------------------------------------------------------
# Edge cases
# ---------------------------------------------------------

def test_empty_eventseries():
    ev = EventSeries(times=[], labels=[])

    assert ev.times.size == 0
    assert ev.labels == []


def test_single_event():
    ev = EventSeries(times=[5.0], labels=["trigger"])

    assert ev.times.size == 1
    assert ev.labels == ["trigger"]
