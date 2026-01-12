import numpy as np
import pytest

from spectHR.DataSet.Series.TimeSeries import TimeSeries, TimeSeriesView
from spectHR.DataSet.Epoch import Epoch
from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.StreamAccessor import StreamAccessor


@pytest.fixture
def physiodata():
    # Construct PhysioData without invoking loaders
    pd = PhysioData.__new__(PhysioData)

    pd.filename = "dummy"
    pd.basename = "dummy"

    pd.timeseries = {}
    pd.events = {}
    pd.epochs = {}
    pd.band_map = {}
    pd.active_band = None
    pd.hrv_map = {}

    # Epoch: 1s–3s
    pd.epochs["rest"] = Epoch(active=True, start=1.0, end=3.0)

    # TimeSeries: 0–4s
    ts = TimeSeries(
        times=np.array([0, 1, 2, 3, 4], dtype=float),
        values=np.array([10, 20, 30, 40, 50], dtype=float),
    )

    pd.timeseries["ecg"] = ts

    return pd


# ---------------------------------------------------------------------
# StreamAccessor tests (new contract)
# ---------------------------------------------------------------------

def test_stream_accessor_non_epoch_key_falls_through(physiodata):
    ts = physiodata.timeseries["ecg"]
    acc = StreamAccessor(ts, physiodata, "ecg")

    # Non-epoch key → delegate to TimeSeries
    assert acc.times[2] == 2.0
    assert acc.values[2] == 30.0


def test_stream_accessor_epoch_slice(physiodata):
    ts = physiodata.timeseries["ecg"]
    acc = StreamAccessor(ts, physiodata, "ecg")

    view = acc["rest"]

    assert isinstance(view, TimeSeriesView)

    # Correct slice
    assert np.all(view.times == np.array([1.0, 2.0, 3.0]))
    assert np.all(view.values == np.array([20.0, 30.0, 40.0]))

    # Identity is formalized on the view
    assert view._pd is physiodata
    assert view._stream == "ecg"
    assert view._epoch == "rest"


def test_stream_accessor_invalid_epoch_key_falls_through(physiodata):
    ts = physiodata.timeseries["ecg"]
    acc = StreamAccessor(ts, physiodata, "ecg")

    # Unknown key → treated as non-epoch → delegated
    with pytest.raises(Exception):
        _ = acc["does_not_exist"]
