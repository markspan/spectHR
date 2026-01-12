from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from spectHR.DataSet.Series.TimeSeries import TimeSeries, TimeSeriesView

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData


@dataclass
class StreamAccessor:
    """
    Design role
    -----------
    - Provides dataset-aware access to a specific TimeSeries.
    - ONLY place that stamps view identity: (_pd, _stream, _epoch)

    Examples
    --------
    data["ecg"]           -> StreamAccessor
    data["ecg"]["rest"]   -> TimeSeriesView for epoch "rest"
    """

    _ts: TimeSeries
    _pd: "PhysioData"
    _stream: str  # logical/physical stream name in physiodata.timeseries

    def __getitem__(self, key) -> TimeSeriesView:
        # ------------------------------------------------------------
        # Epoch slicing (dataset-aware)
        # ------------------------------------------------------------
        if isinstance(key, str) and key in self._pd.epochs:
            ep = self._pd.epochs[key]

            view = self._ts.view(starttime=ep.start, endtime=ep.end)

            # Stamp identity (single mutation interface / provenance)
            view._pd = self._pd
            view._stream = self._stream
            view._epoch = key

            return view

        # ------------------------------------------------------------
        # Non-epoch slicing: delegate to raw TimeSeries slicing
        # (returns raw values, not a view)
        # ------------------------------------------------------------
        return self._ts[key]

    @property
    def times(self):
        return self._ts.times

    @property
    def values(self):
        return self._ts.values

    @property
    def timeseries(self) -> TimeSeries:
        return self._ts
