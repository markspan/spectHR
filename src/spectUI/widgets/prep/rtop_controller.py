# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Mutable R-peak editing on top of an immutable :class:`Events` channel.

V2 edited R-peaks by mutating a ``CardioSeries`` in place; every widget
held the same object, so an edit was instantly visible everywhere.  The
development branch's :class:`~spectHR.session.Events` is a *frozen*
dataclass (its read-only arrays are what make ``Events.ibi`` safely
cacheable), so in-place mutation is no longer possible.

:class:`RTopController` reconciles the two worlds.  It keeps private,
writable copies of the peak times and beat labels, and after every
structural edit it builds a fresh immutable :class:`Events` and assigns it
back into ``session.events["hrv"]``.  Because :class:`~spectHR.session.Session`
itself is an ordinary (non-frozen) dataclass, that assignment is seen
immediately by every other holder of the same session — the same
call-by-reference convenience V2 had, without giving up array immutability
in the analysis layer.

Two tiers of edit are offered:

``*_no_classify``
    Apply the structural change and commit, leaving labels untouched.
    The widget uses these for instant feedback during a drag and schedules
    re-classification on a background thread.
``add`` / ``move`` / ``delete``
    Apply the change *and* re-classify synchronously before returning —
    convenient for scripted or test edits where labels must be correct on
    the next read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from spectHR.session import Events, Session
from spectHR.Tools.IbiClassification import classify_ibi


@dataclass(frozen=True)
class RTopView:
    """An immutable slice of R-peaks for one time window.

    Returned by :meth:`RTopController.window_view` for rendering.  Holds
    numpy *views* of the controller's arrays (no copy), so it is cheap to
    build on every redraw.

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
        Keyword args forwarded to
        :func:`~spectHR.Tools.IbiClassification.classify_ibi` by
        :meth:`reclassify` (``window_length`` / ``n_std`` / ``max_ibi_sec``).
        Defaults to the classifier's own defaults; the widget passes the
        workspace ``CardioParameters`` so a post-edit re-classification uses
        exactly the thresholds the initial detection used.

    Notes
    -----
    The constructor copies the times and labels out of the frozen
    ``Events`` so the working arrays are writable; the original frozen
    object is never mutated.
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
        self._times: np.ndarray = np.array(hrv.times, dtype=float)
        self._labels: np.ndarray = np.array(hrv.labels, dtype=object)
        self._classify_params: dict[str, Any] = dict(classify_params or {})

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    @property
    def times(self) -> np.ndarray:
        """Peak times in seconds, ascending.  Treat as read-only."""
        return self._times

    @property
    def labels(self) -> np.ndarray:
        """Beat labels parallel to :attr:`times`.

        Assigning a new array of the same length commits immediately, so
        the background classifier can publish its result with a single
        ``ctrl.labels = new_labels``.
        """
        return self._labels

    @labels.setter
    def labels(self, value: np.ndarray) -> None:
        value = np.asarray(value, dtype=object)
        if value.shape[0] != self._times.shape[0]:
            raise ValueError(
                f"label array length {value.shape[0]} does not match "
                f"{self._times.shape[0]} peaks"
            )
        self._labels = value
        self._commit()

    @property
    def ibi(self) -> np.ndarray:
        """Freshly computed inter-beat intervals, last entry ``NaN``.

        Allocated on each access (it mirrors :attr:`Events.ibi` but the
        controller's times change between reads) so callers may mutate the
        returned array freely.
        """
        t = self._times
        if t.size < 2:
            return np.array([np.nan])
        out = np.empty(t.size)
        out[:-1] = np.diff(t)
        out[-1] = np.nan
        return out

    @property
    def count(self) -> int:
        """Number of R-peaks currently held."""
        return int(self._times.size)

    def window_view(self, x_min: float, x_max: float) -> RTopView:
        """Return an :class:`RTopView` of peaks within ``[x_min, x_max]``."""
        mask = (self._times >= x_min) & (self._times <= x_max)
        return RTopView(
            times=self._times[mask],
            labels=self._labels[mask],
            ibi=self.ibi[mask],
        )

    # ------------------------------------------------------------------
    # Navigation queries
    # ------------------------------------------------------------------

    def _abnormal_mask(self) -> np.ndarray:
        """Boolean mask of beats worth navigating to (non-``"N"``).

        Excludes the final beat: its IBI is the trailing ``NaN`` sentinel, so
        :func:`classify_ibi` always labels it ``"T"`` (degenerate) even though
        it is not a real artefact.  Without this it would be a phantom
        "abnormal" target at the very end of every recording.
        """
        mask = self._labels != "N"
        if mask.size:
            mask[-1] = False
        return mask

    def next_non_normal(self, after: float) -> float | None:
        """Time of the first abnormal beat strictly after *after*, or ``None``."""
        mask = self._abnormal_mask() & (self._times > after)
        return float(self._times[mask][0]) if mask.any() else None

    def prev_non_normal(self, before: float) -> float | None:
        """Time of the last abnormal beat strictly before *before*, or ``None``."""
        mask = self._abnormal_mask() & (self._times < before)
        return float(self._times[mask][-1]) if mask.any() else None

    # ------------------------------------------------------------------
    # Structural edits — no re-classification
    # ------------------------------------------------------------------

    def move_no_classify(self, old_t: float, new_t: float) -> None:
        """Move the peak nearest *old_t* to *new_t*, keeping its label.

        Re-sorts so :attr:`times` stays ascending, then commits.  Labels
        are left as-is; the caller is expected to re-classify if needed.
        """
        if self._times.size == 0:
            return
        idx = int(np.argmin(np.abs(self._times - old_t)))
        self._times[idx] = float(new_t)
        order = np.argsort(self._times, kind="stable")
        self._times = self._times[order]
        self._labels = self._labels[order]
        self._commit()

    def add_no_classify(self, t: float, label: str = "N") -> None:
        """Insert a peak at time *t* with *label*, keeping the array sorted."""
        idx = int(np.searchsorted(self._times, t))
        self._times = np.insert(self._times, idx, float(t))
        self._labels = np.insert(self._labels, idx, label)
        self._commit()

    def delete_no_classify(self, t: float) -> None:
        """Delete the peak nearest *t*."""
        if self._times.size == 0:
            return
        idx = int(np.argmin(np.abs(self._times - t)))
        self._times = np.delete(self._times, idx)
        self._labels = np.delete(self._labels, idx)
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

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def reclassify(self) -> None:
        """Re-run :func:`classify_ibi` over all beats and commit the labels.

        The background path in the widget snapshots the arrays and calls
        :func:`classify_ibi` off-thread instead; this synchronous variant
        exists for scripted edits and tests.
        """
        labels = self._labels.copy()
        classify_ibi(self.ibi, labels, **self._classify_params)
        self._labels = labels
        self._commit()

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    def _commit(self) -> None:
        """Publish the working arrays as a fresh ``Events`` on the session."""
        self._session.events[self.EVENTS_KEY] = Events(
            times=self._times.copy(),
            labels=self._labels.copy(),
        )
