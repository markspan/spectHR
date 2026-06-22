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
functional, every modifying method returns a new object.

*Zero-copy windowing.*  ``obj.window(start, end)`` uses ``np.searchsorted``
on the sorted time axis to locate the slice boundaries in O(log n) and
returns a new object whose arrays are numpy *views* of the parent's arrays
- no heap allocation beyond the three new Python objects.

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
# Samples, continuous 1-D waveform
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
        from spectHR.signal.filters import butterworth_filter
        if self.srate is None:
            raise ValueError("Cannot filter Samples with unknown sampling rate.")
        filtered = butterworth_filter(self.values, self.srate,
                                      filter_type=filter_type, cutoff=cutoff, order=order)
        return Samples(self.times, filtered, self.name)


# ---------------------------------------------------------------------------
# Events, point process with categorical labels
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
        from spectHR.signal.rpeak import detect_rpeaks
        from spectHR.signal.ibi_classification import classify_ibi as _classify_ibi

        peak_times = detect_rpeaks(signal, min_peak_distance_ms=min_peak_distance_ms)
        labels = np.full(peak_times.shape, "N", dtype=object)
        if classify and peak_times.size > 1:
            ibi = np.concatenate([np.diff(peak_times), [np.nan]])
            _classify_ibi(ibi, labels,
                          window_length=window_length, n_std=n_std, max_ibi_sec=max_ibi_sec)
        return cls(times=peak_times, labels=labels)

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

    # --- single-beat editing (functional; used by interactive R-peak editors) ---

    def added(self, t: float, label: str = "N") -> Events:
        """Return a new ``Events`` with one beat inserted at *t* (kept sorted)."""
        idx = int(np.searchsorted(self.times, t))
        return Events(
            np.insert(self.times, idx, float(t)),
            np.insert(self.labels, idx, label),
        )

    def moved(self, old_t: float, new_t: float) -> Events:
        """Return a new ``Events`` with the beat nearest *old_t* moved to *new_t*.

        The series is re-sorted so times stay ascending; the moved beat keeps
        its label.  Returns ``self`` unchanged when there are no beats.
        """
        if self.times.size == 0:
            return self
        times = self.times.copy()
        idx = int(np.argmin(np.abs(times - old_t)))
        times[idx] = float(new_t)
        order = np.argsort(times, kind="stable")
        return Events(times[order], self.labels[order])

    def removed(self, t: float) -> Events:
        """Return a new ``Events`` with the beat nearest *t* removed.

        Returns ``self`` unchanged when there are no beats.
        """
        if self.times.size == 0:
            return self
        idx = int(np.argmin(np.abs(self.times - t)))
        return Events(np.delete(self.times, idx), np.delete(self.labels, idx))

    def reclassified(self, **classify_kwargs) -> Events:
        """Return a new ``Events`` with labels recomputed by ``classify_ibi``.

        Keyword args (``window_length`` / ``n_std`` / ``max_ibi_sec``) are
        forwarded to :func:`~spectHR.signal.ibi_classification.classify_ibi`;
        omit them to use the classifier's own defaults.
        """
        from spectHR.signal.ibi_classification import classify_ibi
        labels = np.array(self.labels, dtype=object)        # writable copy
        classify_ibi(np.array(self.ibi, dtype=float), labels, **classify_kwargs)
        return Events(self.times, labels)

    # --- abnormal-beat queries (for "jump to next/previous artefact") ---

    def abnormal_mask(self) -> np.ndarray:
        """Boolean mask of abnormal beats (label != ``"N"``).

        The final beat is always excluded: its IBI is the trailing-``NaN``
        sentinel, so :func:`classify_ibi` labels it ``"T"`` (degenerate) even
        though it is not a real artefact, without this it would be a phantom
        target at the very end of every recording.
        """
        mask = self.labels != "N"
        if mask.size:
            mask[-1] = False
        return mask

    def next_abnormal(self, after: float) -> float | None:
        """Time of the first abnormal beat strictly after *after*, or ``None``."""
        mask = self.abnormal_mask() & (self.times > after)
        return float(self.times[mask][0]) if mask.any() else None

    def prev_abnormal(self, before: float) -> float | None:
        """Time of the last abnormal beat strictly before *before*, or ``None``."""
        mask = self.abnormal_mask() & (self.times < before)
        return float(self.times[mask][-1]) if mask.any() else None


# ---------------------------------------------------------------------------
# Intervals, labelled non-overlapping time segments
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
        from spectHR.signal.respiration import segment_respiration

        starts, ends, labels = segment_respiration(signal, smoothing_window=smooth_window)
        return cls(
            starts=np.asarray(starts, dtype=np.float64),
            ends=np.asarray(ends,     dtype=np.float64),
            labels=np.asarray(labels, dtype=object),
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

        Example, compute a metric per inhalation phase::

            for t0, t1 in session.intervals["breath"].windows_of("INH"):
                ibi_in_phase = session.events["hrv"].window(t0, t1)
                ...
        """
        subset = self.of(label)
        yield from zip(subset.starts.tolist(), subset.ends.tolist())
