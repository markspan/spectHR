# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/DataSet/Series/CardioSeries.py
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

from spectHR.DataSet.Series.IBIClassificationParams import DEFAULT_IBI_PARAMS

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData
    from spectHR.DataSet.Series.CardioSeriesView import CardioSeriesView


class CardioSeries:
    """R-peak timestamps with per-interval classification labels.

    ``times`` : 1D float array of R-peak times in seconds.
    ``labels`` : 1D object array of the same length; ``labels[i]`` describes
    the interval from ``times[i]`` to ``times[i+1]``; the last element is a
    placeholder.

    IBIs are derived on demand from ``times`` via the ``ibi`` property.
    All label assignment goes through :meth:`classify_ibi`; call it after
    any mutation to ``times``.

    HRV metrics and PSD are not computed here — pass a ``CardioSeries``
    or ``CardioSeriesView`` to functions in ``spectHR.analysis``.
    """

    def __init__(self, times: np.ndarray) -> None:
        self.times = np.asarray(times, dtype=float)
        self.labels = np.full(self.times.shape, "N", dtype=object)
        self._pd: Optional["PhysioData"] = None
        self._stream: Optional[str] = None
        # When True, preprocess_ecg() skips R-peak re-detection; the times
        # are authoritative (e.g. loaded from a .evt file). The ECG can
        # still be filtered for display.
        self.rtops_locked: bool = False

    def link(self, pd: "PhysioData", stream: str) -> "CardioSeries":
        """Attach this series to its parent dataset and stream name.

        Sets the back-references the views rely on (``_pd`` for epoch
        lookups, ``_stream`` for identity) without callers reaching into
        private attributes. Returns ``self`` for chaining.
        """
        self._pd = pd
        self._stream = stream
        return self

    # ------------------------------------------------------------------
    # Construction / detection
    # ------------------------------------------------------------------

    @classmethod
    def from_timeseries(
        cls,
        ts,
        *,
        min_peak_distance_ms: float = 300.0,
        window_length: int   = DEFAULT_IBI_PARAMS.window_length,
        n_std:         float = DEFAULT_IBI_PARAMS.n_std,
        max_ibi_sec:   float = DEFAULT_IBI_PARAMS.max_ibi_sec,
        classify:      bool  = True,
    ) -> "CardioSeries":
        """Detect R-peaks from an ECG TimeSeries and construct a CardioSeries.

        Delegates peak detection to
        :func:`spectHR.Tools.RPeakDetection.detect_rpeaks`,
        then wraps the resulting timestamps in a ``CardioSeries`` and
        optionally classifies IBIs via :meth:`classify_ibi`.

        Parameters
        ----------
        ts : ECG time series with ``.times`` and ``.values`` attributes.
        min_peak_distance_ms : float
            Minimum R-R distance in ms (physiological refractory period).
        window_length : int
            Centered rolling window size passed to :meth:`classify_ibi`.
        n_std : float
            SD threshold passed to :meth:`classify_ibi`.
        max_ibi_sec : float
            Absolute ceiling passed to :meth:`classify_ibi`; intervals
            longer than this are labeled ``"TL"``.
        classify : bool
            If ``True``, run :meth:`classify_ibi` after peak detection.
        """
        from spectHR.Tools.RPeakDetection import detect_rpeaks

        peak_times = detect_rpeaks(ts, min_peak_distance_ms=min_peak_distance_ms)
        series = cls(peak_times)
        series.labels[:] = "N"
        if classify and series.times.size > 0:
            series.classify_ibi(
                window_length=window_length,
                n_std=n_std,
                max_ibi_sec=max_ibi_sec,
            )
        return series

    # ------------------------------------------------------------------
    # IBI - pure computation, no side effects
    # ------------------------------------------------------------------

    @property
    def ibi(self) -> np.ndarray:
        """IBIs in seconds; trailing NaN so ``len(ibi) == len(times)``.

        ``ibi[i]`` = ``times[i+1] - times[i]``; the last element is NaN.
        Pure computation — never mutates ``labels``.
        """
        if self.times.size < 2:
            return np.asarray([], dtype=float)
        return np.concatenate([np.diff(self.times), np.array([np.nan], dtype=float)])

    # ------------------------------------------------------------------
    # Classification - sole owner of label state
    # ------------------------------------------------------------------

    def classify_ibi(
        self,
        *,
        window_length: int   = DEFAULT_IBI_PARAMS.window_length,
        n_std:         float = DEFAULT_IBI_PARAMS.n_std,
        max_ibi_sec:   float = DEFAULT_IBI_PARAMS.max_ibi_sec,
    ) -> None:
        """
        Classify IBIs and assign labels.

        This is the sole method that mutates self.labels.
        Call it after any change to self.times.

        Labels produced
        ---------------
        "N"   - normal
        "L"   - long  (above rolling upper threshold)
        "S"   - short (below rolling lower threshold)
        "TL"  - too long (> max_ibi_sec); excluded from statistics
        "SL"  - short-then-long pattern
        "SNS" - short-normal-short pattern
        "T"   - degenerate (NaN or <= 0)

        Parameters
        ----------
        window_length : int
            Size of the centered rolling window (beats) for local mean/std.
        n_std : float
            Threshold multiplier: mean ± n_std × std defines S/L boundaries.
        max_ibi_sec : float
            Absolute ceiling; IBIs above this are labeled TL before rolling
            statistics are computed, so artefacts do not distort thresholds.
        """
        from spectHR.Tools.IbiClassification import classify_ibi
        classify_ibi(
            self.ibi,
            self.labels,
            window_length=window_length,
            n_std=n_std,
            max_ibi_sec=max_ibi_sec,
        )

    # ------------------------------------------------------------------
    # Editing / replacement
    # ------------------------------------------------------------------

    def replace_from_timeseries(
        self,
        ts,
        *,
        start: float,
        end: float,
        min_peak_distance_ms: float = 300.0,
        window_length: int   = DEFAULT_IBI_PARAMS.window_length,
        n_std:         float = DEFAULT_IBI_PARAMS.n_std,
        max_ibi_sec:   float = DEFAULT_IBI_PARAMS.max_ibi_sec,
        classify:      bool  = True,
    ) -> None:
        """
        Re-detect R-peaks inside [start, end] and merge with peaks outside.

        Designed for interactive editing: keeps R-peaks outside the window,
        replaces those inside with freshly detected ones, then optionally
        re-runs global classification with the supplied thresholds.
        """
        if start >= end:
            raise ValueError("replace_from_timeseries: start must be < end")

        if self.times.size == 0:
            new = CardioSeries.from_timeseries(
                ts,
                min_peak_distance_ms=min_peak_distance_ms,
                window_length=window_length,
                n_std=n_std,
                max_ibi_sec=max_ibi_sec,
                classify=classify,
            )
            self.times = new.times
            self.labels = new.labels
            return

        new = CardioSeries.from_timeseries(
            ts,
            min_peak_distance_ms=min_peak_distance_ms,
            window_length=window_length,
            n_std=n_std,
            max_ibi_sec=max_ibi_sec,
            classify=False,
        )
        new_labels = np.full(new.times.shape, "N", dtype=object)

        keep = (self.times < start) | (self.times > end)
        merged_times = np.concatenate([self.times[keep], new.times])
        merged_labels = np.concatenate([self.labels[keep], new_labels])

        if merged_times.size == 0:
            self.times = merged_times
            self.labels = merged_labels
            return

        order = np.argsort(merged_times)
        self.times = merged_times[order]
        self.labels = merged_labels[order]

        if classify:
            self.classify_ibi(
                window_length=window_length,
                n_std=n_std,
                max_ibi_sec=max_ibi_sec,
            )

    # ------------------------------------------------------------------
    # Views / slicing
    # ------------------------------------------------------------------

    def __getitem__(self, epoch_label: str) -> "CardioSeriesView":
        """
        Return an epoch-restricted view using PhysioData.epochs.

        Raises
        ------
        RuntimeError  If this CardioSeries is not linked to a PhysioData.
        KeyError      If the requested epoch does not exist.
        """
        from spectHR.DataSet.Series.CardioSeriesView import CardioSeriesView

        if self._pd is None:
            raise RuntimeError(
                "CardioSeries is not connected to a PhysioData instance. "
                "Assign CardioSeries._pd = physiodata."
            )
        if epoch_label not in self._pd.epochs:
            raise KeyError(f"No epoch '{epoch_label}' in PhysioData.")

        ep = self._pd.epochs[epoch_label]
        idx = np.where((self.times >= ep.start) & (self.times <= ep.end))[0]
        v = CardioSeriesView(self, idx)
        v._pd = self._pd
        v._stream = self._stream
        v._epoch = epoch_label
        return v

    def view(self, starttime: float, endtime: float) -> "CardioSeriesView":
        """Return a zero-copy view restricted to [starttime, endtime]."""
        from spectHR.DataSet.Series.CardioSeriesView import CardioSeriesView

        idx = np.where((self.times >= starttime) & (self.times <= endtime))[0]
        v = CardioSeriesView(self, idx)
        v._pd = self._pd
        v._stream = self._stream
        v._epoch = None
        return v

    def window(self, start: float, end: float) -> "CardioSeriesView":
        """Canonical windowing name; delegates to view()."""
        return self.view(start, end)

    def __repr__(self) -> str:
        return f"CardioSeries(n={self.times.size}, stream={self._stream!r})"
