# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/DataSet/Series/RespirationSeriesView.py
"""
Zero-copy view into a RespirationSeries.

Design
------
RespirationSeriesView is a pure data accessor. It holds a reference to a
parent RespirationSeries and an index array, and exposes the subset of
starts, ends, and labels that fall within that slice.

Respiration analysis functions (e.g. mean_breath_frequency_hz) are
standalone functions in spectHR.Tools.RespirationSegmentation that accept
a view as their argument.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional
import numpy as np

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData
    from spectHR.DataSet.Series.RespirationSeries import RespirationSeries


class RespirationSeriesView:
    """
    Zero-copy view into a parent RespirationSeries.

    Uses composition: holds a reference to the parent and an index array.
    Does NOT inherit from RespirationSeries and cannot own data or call
    from_timeseries. View methods never modify the parent.

    Identity metadata
    -----------------
    _pd     : PhysioData linkage (propagated from parent)
    _stream : band / stream identifier
    _epoch  : epoch label (set when produced by epoch slicing)
    """

    def __init__(self, parent: "RespirationSeries", indices: np.ndarray) -> None:
        self._parent = parent
        self._idx = np.asarray(indices, dtype=int)
        self._pd: Optional["PhysioData"] = getattr(parent, "_pd", None)
        self._stream: Optional[str] = getattr(parent, "_stream", None)
        self._epoch: Optional[str] = None

    # ------------------------------------------------------------------
    # Data interface - composition, not ownership
    # ------------------------------------------------------------------

    @property
    def starts(self) -> np.ndarray:
        """View of parent phase start times (seconds)."""
        return self._parent.starts[self._idx]

    @property
    def ends(self) -> np.ndarray:
        """View of parent phase end times (seconds)."""
        return self._parent.ends[self._idx]

    @property
    def labels(self) -> np.ndarray:
        """View of parent phase labels."""
        return self._parent.labels[self._idx]

    # ------------------------------------------------------------------
    # Slicing
    # ------------------------------------------------------------------

    def view(self, starttime: float, endtime: float) -> "RespirationSeriesView":
        """Create a sub-view restricted to phases within [starttime, endtime]."""
        mask = (self.starts >= starttime) & (self.ends <= endtime)
        sub = RespirationSeriesView(self._parent, self._idx[mask])
        sub._pd = self._pd
        sub._stream = self._stream
        sub._epoch = None
        return sub

    def __getitem__(self, epoch_label: str) -> "RespirationSeriesView":
        """
        Return an epoch-restricted view using PhysioData.epochs.

        Raises
        ------
        RuntimeError
            If not linked to a PhysioData instance.
        KeyError
            If the requested epoch does not exist.
        """
        if self._pd is None:
            raise RuntimeError("RespirationSeriesView is not connected to PhysioData.")
        if epoch_label not in self._pd.epochs:
            raise KeyError(f"No epoch '{epoch_label}' in PhysioData.")
        ep = self._pd.epochs[epoch_label]
        mask = (self.starts >= ep.start) & (self.ends <= ep.end)
        v = RespirationSeriesView(self._parent, self._idx[mask])
        v._pd = self._pd
        v._stream = self._stream
        v._epoch = epoch_label
        return v

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return int(self._idx.size)

    def __repr__(self) -> str:
        return (
            f"RespirationSeriesView("
            f"n={len(self)}, "
            f"stream={self._stream!r}, "
            f"epoch={self._epoch!r})"
        )
