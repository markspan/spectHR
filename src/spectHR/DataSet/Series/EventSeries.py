# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass
class EventSeries:
    """
    Represents a marker / event stream.

    Attributes
    ----------
    times : np.ndarray
        1-D array of event times.
    labels : list[str]
        List of event labels (same length as times).
    """

    times: np.ndarray
    labels: list[str]

    def __post_init__(self) -> None:
        self.times = np.asarray(self.times, dtype=float)
        if self.times.ndim != 1:
            raise ValueError("EventSeries.times must be 1-D.")
        if len(self.times) != len(self.labels):
            raise ValueError("times and labels must have same length.")

