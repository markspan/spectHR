import numpy as np
import pytest

from spectHR.DataSet.Series.CardioSeries import CardioSeries, CardioSeriesView
from spectHR.DataSet.Epoch import Epoch


# ---------------------------------------------------------
# Minimal PhysioData stub (only what CardioSeries uses)
# ---------------------------------------------------------


class DummyPhysioData:
    def __init__(self):
        self.epochs = {
            "experiment": Epoch(active=True, start=0.0, end=10.0),
            "rest": Epoch(active=True, start=2.0, end=6.0),
            "inactive": Epoch(active=False, start=1.0, end=9.0),
        }


# ---------------------------------------------------------
# Fixtures
# ---------------------------------------------------------


@pytest.fixture
def cardio():
    times = np.array([0.0, 1.0, 2.0, 3.1, 4.0, 5.2, 6.0, 7.0])
    cs = CardioSeries(times)
    cs._pd = DummyPhysioData()
    return cs


# ---------------------------------------------------------
# IBI computation
# ---------------------------------------------------------


def test_ibi_computation(cardio):
    ibi = cardio.ibi
    assert ibi.size == cardio.times.size
    assert np.isnan(ibi[-1])
    np.testing.assert_allclose(ibi[:-1], np.diff(cardio.times))


def test_ibi_single_value():
    cs = CardioSeries(np.array([1.0]))
    assert cs.ibi.size == 0


def test_ibi_times_unchanged_after_classification(cardio):
    t0 = cardio.times.copy()
    cardio.classify_ibi()
    np.testing.assert_allclose(cardio.times, t0)


def test_tl_ibi_becomes_nan():
    # IBI = 9s → TL → NaN
    times = np.array([0.0, 1.0, 10.0])
    cs = CardioSeries(times)
    cs.classify_ibi(Tmax=5.0)

    assert cs.labels[1] == "TL"
    assert np.isnan(cs.ibi[1])


# ---------------------------------------------------------
# View semantics (epoch + window)
# ---------------------------------------------------------


def test_epoch_getitem(cardio):
    view = cardio["rest"]
    assert isinstance(view, CardioSeriesView)
    assert np.all(view.times >= 2.0)
    assert np.all(view.times <= 6.0)


def test_getitem_requires_pd():
    cs = CardioSeries(np.array([0.0, 1.0]))
    with pytest.raises(RuntimeError):
        cs["experiment"]


def test_getitem_missing_epoch(cardio):
    with pytest.raises(KeyError):
        cardio["does_not_exist"]


def test_view_method(cardio):
    view = cardio.view(1.0, 4.0)
    assert isinstance(view, CardioSeriesView)
    assert np.all(view.times >= 1.0)
    assert np.all(view.times <= 4.0)


# ---------------------------------------------------------
# HRV metrics
# ---------------------------------------------------------


def test_metric_table(cardio):
    table = cardio.metric_table()
    assert isinstance(table, dict)
    assert "mean" in table
    assert "sdnn" in table
    assert "rmssd" in table
    for v in table.values():
        assert isinstance(v, float)
        assert not np.isinf(v)


def test_metric_table_epoch(cardio):
    tbl = cardio.metric_table_epoch(2.0, 6.0)
    assert "count" in tbl
    assert tbl["count"] > 0


def test_metrics_insufficient_data():
    cs = CardioSeries(np.array([1.0]))
    tbl = cs.metric_table()
    assert tbl["count"] == 0
    assert np.isnan(tbl["mean"])
    assert np.isnan(tbl["std"])
    assert np.isnan(tbl["rmssd"])


# ---------------------------------------------------------
# Welch PSD
# ---------------------------------------------------------


def test_welch_psd_empty():
    cs = CardioSeries(np.array([0.0]))
    freqs, power = cs.welch_psd()
    assert freqs.size == 0
    assert power.size == 0


def test_welch_psd_basic(cardio):
    freqs, power = cardio.welch_psd()
    assert freqs.ndim == 1
    assert power.ndim == 1
    assert freqs.size == power.size


def test_welch_psd_with_ci(cardio):
    freqs, psd, lo, hi = cardio.welch_psd_with_ci()
    assert freqs.size == psd.size
    assert lo.size == psd.size
    assert hi.size == psd.size


def test_welch_psd_with_ci_empty():
    cs = CardioSeries(np.array([0.0]))
    freqs, psd, lo, hi = cs.welch_psd_with_ci()
    assert freqs.size == 0
    assert np.all(psd == lo)
    assert np.all(psd == hi)


# ---------------------------------------------------------
# Band power
# ---------------------------------------------------------


def test_band_power_empty():
    cs = CardioSeries(np.array([0.0]))
    freqs, power = cs.welch_psd()
    val = cs._band_power_exact(freqs, power, 0.04, 0.15)
    assert np.isnan(val)


# ---------------------------------------------------------
# Epoch HRV table
# ---------------------------------------------------------


def test_hrv_epoch_table(cardio):
    df = cardio.hrv_epoch_table(cardio._pd)
    assert isinstance(df, pd.DataFrame)
    assert "mean" in df.columns
    assert "count" in df.columns
    assert "inactive" not in df.index


def test_hrv_epoch_table_column_order(cardio):
    df = cardio.hrv_epoch_table(cardio._pd)
    expected = [c for c in cardio.METRIC_ORDER if c in df.columns]
    assert list(df.columns) == expected


# ---------------------------------------------------------
# CardioSeriesView specifics
# ---------------------------------------------------------


def test_view_inherits_pd(cardio):
    view = cardio["rest"]
    assert view._pd is cardio._pd


def test_view_ibi(cardio):
    view = cardio["rest"]
    ibi = view.ibi
    assert ibi.size == view.times.size
    assert np.isnan(ibi[-1])


def test_view_repr(cardio):
    view = cardio["rest"]
    r = repr(view)
    assert "CardioSeriesView" in r
    assert "start" in r or "[" in r
