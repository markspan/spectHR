# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""R-top (R-peak) editing controller.

A thin, headless data-mutation API over a :class:`CardioSeries`: move,
add, delete and query R-peaks. Pure numpy — no plotting, no Qt — so the
same editing operations are usable from scripts and tests, not only the
interactive Preprocessing widget that drives it.
"""
from __future__ import annotations

import numpy as np

from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.DataSet.Series.CardioSeriesView import CardioSeriesView


class RTopController:
    """
    Encapsulates all mutations & queries on a CardioSeries (R-top data).

    This class is purely about *data*: no plotting, no Qt.

    After any mutation to R-peak times, `classify_ibi()` is called
    automatically so that labels always reflect the current IBI values.
    The ``*_no_classify`` variants skip that step for callers that batch
    several edits and reclassify once at the end (e.g. on a worker thread).
    """

    def __init__(self, rtops: CardioSeries) -> None:
        """
        Parameters
        ----------
        rtops:
            The CardioSeries instance to control (mutated in place).
        """
        self.rtops = rtops

    @property
    def times(self) -> np.ndarray:
        """R-top times in seconds."""
        return self.rtops.times

    @property
    def labels(self) -> np.ndarray:
        """Labels aligned to R-top indexing."""
        return self.rtops.labels

    @property
    def ibi(self) -> np.ndarray:
        """Inter-beat intervals in seconds."""
        return self.rtops.ibi

    def _sort_by_time(self) -> None:
        """Keep times & labels sorted ascending by time."""
        order = np.argsort(self.rtops.times)
        self.rtops.times = self.rtops.times[order]
        self.rtops.labels = self.rtops.labels[order]

    def _closest_idx(self, t: float) -> int:
        """Return index of R-top closest in time to t."""
        return int(np.argmin(np.abs(self.rtops.times - t)))

    def move(self, old_t: float, new_t: float) -> None:
        """Move R-top and immediately reclassify (for callers that need labels in one step)."""
        self.move_no_classify(old_t, new_t)
        self.rtops.classify_ibi()

    def move_no_classify(self, old_t: float, new_t: float) -> None:
        """Move the closest R-top to new_t without reclassifying IBIs."""
        idx = self._closest_idx(old_t)
        self.rtops.times[idx] = float(new_t)
        self._sort_by_time()

    def add(self, t: float, label: str = "N") -> None:
        """Insert a new R-top and immediately reclassify (for callers that need labels in one step)."""
        self.add_no_classify(t, label)
        self.rtops.classify_ibi()

    def add_no_classify(self, t: float, label: str = "N") -> None:
        """Insert a new R-top at time t without reclassifying IBIs."""
        self.rtops.times = np.concatenate(
            [self.rtops.times, np.array([t], dtype=float)]
        )
        self.rtops.labels = np.concatenate(
            [self.rtops.labels, np.array([label], dtype=object)]
        )
        self._sort_by_time()

    def delete(self, t: float) -> None:
        """Delete the closest R-top and immediately reclassify (for callers that need labels in one step)."""
        self.delete_no_classify(t)
        self.rtops.classify_ibi()

    def delete_no_classify(self, t: float) -> None:
        """Delete the R-top closest to t without reclassifying IBIs."""
        idx = self._closest_idx(t)
        mask = np.ones(self.rtops.times.shape[0], dtype=bool)
        mask[idx] = False
        self.rtops.times = self.rtops.times[mask]
        self.rtops.labels = self.rtops.labels[mask]

    def next_non_normal(self, after_time: float) -> float | None:
        """
        First non-'N' R-top strictly after `after_time`.
        """
        mask = (self.rtops.labels != "N") & (self.rtops.times > after_time)
        if not np.any(mask):
            return None
        return float(self.rtops.times[mask][0])

    def prev_non_normal(self, before_time: float) -> float | None:
        """
        Last non-'N' R-top strictly before `before_time`.
        """
        mask = (self.rtops.labels != "N") & (self.rtops.times < before_time)
        if not np.any(mask):
            return None
        return float(self.rtops.times[mask][-1])

    def window_view(self, x_min: float, x_max: float) -> CardioSeriesView:
        """
        Return a CardioSeriesView restricted to [x_min, x_max].
        """
        return self.rtops.view(x_min, x_max)
