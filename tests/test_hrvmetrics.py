import warnings
import pytest
import numpy as np

from spectHR.DataSet.HRVMetrics import hrv_metric, HRVMetric


# ---------------------------------------------------------
# TEST FIXTURES / DUMMY CLASSES
# ---------------------------------------------------------

class DummySeries(HRVMetric):
    """
    Minimal concrete class implementing HRVMetric.
    """

    def __init__(self, data):
        self.data = np.asarray(data)

    def view(self, start, end):
        """
        Simple epoch slicing by index for testing.
        """
        return DummySeries(self.data[start:end])

    @hrv_metric
    def mean(self):
        return float(np.mean(self.data))

    @hrv_metric
    def std(self):
        return float(np.std(self.data))


class NoViewSeries(HRVMetric):
    """
    Class without .view() to test error handling.
    """

    @hrv_metric
    def constant(self):
        return 1.0


# ---------------------------------------------------------
# DECORATOR TESTS
# ---------------------------------------------------------

def test_hrv_metric_sets_flag():
    def fn(self):
        return 0.0

    decorated = hrv_metric(fn)
    assert hasattr(decorated, "_is_hrv_metric")
    assert decorated._is_hrv_metric is True


# ---------------------------------------------------------
# METRIC DISCOVERY
# ---------------------------------------------------------

def test_get_metric_functions_finds_only_decorated():
    metrics = DummySeries.get_metric_functions()

    assert "mean" in metrics
    assert "std" in metrics
    assert callable(metrics["mean"])
    assert callable(metrics["std"])


def test_get_metric_functions_returns_dict():
    metrics = DummySeries.get_metric_functions()
    assert isinstance(metrics, dict)


# ---------------------------------------------------------
# FULL-SERIES METRIC TABLE
# ---------------------------------------------------------

def test_metric_table_computation():
    data = [1, 2, 3, 4]
    series = DummySeries(data)

    table = series.metric_table()

    assert isinstance(table, dict)
    assert set(table.keys()) == {"mean", "std"}

    np.testing.assert_allclose(table["mean"], np.mean(data))
    np.testing.assert_allclose(table["std"], np.std(data))


def test_metric_table_returns_floats():
    series = DummySeries([1, 2, 3])
    table = series.metric_table()

    for value in table.values():
        assert isinstance(value, float)


# ---------------------------------------------------------
# EPOCH METRIC TABLE
# ---------------------------------------------------------

def test_metric_table_epoch_computation():
    data = [1, 2, 3, 4, 5]
    series = DummySeries(data)

    table = series.metric_table_epoch(1, 4)  # [2,3,4]

    expected = np.array([2, 3, 4])

    np.testing.assert_allclose(table["mean"], np.mean(expected))
    np.testing.assert_allclose(table["std"], np.std(expected))


def test_metric_table_epoch_returns_new_view():
    series = DummySeries([10, 20, 30])
    table = series.metric_table_epoch(0, 1)

    assert table["mean"] == 10.0


# ---------------------------------------------------------
# ERROR HANDLING
# ---------------------------------------------------------

def test_metric_table_epoch_requires_view():
    obj = NoViewSeries()

    with pytest.raises(AttributeError, match="must implement .view"):
        obj.metric_table_epoch(0, 1)


# ---------------------------------------------------------
# EDGE CASES
# ---------------------------------------------------------
import warnings
def test_empty_data_handling():
    series = DummySeries([])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        table = series.metric_table()

    assert np.isnan(table["mean"])
    assert np.isnan(table["std"])


def test_single_value_data():
    series = DummySeries([42])

    table = series.metric_table()

    assert table["mean"] == 42.0
    assert table["std"] == 0.0
