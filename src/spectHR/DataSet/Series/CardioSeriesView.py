# spectHR/DataSet/Series/CardioSeriesView.py
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

from spectHR.DataSet.Series.CardioMetricsMixin import CardioMetricsMixin
from spectHR.DataSet.Series.CardioFrequencyMetricsMixin import (
    CardioFrequencyMetricsMixin,
)

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData
    from spectHR.DataSet.Series.CardioSeries import CardioSeries


class CardioSeriesView(CardioMetricsMixin, CardioFrequencyMetricsMixin):
    """
    Zero-copy view into a parent CardioSeries.

    Uses composition: holds a reference to the parent and an index array.
    Does NOT inherit from CardioSeries — it cannot own data, classify IBIs,
    or replace peaks.  Methods that only make sense on the full series
    (classify_ibi, replace_from_timeseries, from_timeseries, hrv_epoch_table)
    are deliberately absent.

    All HRV metric methods are inherited from CardioMetricsMixin and operate
    correctly on the view's times and labels.

    Use CardioSeriesLike (CardioSeriesProtocol.py) for type annotations where
    either a CardioSeries or a CardioSeriesView may be passed.

    Identity metadata
    -----------------
    _pd     : PhysioData linkage (propagated from parent)
    _stream : band / stream identifier
    _epoch  : epoch label (set when produced by CardioSeries.__getitem__)
    """

    def __init__(self, parent: "CardioSeries", indices: np.ndarray) -> None:
        self._parent = parent
        self._idx = np.asarray(indices, dtype=int)
        self._pd: Optional["PhysioData"] = parent._pd
        self._stream: Optional[str] = parent._stream
        self._epoch: Optional[str] = None

    # ------------------------------------------------------------------
    # Data interface — composition, not ownership
    # ------------------------------------------------------------------

    @property
    def times(self) -> np.ndarray:
        """View of parent R-peak times (seconds)."""
        return self._parent.times[self._idx]

    @property
    def labels(self) -> np.ndarray:
        """View of parent labels aligned to this view's IBI indexing."""
        return self._parent.labels[self._idx]

    @property
    def ibi(self) -> np.ndarray:
        """
        IBIs in seconds derived from this view's times, with a trailing NaN.

        Pure computation — never mutates parent labels.
        """
        t = self.times
        if t.size < 2:
            return np.asarray([np.nan], dtype=float)
        return np.concatenate([np.diff(t), np.array([np.nan], dtype=float)])

    # ------------------------------------------------------------------
    # PSD configuration — delegate to parent so the master CardioSeries
    # is the single source of truth. Per-epoch views (created on demand
    # via ``CardioSeries[label]``) are short-lived, so setting
    # psd_method on each one is fragile; setting it on the parent and
    # reading it through this property keeps every view in lock-step
    # with whatever the UI most recently pushed.
    # ------------------------------------------------------------------

    @property
    def psd_method(self):  # type: ignore[override]
        return getattr(self._parent, "psd_method", None)

    @psd_method.setter
    def psd_method(self, value) -> None:
        self._parent.psd_method = value

    # ------------------------------------------------------------------
    # Slicing
    # ------------------------------------------------------------------

    def view(self, starttime: float, endtime: float) -> "CardioSeriesView":
        """Create a sub-view restricted to [starttime, endtime]."""
        mask = (self.times >= starttime) & (self.times <= endtime)
        sub = CardioSeriesView(self._parent, self._idx[mask])
        sub._pd = self._pd
        sub._stream = self._stream
        sub._epoch = None
        return sub

    def __repr__(self) -> str:
        return (
            f"CardioSeriesView(n={self.times.size}, "
            f"stream={self._stream!r}, epoch={self._epoch!r})"
        )
