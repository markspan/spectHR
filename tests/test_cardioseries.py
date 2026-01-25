import numpy as np
import pandas as pd
import pytest

from spectHR.DataSet.Series.CardioSeries import CardioSeries, CardioSeriesView


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

@pytest.fixture
def simple_times():
    # 1 Hz heart rate (1 second RR)
    return np.array([0.0, 1.0, 2.0, 3.0, 4.0])


@pytest.fixture
def cardio(simple_times):
    return CardioSeries(simple_times)


@pytest.fixture
def irregular_times():
    return np.array([0.0, 0.9, 2.1, 3.0, 5.5])


# ---------------------------------------------------------------------
# Construction & invariants
# ---------------------------------------------------------------------

def test_init_sets_times_and_labels(cardio):
    assert cardio.times.dtype == float
    assert cardio.labels.shape == cardio.times.shape
    assert np.all(cardio.labels == "N")


def test_empty_series():
    cs = CardioSeries(np.array([]))
    assert cs.times.size == 0
    assert cs.labels.size == 0
    assert cs.ibi.size == 0


# ---------------------------------------------------------------------
# IBI derivation & policy
# ---------------------------------------------------------------------

def test_ibi_alignment(simple_times):
    cs = CardioSeries(simple_times)
    ibi = cs.ibi

    assert len(ibi) == len(simple_times)
    assert np.isnan(ibi[-1])
    assert np.allclose(ibi[:-1], 1.0)


def test_ibi_marks_too_long_and_mutates_labels():
    times = np.array([0.0, 1.0, 4.5, 5.5])  # 3.5 s gap
    cs = CardioSeries(times)

    ibi = cs.ibi
    assert np.isnan(ibi[1])
    assert cs.labels[1] == "TL"


def test_ibi_single_sample():
    cs = CardioSeries(np.array([1.0]))
    ibi = cs.ibi
    assert ibi.size == 0


# ---------------------------------------------------------------------
# _ibi_clean_ms
# ---------------------------------------------------------------------

def test_ibi_clean_ms_excludes_nan():
    times = np.array([0.0, 1.0, 4.5, 5.5])
    cs = CardioSeries(times)

    ibi_ms = cs._ibi_clean_ms()
    assert ibi_ms.ndim == 1
    assert np.all(ibi_ms > 0)
    assert np.all(~np.isnan(ibi_ms))


# ---------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------

def test_classify_ibi_basic_runs(cardio):
    cardio.classify_ibi()
    assert set(cardio.labels).issubset(
        {"N", "L", "S", "TL", "SL", "SNS", "T"}
    )


def test_classify_handles_degenerate_intervals():
    times = np.array([0.0, 1.0, 1.0, 2.0])
    cs = CardioSeries(times)
    cs.classify_ibi()

    assert "T" in cs.labels


def test_sequence_labels_applied():
    # Artificial pattern: short, long
    times = np.array([0.0, 0.5, 2.0, 3.0])
    cs = CardioSeries(times)
    cs.classify_ibi(window_length=3, n_std=0.1)

    assert "SL" in cs.labels


# ---------------------------------------------------------------------
# replace_from_timeseries
# ---------------------------------------------------------------------

class DummyTS:
    def __init__(self, times, values):
        self.times = times
        self.values = values


def test_replace_from_timeseries_basic():
    base = CardioSeries(np.array([0.0, 1.0, 2.0, 3.0]))

    ts = DummyTS(
        times=np.linspace(1.0, 2.0, 100),
        values=np.sin(np.linspace(0, 10, 100))
    )

    base.replace_from_timeseries(ts, start=1.0, end=2.0)

    assert np.all(base.times >= 0)
    assert np.all(np.diff(base.times) >= 0)


def test_replace_invalid_window_raises():
    cs = CardioSeries(np.array([0.0, 1.0]))
    with pytest.raises(ValueError):
        cs.replace_from_timeseries(None, start=2.0, end=1.0)


# ---------------------------------------------------------------------
# Views & slicing
# ---------------------------------------------------------------------

def test_view_is_zero_copy(cardio):
    view = cardio.view(1.0, 3.0)
    assert isinstance(view, CardioSeriesView)

    cardio.times[1] = 10.0
    assert view.times[0] == 10.0


def test_view_ibi_alignment():
    cs = CardioSeries(np.array([0.0, 1.0, 3.5]))
    view = cs.view(0.0, 3.5)

    ibi = view.ibi
    assert len(ibi) == len(view.times)
    assert np.isnan(ibi[-1])


def test_nested_view():
    cs = CardioSeries(np.array([0.0, 1.0, 2.0, 3.0]))
    v1 = cs.view(1.0, 3.0)
    v2 = v1.view(2.0, 3.0)

    assert np.all(v2.times == np.array([2.0, 3.0]))


# ---------------------------------------------------------------------
# Welch PSD
# ---------------------------------------------------------------------

def test_welch_psd_empty():
    cs = CardioSeries(np.array([]))
    freqs, power = cs.welch_psd()
    assert freqs.size == 0
    assert power.size == 0


def test_welch_psd_runs(cardio):
    freqs, power = cardio.welch_psd(interpolate=False)
    assert freqs.ndim == 1
    assert power.ndim == 1


def test_welch_psd_with_ci_shapes(cardio):
    freqs, psd, lo, hi = cardio.welch_psd_with_ci()
    assert freqs.shape == psd.shape == lo.shape == hi.shape


# ---------------------------------------------------------------------
# HRV metrics
# ---------------------------------------------------------------------

def test_basic_hrv_metrics(cardio):
    assert cardio.count() == 4
    assert cardio.mean() > 0
    assert cardio.std() >= 0
    assert cardio.rmssd() >= 0


def test_metrics_nan_on_insufficient_data():
    cs = CardioSeries(np.array([0.0]))
    assert np.isnan(cs.rmssd())
    assert np.isnan(cs.sd1())
    assert np.isnan(cs.sd2())


# ---------------------------------------------------------------------
# Band power utility
# ---------------------------------------------------------------------

def test_band_power_returns_nan_on_empty():
    cs = CardioSeries(np.array([]))
    val = cs._band_power_exact(np.array([]), np.array([]), 0.04, 0.15)
    assert np.isnan(val)
