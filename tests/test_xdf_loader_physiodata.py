import numpy as np
import pytest

from spectHR.DataSet.loaders.xdf_loader import load_xdf, _compute_RSP_signal
from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries


# ---------------------------------------------------------------------
# Minimal PhysioData stub
# ---------------------------------------------------------------------

class DummyPhysioData:
    def __init__(self):
        self.timeseries = {}
        self.events = {}
        self.has_ecg = False
        self.band_map = {}
        self.active_band = None


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

@pytest.fixture
def physiodata():
    return DummyPhysioData()


@pytest.fixture
def fake_ecg_stream():
    return {
        "info": {
            "name": ["PolarH10_ecg"],
            "type": ["ECG"],
            "nominal_srate": ["130"],
        },
        "time_stamps": np.linspace(0, 10, 1300),
        "time_series": np.random.randn(1300, 1),
    }


@pytest.fixture
def fake_acc_stream():
    return {
        "info": {
            "name": ["PolarH10_acc"],
            "type": ["ACC"],
            "nominal_srate": ["50"],
        },
        "time_stamps": np.linspace(0, 10, 500),
        "time_series": np.random.randn(500, 3),
    }


@pytest.fixture
def fake_marker_stream():
    return {
        "info": {
            "name": ["TaskMarkers"],
            "type": ["Markers"],
            "nominal_srate": ["0"],
        },
        "time_stamps": np.array([1.0, 2.0, 3.0]),
        "time_series": [
            ["start trial"],
            ["end trial"],
            ["foo"],
        ],
    }


# ---------------------------------------------------------------------
# pyxdf mocking
# ---------------------------------------------------------------------

@pytest.fixture
def mock_pyxdf(monkeypatch, fake_ecg_stream, fake_acc_stream, fake_marker_stream):
    def fake_load_xdf(filename):
        return [fake_ecg_stream, fake_acc_stream, fake_marker_stream], None

    monkeypatch.setattr("pyxdf.load_xdf", fake_load_xdf)


# ---------------------------------------------------------------------
# _compute_RSP_signal
# ---------------------------------------------------------------------

def test_compute_rsp_signal_shape():
    acc = np.random.randn(1000, 3)
    rsp = _compute_RSP_signal(acc, fs=50.0)

    assert rsp.shape == (1000,)
    assert np.isfinite(rsp).all()


def test_compute_rsp_signal_constant_input():
    acc = np.zeros((500, 3))
    rsp = _compute_RSP_signal(acc, fs=50.0)

    # Should remain near zero
    assert np.allclose(rsp, 0.0, atol=1e-6)


# ---------------------------------------------------------------------
# Loader: happy path
# ---------------------------------------------------------------------

def test_load_xdf_populates_timeseries_and_events(
    physiodata, mock_pyxdf
):
    load_xdf(physiodata, "dummy.xdf")

    # ECG loaded
    ecg_keys = [k for k in physiodata.timeseries if k.startswith("ecg")]
    assert len(ecg_keys) == 1
    assert isinstance(physiodata.timeseries[ecg_keys[0]], TimeSeries)

    # Respiration loaded
    rsp_keys = [k for k in physiodata.timeseries if k.startswith("RSP")]
    assert len(rsp_keys) == 1
    assert isinstance(physiodata.timeseries[rsp_keys[0]], TimeSeries)

    # Markers loaded
    assert "TaskMarkers" in physiodata.events
    assert isinstance(physiodata.events["TaskMarkers"], EventSeries)

    # ECG flag
    assert physiodata.has_ecg is True


def test_marker_label_normalization(physiodata, mock_pyxdf):
    load_xdf(physiodata, "dummy.xdf")

    ev = physiodata.events["TaskMarkers"]
    labels = list(ev.labels)

    assert labels[1].startswith("stop ")
    assert labels[1] == "stop trial"


# ---------------------------------------------------------------------
# Loader: band indexing
# ---------------------------------------------------------------------

def test_band_map_created(physiodata, mock_pyxdf):
    load_xdf(physiodata, "dummy.xdf")

    assert physiodata.band_map
    assert physiodata.active_band is not None

    band = physiodata.active_band
    mapping = physiodata.band_map[band]

    assert "ecg" in mapping
    assert "rsp" in mapping


# ---------------------------------------------------------------------
# Loader: robustness / edge cases
# ---------------------------------------------------------------------

def test_non_polar_streams_ignored(monkeypatch, physiodata):
    def fake_load_xdf(filename):
        return [{
            "info": {
                "name": ["RandomStream"],
                "type": ["EEG"],
                "nominal_srate": ["250"],
            },
            "time_stamps": np.linspace(0, 1, 250),
            "time_series": np.random.randn(250, 8),
        }], None

    monkeypatch.setattr("pyxdf.load_xdf", fake_load_xdf)

    load_xdf(physiodata, "dummy.xdf")
    assert physiodata.timeseries == {}
    assert physiodata.events == {}


def test_acc_wrong_channel_count_skipped(monkeypatch, physiodata):
    def fake_load_xdf(filename):
        return [{
            "info": {
                "name": ["Polar_acc"],
                "type": ["ACC"],
                "nominal_srate": ["50"],
            },
            "time_stamps": np.linspace(0, 10, 100),
            "time_series": np.random.randn(100, 2),  # WRONG
        }], None

    monkeypatch.setattr("pyxdf.load_xdf", fake_load_xdf)

    load_xdf(physiodata, "dummy.xdf")
    assert physiodata.timeseries == {}


def test_invalid_acc_timestamps_skipped(monkeypatch, physiodata):
    def fake_load_xdf(filename):
        return [{
            "info": {
                "name": ["Polar_acc"],
                "type": ["ACC"],
                "nominal_srate": ["50"],
            },
            "time_stamps": np.ones(100),  # no positive diffs
            "time_series": np.random.randn(100, 3),
        }], None

    monkeypatch.setattr("pyxdf.load_xdf", fake_load_xdf)

    load_xdf(physiodata, "dummy.xdf")
    assert physiodata.timeseries == {}
