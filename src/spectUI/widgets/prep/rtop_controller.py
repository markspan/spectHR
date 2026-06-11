# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
A mutable editing facade over the immutable ``"hrv"`` :class:`Events` channel.

The R-peak *algorithms* — insert / move / delete / re-classify, and the
"jump to the next abnormal beat" queries — all live on
:class:`spectHR.session.Events` as functional methods that return a new
``Events``.  :class:`RTopController` adds the only thing the data model
should not own: the *editing-session* state.  It holds the current
``Events``, replaces it with the result of each edit, and commits that back
into ``session.events["hrv"]``.

Because :class:`~spectHR.session.Session` is a plain (non-frozen) dataclass,
that commit is seen immediately by every other holder of the same session —
the call-by-reference convenience V2 had from its mutable ``CardioSeries``,
without giving up array immutability in the analysis layer.

Two tiers of edit are exposed:

``*_no_classify``
    Apply the structural change and commit, leaving labels untouched — used
    for instant feedback during a drag, with re-classification scheduled on
    a background thread.
``add`` / ``move`` / ``delete``
    Apply the change *and* re-classify synchronously — for scripted or test
    edits where labels must be correct on the next read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from spectHR.session import Events, Session


@dataclass(frozen=True)
class RTopView:
    """An immutable slice of R-peaks for one time window (for rendering).

    Attributes
    ----------
    times
        Peak times within the window, in seconds.
    labels
        Beat labels parallel to ``times``.
    ibi
        Inter-beat intervals parallel to ``times``; the entry for the last
        peak of the whole series is ``NaN``.
    """

    times: np.ndarray
    labels: np.ndarray
    ibi: np.ndarray


class RTopController:
    """Edit the ``"hrv"`` R-peaks of a live session, committing each change.

    Parameters
    ----------
    session
        The session to edit.  Must contain an ``events["hrv"]``
        :class:`Events`; a :class:`ValueError` is raised otherwise.
    classify_params
        Keyword args forwarded to :meth:`Events.reclassified`
        (``window_length`` / ``n_std`` / ``max_ibi_sec``).  The widget passes
        the workspace ``CardioParameters`` so a post-edit re-classification
        uses exactly the thresholds the initial detection used; omit them to
        use the classifier defaults.
    """

    EVENTS_KEY = "hrv"

    def __init__(
        self,
        session: Session,
        classify_params: "dict[str, Any] | None" = None,
    ) -> None:
        hrv = session.events.get(self.EVENTS_KEY)
        if hrv is None:
            raise ValueError("Session has no 'hrv' Events channel to edit.")
        self._session = session
        self._events: Events = hrv
        self._classify_params: dict[str, Any] = dict(classify_params or {})

    # ------------------------------------------------------------------
    # Read access (delegated to the current Events)
    # ------------------------------------------------------------------

    @property
    def events(self) -> Events:
        """The current (uncommitted-edit-free) :class:`Events`."""
        return self._events

    @property
    def times(self) -> np.ndarray:
        """Peak times in seconds, ascending.  Read-only."""
        return self._events.times

    @property
    def labels(self) -> np.ndarray:
        """Beat labels parallel to :attr:`times`.

        Assigning a new array of the same length commits immediately, so the
        background classifier can publish its result with one assignment.
        """
        return self._events.labels

    @labels.setter
    def labels(self, value: np.ndarray) -> None:
        value = np.asarray(value, dtype=object)
        if value.shape[0] != self._events.times.shape[0]:
            raise ValueError(
                f"label array length {value.shape[0]} does not match "
                f"{self._events.times.shape[0]} peaks"
            )
        self._events = self._events.with_labels(value)
        self._commit()

    @property
    def ibi(self) -> np.ndarray:
        """Inter-beat intervals (last entry ``NaN``) — from :attr:`Events.ibi`."""
        return self._events.ibi

    @property
    def count(self) -> int:
        """Number of R-peaks currently held."""
        return int(self._events.times.size)

    def window_view(self, x_min: float, x_max: float) -> RTopView:
        """Return an :class:`RTopView` of peaks within ``[x_min, x_max]``."""
        times = self._events.times
        mask = (times >= x_min) & (times <= x_max)
        return RTopView(
            times=times[mask],
            labels=self._events.labels[mask],
            ibi=self._events.ibi[mask],
        )

    # ------------------------------------------------------------------
    # Navigation queries (delegated)
    # ------------------------------------------------------------------

    def next_non_normal(self, after: float) -> float | None:
        """Time of the first abnormal beat strictly after *after*, or ``None``."""
        return self._events.next_abnormal(after)

    def prev_non_normal(self, before: float) -> float | None:
        """Time of the last abnormal beat strictly before *before*, or ``None``."""
        return self._events.prev_abnormal(before)

    # ------------------------------------------------------------------
    # Structural edits — no re-classification
    # ------------------------------------------------------------------

    def move_no_classify(self, old_t: float, new_t: float) -> None:
        """Move the peak nearest *old_t* to *new_t*, keeping its label."""
        self._events = self._events.moved(old_t, new_t)
        self._commit()

    def add_no_classify(self, t: float, label: str = "N") -> None:
        """Insert a peak at time *t* with *label*."""
        self._events = self._events.added(t, label)
        self._commit()

    def delete_no_classify(self, t: float) -> None:
        """Delete the peak nearest *t*."""
        self._events = self._events.removed(t)
        self._commit()

    # ------------------------------------------------------------------
    # Structural edits — with synchronous re-classification
    # ------------------------------------------------------------------

    def move(self, old_t: float, new_t: float) -> None:
        """:meth:`move_no_classify` followed by synchronous re-classification."""
        self.move_no_classify(old_t, new_t)
        self.reclassify()

    def add(self, t: float, label: str = "N") -> None:
        """:meth:`add_no_classify` followed by synchronous re-classification."""
        self.add_no_classify(t, label)
        self.reclassify()

    def delete(self, t: float) -> None:
        """:meth:`delete_no_classify` followed by synchronous re-classification."""
        self.delete_no_classify(t)
        self.reclassify()

    def reclassify(self) -> None:
        """Recompute all beat labels via :meth:`Events.reclassified` and commit."""
        self._events = self._events.reclassified(**self._classify_params)
        self._commit()

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    def _commit(self) -> None:
        """Publish the current ``Events`` into ``session.events["hrv"]``."""
        self._session.events[self.EVENTS_KEY] = self._events
