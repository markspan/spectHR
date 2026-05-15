# spectHR/DataSet/Series/CardioSeries.py
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import numpy as np
import scipy.signal as signal

from spectHR.DataSet.Series.CardioMetricsMixin import CardioMetricsMixin
from spectHR.DataSet.Series.IBIClassificationParams import DEFAULT_IBI_PARAMS
from spectHR.Tools.Logger import logger

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData
    from spectHR.DataSet.Series.CardioSeriesView import CardioSeriesView


class CardioSeries(CardioMetricsMixin):
    """
    Container for R-peak times and per-interval labels, with HRV metric methods.

    Conceptual model
    ----------------
    A CardioSeries *owns* a sequence of R-peak timestamps (seconds, dataset
    time base).  Inter-beat intervals (IBIs) are derived on demand from those
    times.

    Data arrays
    -----------
    times  : 1D float array of R-peak times in seconds.
    labels : 1D object array of per-interval labels (same length as times).
             labels[i] describes the interval between times[i] and times[i+1].
             The final element is present for alignment but unused.

    Label lifecycle
    ---------------
    All label assignment is the sole responsibility of classify_ibi().
    The ibi property is a pure computation and never mutates labels.
    Call classify_ibi() after any mutation to times.

    Relationship to views
    ---------------------
    CardioSeries.view() and CardioSeries.__getitem__() return CardioSeriesView
    objects (defined in CardioSeriesView.py).  Views do NOT inherit from
    CardioSeries — they use composition and share metric methods via
    CardioMetricsMixin.  Use CardioSeriesLike (CardioSeriesProtocol.py) for
    type annotations where either is acceptable.
    """

    def __init__(self, times: np.ndarray) -> None:
        self.times = np.asarray(times, dtype=float)
        self.labels = np.full(self.times.shape, "N", dtype=object)
        self._pd: Optional["PhysioData"] = None
        self._stream: Optional[str] = None
        # When True, preprocess_ecg() must NOT re-detect R-peaks from the ECG
        # signal — the times are authoritative (e.g. loaded from a CARSPAN
        # .evt alongside an .nff). The ECG can still be filtered for display.
        self.rtops_locked: bool = False

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
        """
        Detect R-peaks from an ECG TimeSeries and construct a CardioSeries.

        Steps
        -----
        1. Estimate sampling rate from ts.times.
        2. Detect candidate peaks with scipy.signal.find_peaks.
           The minimum peak distance enforces a physiological refractory
           period equivalent to CARSPAN's Trefr (default 300 ms → max ~200 bpm).
        3. Apply a lightweight sub-sample timing correction.
        4. Initialise labels to "N".
        5. Optionally classify IBIs via classify_ibi().

        Parameters
        ----------
        ts : ECG time series with .times and .values attributes.
        min_peak_distance_ms : Minimum R-R distance in milliseconds.
            Beats closer than this cannot be detected, acting as a
            refractory period (CARSPAN: Trefr = 300 ms).
        window_length : Passed to classify_ibi() — centered rolling window
            size in beats.
        n_std : Passed to classify_ibi() — threshold in standard deviations.
        max_ibi_sec : Passed to classify_ibi() — absolute ceiling for IBI
            length; longer intervals are labeled "TL".
        classify : If True, run classify_ibi() after peak detection.
        """
        times = np.asarray(ts.times, dtype=float)
        values = np.asarray(ts.values, dtype=float)

        if times.size < 2 or values.size < 2:
            logger.warning("ECG TimeSeries too short for peak detection.")
            return cls(np.array([], dtype=float))

        time_deltas = np.diff(times)
        time_deltas = time_deltas[time_deltas > 0]
        if time_deltas.size == 0:
            raise ValueError(
                "Cannot estimate sampling rate from ECG times (no positive deltas)."
            )

        sampling_rate_hz = 1.0 / float(np.mean(time_deltas))
        min_distance_samples = max(
            1, int((min_peak_distance_ms / 1000.0) * sampling_rate_hz)
        )
        peak_height_threshold = float(np.median(values) + 1.5 * np.std(values))

        peak_indices, _ = signal.find_peaks(
            values,
            height=peak_height_threshold,
            distance=min_distance_samples,
        )

        if peak_indices.size == 0:
            logger.warning("No R-peaks detected.")
            return cls(np.array([], dtype=float))

        # Sub-sample timing correction
        pre_values = values[np.clip(peak_indices - 1, 0, values.size - 1)]
        post_values = values[np.clip(peak_indices + 1, 0, values.size - 1)]
        peak_values = values[peak_indices]
        local_contrast = np.maximum(
            np.abs(peak_values - pre_values),
            np.abs(post_values - peak_values),
        )
        local_contrast[local_contrast == 0] = 1e-12
        correction_sec = (
            (post_values - pre_values) / sampling_rate_hz / (2.0 * local_contrast)
        )
        peak_times = times[peak_indices] + correction_sec

        series = cls(np.asarray(peak_times, dtype=float))
        series.labels[:] = "N"
        if classify:
            series.classify_ibi(
                window_length=window_length,
                n_std=n_std,
                max_ibi_sec=max_ibi_sec,
            )
        return series

    # ------------------------------------------------------------------
    # IBI — pure computation, no side effects
    # ------------------------------------------------------------------

    @property
    def ibi(self) -> np.ndarray:
        """
        Inter-beat intervals in seconds, with a trailing NaN for alignment.

        len(ibi) == len(times).
        ibi[i] is the interval between times[i] and times[i+1].
        The final element is always NaN.

        Pure computation — never mutates self.labels.
        Call classify_ibi() after any mutation to times.
        """
        if self.times.size < 2:
            return np.asarray([], dtype=float)
        return np.concatenate([np.diff(self.times), np.array([np.nan], dtype=float)])

    # ------------------------------------------------------------------
    # Classification — sole owner of label state
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
        "N"   — normal
        "L"   — long  (above rolling upper threshold)
        "S"   — short (below rolling lower threshold)
        "TL"  — too long (> max_ibi_sec); excluded from statistics
        "SL"  — short-then-long pattern
        "SNS" — short-normal-short pattern
        "T"   — degenerate (NaN or <= 0)

        Parameters
        ----------
        window_length : int
            Size of the centered rolling window (beats) for local mean/std.
            Loaded from workspace["CardioParameters"]["IbiClassification"]
            ["window_length"].
        n_std : float
            Threshold multiplier: mean ± n_std × std defines S/L boundaries.
            Loaded from workspace["CardioParameters"]["IbiClassification"]
            ["n_std"].
        max_ibi_sec : float
            Absolute ceiling; IBIs above this are labeled TL before rolling
            statistics are computed, so artifacts do not distort thresholds.
            Loaded from workspace["CardioParameters"]["IbiClassification"]
            ["max_ibi_sec"].
        """
        ibi_sec = self.ibi  # pure — no side effects
        labels = self.labels
        n = ibi_sec.size

        if n == 0:
            return

        # Step 1: degenerate and too-long
        degenerate = np.isnan(ibi_sec) | (ibi_sec <= 0)
        labels[degenerate] = "T"
        too_long = ibi_sec > max_ibi_sec
        labels[too_long] = "TL"

        # Step 2: IBI array for statistics (exclude T and TL)
        ibi_stats = ibi_sec.astype(float, copy=True)
        ibi_stats[degenerate | too_long] = np.nan

        if ibi_stats.size >= 2 and np.isnan(ibi_stats[-1]):
            last_valid = ibi_stats[~np.isnan(ibi_stats)]
            if last_valid.size > 0:
                ibi_stats[-1] = last_valid[-1]

        if not np.any(~np.isnan(ibi_stats)):
            return

        # Step 3: short-series fallback
        if n < window_length:
            mean = np.nanmean(ibi_stats)
            std = np.nanstd(ibi_stats)
            lo, hi = mean - n_std * std, mean + n_std * std
            for i in range(n):
                if labels[i] in ("T", "TL"):
                    continue
                labels[i] = "L" if ibi_sec[i] > hi else "S" if ibi_sec[i] < lo else "N"
            return

        # Step 4: rolling statistics (centered window)
        half = window_length // 2
        padded = np.pad(ibi_stats, (half, half), mode="edge")
        windows = np.lib.stride_tricks.sliding_window_view(padded, window_length)
        local_mean = np.nanmean(windows, axis=1)[:n]
        local_std = np.nanstd(windows, axis=1)[:n]
        lo = local_mean - n_std * local_std
        hi = local_mean + n_std * local_std

        # Step 5: pointwise classification
        for i in range(n):
            if labels[i] in ("T", "TL"):
                continue
            labels[i] = (
                "L" if ibi_sec[i] > hi[i] else "S" if ibi_sec[i] < lo[i] else "N"
            )

        # Step 6: sequence heuristics
        for i in range(n - 1):
            if labels[i] == "S" and labels[i + 1] == "L":
                labels[i] = "SL"
        for i in range(n - 2):
            if labels[i] == "S" and labels[i + 1] == "N" and labels[i + 2] == "S":
                labels[i] = "SNS"

        # Step 7: summary
        unique, counts = np.unique(labels, return_counts=True)
        logger.info(f"IBI classification summary (n_IBI={n}):")
        for lab, cnt in zip(unique, counts):
            logger.info(f"  {lab}: {cnt}")

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

    # ------------------------------------------------------------------
    # Epoch aggregation
    # ------------------------------------------------------------------

    def hrv_epoch_table(
        self,
        physiodata: "PhysioData",
    ) -> Tuple[np.ndarray, List[str], np.ndarray]:
        """
        Compute all HRV metrics for every active epoch in physiodata.

        Returns
        -------
        labels : np.ndarray (n_epochs,)   — epoch names
        cols   : list[str]                — metric names in METRIC_ORDER
        values : np.ndarray (n_epochs, n_metrics) — float64, NaN for missing
        """
        labels_list: List[Any] = []
        rows: List[Dict[str, float]] = []

        for label, ep in physiodata.epochs.items():
            if getattr(ep, "active", False):
                labels_list.append(label)
                rows.append(self.metric_table_epoch(ep.start, ep.end))

        if not rows:
            return np.array([], dtype=object), [], np.empty((0, 0), dtype=float)

        keys = set().union(*(d.keys() for d in rows))
        cols = [c for c in self.METRIC_ORDER if c in keys]
        cols.extend(sorted(keys - set(cols)))
        col_idx = {c: j for j, c in enumerate(cols)}

        values = np.full((len(rows), len(cols)), np.nan, dtype=float)
        for i, d in enumerate(rows):
            for k, v in d.items():
                j = col_idx.get(k)
                if j is not None:
                    values[i, j] = float(v)

        return np.asarray(labels_list, dtype=object), cols, values

    def __repr__(self) -> str:
        return f"CardioSeries(n={self.times.size}, stream={self._stream!r})"
