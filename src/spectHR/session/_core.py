# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/session/_core.py
"""
Three immutable data primitives that cover every physiological time series.

``Samples``
    Continuous 1-D waveform: ECG, respiration, blood pressure, ICG.
``Events``
    Point process with categorical labels: R-peaks, trigger pulses,
    any annotation at a point in time.
``Intervals``
    Non-overlapping labelled segments: INH/EXH breath phases, task
    conditions, artefact windows.

Design rules
------------
*Immutable.*  All arrays are read-only at construction.  Updates are
functional — every modifying method returns a new object.

*Zero-copy windowing.*  ``obj.window(start, end)`` uses ``np.searchsorted``
on the sorted time axis to locate the slice boundaries in O(log n) and
returns a new object whose arrays are numpy *views* of the parent's arrays
— no heap allocation beyond the three new Python objects.

*No separate slice type.*  Windowing returns the same type as the
parent.  Code written for a full ``Events`` works identically on a
windowed ``Events``.

*Cached derivations.*  ``Events.ibi`` is a ``cached_property``; the first
access pays the O(n) cost and all subsequent accesses are free.  This works
with ``frozen=True`` because ``cached_property`` writes directly to
``__dict__``, bypassing ``__setattr__``.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Iterator, Protocol

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ro(arr) -> np.ndarray:
    """Return *arr* as a read-only float64 ndarray (zero-copy when possible)."""
    a = np.asarray(arr, dtype=np.float64)
    a.flags.writeable = False
    return a


def _ro_obj(arr) -> np.ndarray:
    """Return *arr* as a read-only object ndarray."""
    a = np.asarray(arr, dtype=object)
    a.flags.writeable = False
    return a


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

class SamplesLike(Protocol):
    @property
    def times(self)  -> np.ndarray: ...
    @property
    def values(self) -> np.ndarray: ...


class EventsLike(Protocol):
    @property
    def times(self)  -> np.ndarray: ...
    @property
    def labels(self) -> np.ndarray: ...
    @property
    def ibi(self)    -> np.ndarray: ...


class IntervalsLike(Protocol):
    @property
    def starts(self) -> np.ndarray: ...
    @property
    def ends(self)   -> np.ndarray: ...
    @property
    def labels(self) -> np.ndarray: ...
    def __len__(self) -> int: ...


# ---------------------------------------------------------------------------
# Samples — continuous 1-D waveform
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=False)
class Samples:
    """Continuous 1-D waveform sampled at irregular or regular intervals.

    ``times`` must be sorted ascending.  Both arrays are read-only.

    Typical channels: ``"ecg"``, ``"resp"``, ``"bp"``, ``"icg"``.
    """

    times:  np.ndarray
    values: np.ndarray
    name:   str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "times",  _ro(self.times))
        object.__setattr__(self, "values", _ro(self.values))

    # --- derived ---

    @property
    def srate(self) -> float | None:
        """Median sampling rate in Hz, or ``None`` for fewer than 2 samples."""
        if self.times.size < 2:
            return None
        return float(1.0 / np.median(np.diff(self.times)))

    # --- zero-copy windowing ---

    def window(self, start: float, end: float) -> Samples:
        """Return a zero-copy view restricted to ``[start, end]`` (O(log n))."""
        i = int(np.searchsorted(self.times, start, side="left"))
        j = int(np.searchsorted(self.times, end,   side="right"))
        return Samples(self.times[i:j], self.values[i:j], self.name)

    # --- functional updates ---

    def with_values(self, values: np.ndarray) -> Samples:
        """New ``Samples`` with the same times but replaced values."""
        return Samples(self.times, values, self.name)

    def filtered(self, *, filter_type: str, cutoff, order: int = 4) -> Samples:
        """Return a new ``Samples`` with band-pass / low-pass filtered values."""
        from spectHR.DataSet.Series.TimeSeries import TimeSeries as _TS
        ts = _TS(times=self.times.copy(), values=self.values.copy())
        ts.filter(filter_type, cutoff, order, inplace=True)
        return Samples(self.times, ts.values, self.name)


# ---------------------------------------------------------------------------
# Events — point process with categorical labels
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=False)
class Events:
    """Irregularly timed point events with per-event categorical labels.

    ``times`` must be sorted ascending.  Both arrays are read-only.

    Typical uses: R-peaks (labels ``"N"``/``"V"``/``"A"``), trigger
    pulses, artefact markers.

    The ``ibi`` property (inter-event intervals) is cached on first
    access so multiple metric functions pay the O(n) cost at most once.
    """

    times:  np.ndarray   # float64, sorted ascending
    labels: np.ndarray   # object dtype (str labels)

    def __post_init__(self) -> None:
        object.__setattr__(self, "times",  _ro(self.times))
        object.__setattr__(self, "labels", _ro_obj(self.labels))

    # --- derived (cached) ---

    @cached_property
    def ibi(self) -> np.ndarray:
        """Inter-event intervals in seconds, with a trailing ``NaN``."""
        t = self.times
        if t.size < 2:
            return np.array([np.nan], dtype=np.float64)
        out = np.empty(t.size, dtype=np.float64)
        out[:-1] = np.diff(t)
        out[-1]  = np.nan
        return out

    # --- factory ---

    @classmethod
    def detect(
        cls,
        signal: Samples,
        *,
        min_peak_distance_ms: float = 300.0,
        window_length: int = 20,
        n_std: float = 3.0,
        max_ibi_sec: float = 2.5,
        classify: bool = True,
    ) -> Events:
        """Detect R-peaks in *signal* and return a labelled ``Events``.

        Delegates to the existing peak-detector so all tuning parameters
        and artefact-classification logic are preserved.
        """
        from spectHR.DataSet.Series.CardioSeries import CardioSeries
        from spectHR.DataSet.Series.TimeSeries import TimeSeries as _TS
        ts = _TS(
            times=np.asarray(signal.times,  dtype=float),
            values=np.asarray(signal.values, dtype=float),
        )
        cs = CardioSeries.from_timeseries(
            ts,
            min_peak_distance_ms=min_peak_distance_ms,
            window_length=window_length,
            n_std=n_std,
            max_ibi_sec=max_ibi_sec,
            classify=classify,
        )
        return cls(times=cs.times, labels=cs.labels)

    # --- zero-copy windowing and filtering ---

    def window(self, start: float, end: float) -> Events:
        """Return a zero-copy view restricted to ``[start, end]`` (O(log n))."""
        i = int(np.searchsorted(self.times, start, side="left"))
        j = int(np.searchsorted(self.times, end,   side="right"))
        return Events(self.times[i:j], self.labels[i:j])

    def of(self, label: str) -> Events:
        """Subset to events whose label equals *label*."""
        mask = self.labels == label
        return Events(self.times[mask], self.labels[mask])

    # --- functional updates ---

    def with_labels(self, labels: np.ndarray) -> Events:
        """New ``Events`` with the same times but replaced labels."""
        return Events(self.times, labels)

    def replace_window(self, start: float, end: float, other: Events) -> Events:
        """Replace all events in ``[start, end]`` with *other* (functional)."""
        i = int(np.searchsorted(self.times, start, side="left"))
        j = int(np.searchsorted(self.times, end,   side="right"))
        times  = np.concatenate([self.times[:i],  other.times,  self.times[j:]])
        labels = np.concatenate([self.labels[:i], other.labels, self.labels[j:]])
        return Events(times, labels)


# ---------------------------------------------------------------------------
# Intervals — labelled non-overlapping time segments
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=False)
class Intervals:
    """Non-overlapping labelled time intervals.

    ``starts`` must be sorted ascending.  All three arrays are read-only
    and parallel: ``starts[i]``, ``ends[i]``, ``labels[i]`` describe one
    interval.

    Typical uses: INH/EXH breath phases, task condition segments,
    artefact windows.
    """

    starts: np.ndarray   # float64, sorted ascending
    ends:   np.ndarray   # float64
    labels: np.ndarray   # object dtype (str labels)

    def __post_init__(self) -> None:
        object.__setattr__(self, "starts", _ro(self.starts))
        object.__setattr__(self, "ends",   _ro(self.ends))
        object.__setattr__(self, "labels", _ro_obj(self.labels))

    def __len__(self) -> int:
        return int(self.starts.size)

    # --- factory ---

    @classmethod
    def detect_breath_phases(
        cls,
        signal: Samples,
        events: Events,
        *,
        smooth_window: int = 5,
    ) -> Intervals:
        """Detect INH/EXH phases from a respiration *signal*.

        Uses the existing ``RespirationSeries`` detector.  *events* is the
        beat series used to set epoch boundaries for per-epoch segmentation.
        """
        from spectHR.DataSet.Series.RespirationSeries import RespirationSeries
        from spectHR.DataSet.Series.TimeSeries import TimeSeries as _TS
        rsp_ts = _TS(
            times=np.asarray(signal.times,  dtype=float),
            values=np.asarray(signal.values, dtype=float),
        )
        rs = RespirationSeries.from_timeseries(rsp_ts, smooth_window=smooth_window)
        return cls(
            starts=np.asarray(rs.starts, dtype=np.float64),
            ends=np.asarray(rs.ends,     dtype=np.float64),
            labels=np.asarray(rs.labels, dtype=object),
        )

    # --- zero-copy windowing and filtering ---

    def window(self, start: float, end: float) -> Intervals:
        """Zero-copy view of intervals that overlap ``[start, end]`` (O(log n)).

        Uses binary search on the sorted ``ends`` and ``starts`` arrays so
        no element-wise comparison is needed.
        """
        i = int(np.searchsorted(self.ends,   start, side="left"))
        j = int(np.searchsorted(self.starts, end,   side="right"))
        return Intervals(self.starts[i:j], self.ends[i:j], self.labels[i:j])

    def of(self, label: str) -> Intervals:
        """Subset to intervals whose label equals *label*."""
        mask = self.labels == label
        return Intervals(self.starts[mask], self.ends[mask], self.labels[mask])

    # --- iteration helpers ---

    def windows_of(self, label: str) -> Iterator[tuple[float, float]]:
        """Yield ``(start, end)`` pairs for all intervals with *label*.

        Example — compute a metric per inhalation phase::

            for t0, t1 in session.intervals["breath"].windows_of("INH"):
                ibi_in_phase = session.events["hrv"].window(t0, t1)
                ...
        """
        subset = self.of(label)
        yield from zip(subset.starts.tolist(), subset.ends.tolist())
