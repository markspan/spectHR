import numpy as np
import pytest

import spectHR.DataSet.loaders.xdf_loader as xdfmod
from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def make_stream(name, stype, times, data, srate):
    return {
        "info": {
            "name": [name],
            "type": [stype],
            "nominal_srate": [srate],
        },
        "time_stamps": times,
        "time_series": data,
    }


# ---------------------------------------------------------
# Fixture: mock pyxdf.load_xdf
# ---------------------------------------------------------

@pytest.fixture
def mock_pyxdf(monkeypatch):
    def fake_load_xdf(filename):
        # -------------------------
        # Marker stream
        # -------------------------
        markers = make_stream(
            name="Markers",
            stype="Markers",
            times=[0.5, 1.5],
            data=[["start rest"], ["end rest"]],
            srate=0,
        )

        # -------------------------
        # ECG stream
        # -------------------------
        ecg = make_stream(
            name="Polar_ECG",
            stype="ECG",
            times=[0.00, 0.01, 0.02, 0.03, 0.04],
            data=[[1.0], [2.0], [3.0], [4.0], [5.0]],
            srate=100,
        )

        # -------------------------
        # ACC stream (>= 10 samples → filtfilt safe)
        # -------------------------
        times = np.arange(0.0, 0.2, 0.02)  # 10 samples
        acc_data = np.column_stack([
            np.linspace(0.1, 0.3, 10),
            np.linspace(0.0, 0.2, 10),
            np.linspace(1.0, 0.8, 10),
        ])

        acc = make_stream(
            name="Polar_ACC",
            stype="ACC",
            times=times.tolist(),
            data=acc_data.tolist(),
            srate=50,
        )

        return [markers, ecg, acc], {}

    monkeypatch.setattr(xdfmod.pyxdf, "load_xdf", fake_load_xdf)


# ---------------------------------------------------------
# Tests
# ---------------------------------------------------------

def test_xdf_loader_populates_physiodata(mock_pyxdf, tmp_path):
    fname = tmp_path / "test.xdf"
    fname.write_text("dummy")

    pd = PhysioData(str(fname))

    # -------------------------
    # Events
    # -------------------------
    assert "Markers" in pd.events
    ev = pd.events["Markers"]

    assert isinstance(ev, EventSeries)
    assert ev.labels == ["start rest", "stop rest"]
    np.testing.assert_allclose(ev.times, [0.5, 1.5])

    # -------------------------
    # TimeSeries
    # -------------------------
    ecg_keys = [k for k in pd.timeseries if k.startswith("ecg")]
    rsp_keys = [k for k in pd.timeseries if k.startswith("RSP")]

    assert len(ecg_keys) == 1
    assert len(rsp_keys) == 1

    ecg = pd.timeseries[ecg_keys[0]]
    rsp = pd.timeseries[rsp_keys[0]]

    assert isinstance(ecg, TimeSeries)
    assert isinstance(rsp, TimeSeries)

    np.testing.assert_allclose(ecg.values, [1, 2, 3, 4, 5])
    assert rsp.values.size == 10

    # -------------------------
    # Band mapping
    # -------------------------
    assert pd.band_map
    band = next(iter(pd.band_map))

    mapping = pd.band_map[band]
    assert mapping["ecg"] == ecg_keys[0]
    assert mapping["rsp"] == rsp_keys[0]

    assert pd.active_band == band


def test_non_polar_streams_are_ignored(monkeypatch, tmp_path):
    def fake_load_xdf(filename):
        junk = make_stream(
            name="Camera_Stream",
            stype="video",
            times=[0.0, 1.0],
            data=[[0], [1]],
            srate=30,
        )
        return [junk], {}

    monkeypatch.setattr(xdfmod.pyxdf, "load_xdf", fake_load_xdf)

    fname = tmp_path / "test.xdf"
    fname.write_text("dummy")

    pd = PhysioData(str(fname))

    assert pd.timeseries == {}
    assert pd.events == {}
    assert pd.band_map == {}
    assert pd.active_band is None
