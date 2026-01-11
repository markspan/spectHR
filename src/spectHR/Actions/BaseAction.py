from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple, Any

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.PhysioData import PhysioData

class BaseAction(ABC):
    """
    Base class for actions operating on PhysioData, streams, and views.

    Key feature
    -----------
    Provides a unified way to resolve a "target" into a TimeSeries
    (and optionally its owning PhysioData).
    """

    @classmethod
    def resolve_timeseries(cls, target: Any) -> Tuple[TimeSeries, PhysioData | None]:
        """
        Resolve a target object into (TimeSeries, PhysioData | None).

        Supported targets
        -----------------
        - PhysioData       → first timeseries in its dict (no epoch)
        - StreamAccessor   → its underlying TimeSeries and PhysioData
        - TimeSeries       → itself, no PhysioData
        - TimeSeriesView   → its parent TimeSeries, no PhysioData
        """
        from spectHR.DataSet.Series.TimeSeries import TimeSeries, TimeSeriesView  # local imports to avoid cycles
        from spectHR.DataSet.PhysioData import PhysioData, StreamAccessor

        if isinstance(target, PhysioData):
            if not target.timeseries:
                raise ValueError("PhysioData has no timeseries to operate on.")
            ts = next(iter(target.timeseries.values()))
            return ts, target

        if isinstance(target, StreamAccessor):
            return target.timeseries, target._pd

        if isinstance(target, TimeSeries):
            return target, target.physiodata

        if isinstance(target, TimeSeriesView):
            return target, target.physiodata

        raise TypeError(f"Unsupported target type for action: {type(target)}")

    @classmethod
    @abstractmethod
    def apply(cls, target: Any, **kwargs: Any) -> Any:
        """Perform the action on the given target."""
        raise NotImplementedError
