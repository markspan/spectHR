from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
import numpy as np

from spectHR.Tools.Logger import logger

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData


@dataclass
class TimeSeries:
    """
    Simple 1-D time series.

    Design role
    -----------
    - Owns raw arrays: times, values
    - Does NOT know about PhysioData, epochs, or stream names
    - Provides identity-neutral views via .view()
    """

    times: np.ndarray
    values: np.ndarray

    def __post_init__(self) -> None:
        self.times = np.asarray(self.times, dtype=float)
        self.values = np.asarray(self.values, dtype=float)

        if self.times.ndim != 1 or self.values.ndim != 1:
            raise ValueError("TimeSeries.times and TimeSeries.values must be 1-D arrays.")
        if self.times.shape[0] != self.values.shape[0]:
            raise ValueError("TimeSeries times and values must have same length.")

    def flip(self) -> None:
        """Invert the signal values in place."""
        logger.info("Flipping TimeSeries values.")
        self.values = -self.values

    def __getitem__(self, idx):
        """
        Non-epoch slicing. Returns raw value(s) only.

        Important:
        - We intentionally DO NOT return a TimeSeriesView here, because that would
          enable mutation without identity assignment (pd/stream/epoch).
        """
        return self.values[idx]

    @property
    def srate(self) -> Optional[float]:
        """Approximate sampling rate (Hz), or None if cannot be inferred."""
        if self.times.size < 2:
            return None
        diffs = np.diff(self.times)
        diffs = diffs[diffs > 0]
        if diffs.size == 0:
            return None
        return float(1.0 / np.mean(diffs))

    def view(self, starttime: float | None = None, endtime: float | None = None) -> "TimeSeriesView":
        """
        Return an identity-neutral, zero-copy view on a time interval.

        Identity (pd/stream/epoch) is assigned by StreamAccessor, not here.
        """
        if self.times.size == 0:
            return TimeSeriesView(self, np.empty(0, dtype=int))

        if starttime is None:
            starttime = float(self.times[0])
        if endtime is None:
            endtime = float(self.times[-1])

        mask = (self.times >= starttime) & (self.times <= endtime)
        idx = np.nonzero(mask)[0]
        return TimeSeriesView(self, idx)


class TimeSeriesView:
    """
    Zero-copy dynamic view on a TimeSeries.

    Design role
    -----------
    - Structural slice only; shares storage with the parent series
    - May carry identity metadata (_pd, _stream, _epoch), which is assigned
      by access layers (e.g., StreamAccessor)
    """

    def __init__(self, parent: TimeSeries, indices: np.ndarray) -> None:
        self._parent = parent
        self._indices = np.asarray(indices, dtype=int)

        # Identity metadata (assigned externally by StreamAccessor)
        self._pd: PhysioData | None = None
        self._stream: str | None = None
        self._epoch: str | None = None

    @property
    def physiodata(self) -> "PhysioData | None":
        return self._pd

    @property
    def times(self) -> np.ndarray:
        return self._parent.times[self._indices]

    @property
    def values(self) -> np.ndarray:
        return self._parent.values[self._indices]

    def __getitem__(self, idx: int) -> float:
        parent_idx = int(self._indices[idx])
        return float(self._parent.values[parent_idx])

    def __setitem__(self, idx: int, value: float) -> None:
        """
        Mutate the parent series via the view.

        This is intentionally allowed. Identity metadata enables downstream
        operations (e.g., merging edits back into dataset logic).
        """
        parent_idx = int(self._indices[idx])
        self._parent.values[parent_idx] = float(value)

    def __len__(self) -> int:
        return int(self._indices.size)

    def __repr__(self) -> str:
        return f"TimeSeriesView(n={len(self)}, stream={self._stream!r}, epoch={self._epoch!r})"
