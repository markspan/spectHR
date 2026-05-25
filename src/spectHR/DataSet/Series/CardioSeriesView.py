# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/DataSet/Series/CardioSeriesView.py
"""
Zero-copy view into a CardioSeries.

Design
------
CardioSeriesView is a pure data accessor. It holds a reference to a parent
CardioSeries and an index array, and exposes the subset of times, labels, and
derived IBIs that fall within that slice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData
    from spectHR.DataSet.Series.CardioSeries import CardioSeries


__all__ = ["CardioSeriesView"]


class CardioSeriesView:
    """
    Zero-copy view into a parent CardioSeries.

    Uses composition: holds a reference to the parent and an index array.
    Does NOT inherit from CardioSeries and cannot own data, classify IBIs,
    or replace peaks.

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
    # Data interface - composition, not ownership
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
        """IBIs in seconds derived from this view's times, with a trailing NaN."""
        t = self.times
        if t.size < 2:
            return np.asarray([np.nan], dtype=float)
        return np.concatenate([np.diff(t), np.array([np.nan], dtype=float)])

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
