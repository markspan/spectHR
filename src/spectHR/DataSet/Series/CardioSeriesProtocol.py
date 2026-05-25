# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/DataSet/Series/CardioSeriesProtocol.py
"""
Structural protocol shared by CardioSeries and CardioSeriesView.

CardioSeriesLike lets functions (PSDEngine, profile, analysis metrics)
accept either a full CardioSeries or an epoch / time-range view of one,
with isinstance() support thanks to @runtime_checkable.

What belongs here
-----------------
Only members actually called by algorithm code belong in this protocol.
That is the three data arrays (times, labels, ibi) and the view()
constructor. PSD helper functions live in spectHR.analysis.ibi_helpers
and take a CardioSeriesLike as their first argument; they are not methods
on the series and so do not appear here.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class CardioSeriesLike(Protocol):
    """Structural protocol satisfied by both CardioSeries and CardioSeriesView.

    Use this as a type annotation wherever a function accepts either.

    Example
    -------
    >>> def compute_metrics(series: CardioSeriesLike) -> dict: ...
    """

    @property
    def times(self) -> np.ndarray:
        """R-peak timestamps in seconds."""
        ...

    @property
    def labels(self) -> np.ndarray:
        """Per-beat label array ("N", "TL", "S", ...)."""
        ...

    @property
    def ibi(self) -> np.ndarray:
        """Inter-beat intervals in seconds, trailing NaN for alignment."""
        ...

    def view(self, starttime: float, endtime: float) -> "CardioSeriesLike":
        """Return a zero-copy view restricted to [starttime, endtime]."""
        ...
