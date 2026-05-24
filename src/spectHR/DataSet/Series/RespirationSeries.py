# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/DataSet/Series/RespirationSeries.py
from __future__ import annotations

from typing import Dict, Optional
import numpy as np

from spectHR.Tools.Logger import logger


class RespirationSeries:
    """
    Container for respiration phase intervals derived from a respiration signal.

    Conceptual model
    ----------------
    A RespirationSeries owns phase-based structure extracted from a continuous
    respiration (RSP) TimeSeries.  Each entry corresponds to a contiguous
    breathing phase:
    - inhalation ("INH")
    - exhalation ("EXH")

    Phases are represented as aligned arrays:
    - starts : phase start times (seconds)
    - ends   : phase end times (seconds)
    - labels : phase labels ("INH", "EXH")

    Times are in dataset time base (seconds), consistent with TimeSeries and
    CardioSeries.

    Relationship to views
    ---------------------
    RespirationSeries.view() returns a RespirationSeriesView (defined in
    RespirationSeriesView.py).  Views do NOT inherit from RespirationSeries -
    they use composition.
    """

    def __init__(
        self,
        starts: np.ndarray,
        ends: np.ndarray,
        labels: np.ndarray,
    ) -> None:
        self.starts = np.asarray(starts, dtype=float)
        self.ends   = np.asarray(ends,   dtype=float)
        self.labels = np.asarray(labels, dtype=object)
        self._pd     = None
        self._stream = None

        if not (self.starts.size == self.ends.size == self.labels.size):
            raise ValueError("starts, ends, and labels must have equal length")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_timeseries(
        cls,
        rsp,
        *,
        prefilter_cutoff_hz: float = 2,
        prefilter_order: int | None = None,
        min_phase_duration: float = 2,
        smooth: bool = True,
        smoothing_window: int = 31,
        polyorder: int = 3,
        prominence: float | None = None,
        prominence_rel: float = 0.55,
        min_amplitude: float | None = None,
    ) -> "RespirationSeries":
        """Segment a respiration signal into INH/EXH phases.

        Delegates to
        :func:`spectHR.Tools.RespirationSegmentation.segment_respiration`.
        See that function for full parameter and algorithm documentation.
        """
        from spectHR.Tools.RespirationSegmentation import segment_respiration
        starts, ends, labels = segment_respiration(
            rsp,
            prefilter_cutoff_hz=prefilter_cutoff_hz,
            prefilter_order=prefilter_order,
            min_phase_duration=min_phase_duration,
            smooth=smooth,
            smoothing_window=smoothing_window,
            polyorder=polyorder,
            prominence=prominence,
            prominence_rel=prominence_rel,
            min_amplitude=min_amplitude,
        )
        return cls(starts, ends, labels)

    # ------------------------------------------------------------------
    # Convenience / inspection
    # ------------------------------------------------------------------

    def as_dict(self) -> Dict[str, np.ndarray]:
        """Return phases grouped by label.

        Returns
        -------
        dict  with keys ``"INH"`` and ``"EXH"``, values Nx2 (start, end) arrays.
        """
        grouped: Dict[str, list] = {"INH": [], "EXH": []}
        for s, e, lab in zip(self.starts, self.ends, self.labels):
            grouped[lab].append((s, e))
        return {k: np.asarray(v, dtype=float) for k, v in grouped.items()}

    def __len__(self) -> int:
        return int(self.starts.size)

    def __repr__(self) -> str:
        return f"RespirationSeries(n={len(self)})"

    def view(self, starttime: float, endtime: float) -> "RespirationSeriesView":
        """Return a zero-copy view restricted to phases within [starttime, endtime]."""
        from spectHR.DataSet.Series.RespirationSeriesView import RespirationSeriesView

        idx = np.where((self.starts >= starttime) & (self.ends <= endtime))[0]
        v = RespirationSeriesView(self, idx)
        v._pd     = self._pd
        v._stream = self._stream
        v._epoch  = None
        return v
