# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/session/_data.py
"""
Immutable physiological data primitives.

Three core types — :class:`Signal`, :class:`Beats`, :class:`BreathPhases` —
own their arrays and make them read-only at construction.  Each exposes a
:meth:`slice` factory that returns a zero-copy index view of the same type.
Views also carry a :meth:`view` alias so they are drop-in replacements for
the legacy ``TimeSeries`` / ``CardioSeriesView`` interface used by the
existing analysis layer.

Design rules
------------
* All stored numpy arrays are frozen (``writeable=False``) at construction.
* Updates are functional: every mutation returns a *new* object.
* No back-references to sessions, datasets, or workspaces.
* Views satisfy the same Protocol as their parent so they are usable
  anywhere the parent is accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


# ---------------------------------------------------------------------------
# Protocols — document the expected interface
# ---------------------------------------------------------------------------

class SignalLike(Protocol):
    @property
    def times(self) -> np.ndarray: ...
    @property
    def values(self) -> np.ndarray: ...
    def slice(self, start: float, end: float) -> SignalSlice: ...


class BeatLike(Protocol):
    @property
    def times(self) -> np.ndarray: ...
    @property
    def labels(self) -> np.ndarray: ...
    @property
    def ibi(self) -> np.ndarray: ...
    def slice(self, start: float, end: float) -> BeatSlice: ...


class PhaseLike(Protocol):
    @property
    def starts(self) -> np.ndarray: ...
    @property
    def ends(self) -> np.ndarray: ...
    @property
    def labels(self) -> np.ndarray: ...
    def slice(self, start: float, end: float) -> PhaseSlice: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ro(arr: np.ndarray) -> np.ndarray:
    """Return *arr* as a read-only float64 array (zero-copy if already so)."""
    a = np.asarray(arr, dtype=np.float64)
    a.flags.writeable = False
    return a


def _ro_obj(arr: np.ndarray) -> np.ndarray:
    """Return *arr* as a read-only object array."""
    a = np.asarray(arr, dtype=object)
    a.flags.writeable = False
    return a


def _ibi_from_times(times: np.ndarray) -> np.ndarray:
    if times.size < 2:
        return np.array([np.nan], dtype=np.float64)
    return np.concatenate([np.diff(times), [np.nan]])


# ---------------------------------------------------------------------------
# Signal — continuous 1-D waveform
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Signal:
    """Continuous 1-D waveform.  Both arrays are read-only float64."""

    times:  np.ndarray
    values: np.ndarray
    name:   str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "times",  _ro(self.times))
        object.__setattr__(self, "values", _ro(self.values))

    # --- derived ---

    @property
    def srate(self) -> float | None:
        if self.times.size < 2:
            return None
        return float(1.0 / np.median(np.diff(self.times)))

    # --- slicing ---

    def slice(self, start: float, end: float) -> SignalSlice:
        idx = np.where((self.times >= start) & (self.times <= end))[0]
        return SignalSlice(self, idx)

    # --- functional update ---

    def with_values(self, values: np.ndarray) -> Signal:
        """Return a new Signal with the same times but replaced values."""
        return Signal(self.times, values, self.name)

    def with_name(self, name: str) -> Signal:
        return Signal(self.times, self.values, name)


@dataclass(frozen=True)
class SignalSlice:
    """Zero-copy view into a :class:`Signal`."""

    _signal: Signal
    _idx:    np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "_idx", np.asarray(self._idx, dtype=np.intp))

    @property
    def times(self) -> np.ndarray:
        return self._signal.times[self._idx]

    @property
    def values(self) -> np.ndarray:
        return self._signal.values[self._idx]

    @property
    def srate(self) -> float | None:
        t = self.times
        return None if t.size < 2 else float(1.0 / np.median(np.diff(t)))

    def slice(self, start: float, end: float) -> SignalSlice:
        t = self.times
        sub = np.where((t >= start) & (t <= end))[0]
        return SignalSlice(self._signal, self._idx[sub])


# ---------------------------------------------------------------------------
# Beats — R-peak timestamps with per-beat labels
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Beats:
    """R-peak (or any beat) timestamps with per-beat classification labels.

    Both arrays are read-only and parallel: ``times[i]`` has label
    ``labels[i]``.  Updates (labelling, window replacement) return a new
    ``Beats`` instance — no in-place mutation.
    """

    times:  np.ndarray   # float64, sorted ascending
    labels: np.ndarray   # object (strings, e.g. "N", "V", "A")

    def __post_init__(self) -> None:
        object.__setattr__(self, "times",  _ro(self.times))
        object.__setattr__(self, "labels", _ro_obj(self.labels))

    # --- factory ---

    @classmethod
    def detect(
        cls,
        signal: Signal | SignalSlice,
        *,
        min_peak_distance_ms: float = 300.0,
        window_length: int = 20,
        n_std: float = 3.0,
        max_ibi_sec: float = 2.5,
        classify: bool = True,
    ) -> Beats:
        """Detect R-peaks in *signal* and return a :class:`Beats` instance."""
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
        return cls(cs.times, cs.labels)

    # --- derived ---

    @property
    def ibi(self) -> np.ndarray:
        """IBIs in seconds with a trailing NaN."""
        return _ibi_from_times(self.times)

    # --- slicing ---

    def slice(self, start: float, end: float) -> BeatSlice:
        idx = np.where((self.times >= start) & (self.times <= end))[0]
        return BeatSlice(self, idx)


    # --- functional updates ---

    def with_labels(self, new_labels: np.ndarray) -> Beats:
        """Return new Beats with updated labels (pure function)."""
        return Beats(self.times, new_labels)

    def replace_window(self, start: float, end: float, new_beats: Beats) -> Beats:
        """Return new Beats with the [start, end] window replaced."""
        keep = (self.times < start) | (self.times > end)
        times  = np.concatenate([self.times[keep],  new_beats.times])
        labels = np.concatenate([self.labels[keep], new_beats.labels])
        order  = np.argsort(times, kind="stable")
        return Beats(times[order], labels[order])


@dataclass(frozen=True)
class BeatSlice:
    """Zero-copy view into a :class:`Beats`."""

    _beats: Beats
    _idx:   np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "_idx", np.asarray(self._idx, dtype=np.intp))

    @property
    def times(self) -> np.ndarray:
        return self._beats.times[self._idx]

    @property
    def labels(self) -> np.ndarray:
        return self._beats.labels[self._idx]

    @property
    def ibi(self) -> np.ndarray:
        return _ibi_from_times(self.times)

    def slice(self, start: float, end: float) -> BeatSlice:
        t = self.times
        sub = np.where((t >= start) & (t <= end))[0]
        return BeatSlice(self._beats, self._idx[sub])



# ---------------------------------------------------------------------------
# BreathPhases — INH / EXH phase intervals
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BreathPhases:
    """Respiration phase intervals (INH / EXH).

    ``starts``, ``ends``, and ``labels`` are parallel read-only arrays.
    """

    starts: np.ndarray
    ends:   np.ndarray
    labels: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "starts", _ro(self.starts))
        object.__setattr__(self, "ends",   _ro(self.ends))
        object.__setattr__(self, "labels", _ro_obj(self.labels))

    def __len__(self) -> int:
        return int(self.starts.size)

    def slice(self, start: float, end: float) -> PhaseSlice:
        """Return phases that overlap [start, end]."""
        idx = np.where((self.ends >= start) & (self.starts <= end))[0]
        return PhaseSlice(self, idx)



@dataclass(frozen=True)
class PhaseSlice:
    """Zero-copy view into :class:`BreathPhases`."""

    _phases: BreathPhases
    _idx:    np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "_idx", np.asarray(self._idx, dtype=np.intp))

    @property
    def starts(self) -> np.ndarray:
        return self._phases.starts[self._idx]

    @property
    def ends(self) -> np.ndarray:
        return self._phases.ends[self._idx]

    @property
    def labels(self) -> np.ndarray:
        return self._phases.labels[self._idx]

    def __len__(self) -> int:
        return int(self._idx.size)

    def slice(self, start: float, end: float) -> PhaseSlice:
        sub = np.where((self.ends >= start) & (self.starts <= end))[0]
        return PhaseSlice(self._phases, self._idx[sub])

