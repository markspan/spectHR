# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`DataCoordinator`, keeps the docks in sync with the data and each other.

One :class:`~spectHR.session.Session` is the single source of truth.  When an
editing dock changes part of it, R-peaks, blood-pressure calibration, the
epoch table, the docks that *derive* from that part must repaint.  Rather
than wire "when X changes, refresh Y" across every widget, each dock declares
*what it depends on* (a :class:`DataChange` mask) and implements ``refresh()``;
the coordinator owns the mapping.

Three responsibilities, all dependency-driven:

* **Session broadcast.**  :meth:`set_session` hands the loaded/edited session to
  every registered dock, but only computes it for the **visible** ones; a
  hidden dock keeps the session pending and applies it the first time it is
  shown (:meth:`widget_shown`).  So opening only the pre-processing dock and
  leaving the PSD / profile / transfer docks closed skips their computation
  entirely until you actually open them.
* **Refresh fan-out.**  :meth:`notify` walks the registered docks and refreshes
  those whose dependencies intersect the change, immediately if the dock is
  visible, lazily (on next show, via :meth:`widget_shown`) otherwise, so a
  hidden, expensive dock recomputes at most once when the user reveals it.
* **Window sync.**  Timeline docks registered with :meth:`register_timeline`
  scroll together: when one reports a new window the others follow.

The coordinator is Qt-aware (it reads ``isVisible`` and connects signals) but
holds no analysis logic, it is pure UI orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Flag, auto

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from spectUI.dock_protocol import DataDock, TimelineDock


class DataChange(Flag):
    """What part of the session changed (a dock declares which it depends on)."""

    NONE = 0
    HRV = auto()       # R-peaks / IBI (events["hrv"])
    BP = auto()        # blood-pressure channel / calibration
    RESP = auto()      # respiration source
    EPOCHS = auto()    # epoch table (added / moved / activated)
    PARAMS = auto()    # analysis parameters (bands, PSD method, …)
    ALL = HRV | BP | RESP | EPOCHS | PARAMS


@dataclass
class _Entry:
    widget: QWidget
    depends: DataChange
    dirty: bool = False          # a dependency changed while hidden → refresh on show
    needs_session: bool = False  # a new session arrived while hidden → set_session on show


class DataCoordinator(QObject):
    """Dependency-aware refresh + window-sync coordinator for the docks."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[_Entry] = []
        self._timelines: list = []
        # The window all timeline docks share; the last one any dock reported.
        self._shared_window: tuple[float, float] | None = None
        # The current session / config, so a dock revealed later can be brought
        # up to date without the host re-broadcasting.
        self._session = None
        self._config = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, widget: DataDock, depends: DataChange) -> None:
        """Register *widget* to be refreshed when *depends* changes.

        The widget must satisfy the :class:`~spectUI.dock_protocol.DataDock`
        contract (``set_session`` / ``apply_config`` / ``refresh`` /
        ``isVisible``).  A dock missing any of those fails here, at
        registration, rather than silently doing nothing at runtime.
        """
        if not isinstance(widget, DataDock):
            raise TypeError(
                f"{type(widget).__name__} does not satisfy the DataDock contract "
                "(needs set_session, apply_config, refresh, isVisible)."
            )
        self._entries.append(_Entry(widget, depends))

    def register_timeline(self, widget: TimelineDock) -> None:
        """Register a timeline dock so its window stays in sync with siblings.

        The widget must satisfy :class:`~spectUI.dock_protocol.TimelineDock`
        (``viewChanged`` signal, ``current_window()`` and ``apply_window``).
        """
        self._timelines.append(widget)
        widget.viewChanged.connect(lambda w=widget: self._sync_window(w))

    # ------------------------------------------------------------------
    # Session broadcast
    # ------------------------------------------------------------------

    def set_session(self, session, config) -> None:
        """Hand *session* / *config* to the docks, computing only visible ones.

        Visible docks get ``set_session`` now (and compute); hidden docks keep it
        pending and apply it the first time they are shown, so closed plot docks
        never compute until opened.
        """
        self._session = session
        self._config = config
        for entry in self._entries:
            if entry.widget.isVisible():
                entry.needs_session = False
                entry.dirty = False
                entry.widget.set_session(session, config)
            else:
                entry.needs_session = True

    def set_config(self, config) -> None:
        """Update the current *config* so a later-shown dock uses fresh params.

        Used when only the analysis parameters change (no new session): visible
        docks are refreshed via :meth:`notify`, and a dock revealed afterwards
        applies the pending session with these parameters.
        """
        self._config = config

    # ------------------------------------------------------------------
    # Refresh fan-out
    # ------------------------------------------------------------------

    def notify(self, change: DataChange, *, source: QWidget | None = None) -> None:
        """Refresh docks depending on *change*; *source* is skipped.

        Visible dependants refresh now; hidden ones are marked dirty and
        refreshed the next time they are shown (:meth:`widget_shown`).
        """
        for entry in self._entries:
            if entry.widget is source or not (entry.depends & change):
                continue
            if entry.widget.isVisible():
                entry.dirty = False
                entry.widget.refresh()
            else:
                entry.dirty = True

    def widget_shown(self, widget: QWidget) -> None:
        """Bring a just-shown *widget* up to date.

        A dock that has a session pending (it was hidden when the session
        arrived) receives it now and computes for the first time; otherwise a
        dock marked dirty by a dependency change while hidden is refreshed.  A
        timeline dock then adopts the shared window so the axes stay coupled
        across a hide/show.
        """
        for entry in self._entries:
            if entry.widget is not widget:
                continue
            if entry.needs_session and self._session is not None:
                entry.needs_session = False
                entry.dirty = False
                entry.widget.set_session(self._session, self._config)
            elif entry.dirty:
                entry.dirty = False
                entry.widget.refresh()
            break
        if widget in self._timelines and self._shared_window is not None:
            widget.apply_window(*self._shared_window)

    # ------------------------------------------------------------------
    # Window sync
    # ------------------------------------------------------------------

    def _sync_window(self, source) -> None:
        """Record *source*'s window as shared and apply it to visible siblings.

        Hidden siblings adopt it later in :meth:`widget_shown`, so the overview
        selection couples the x-axis of *every* timeline dock, not just the
        currently visible ones.
        """
        window = source.current_window()
        if window is None:
            return
        self._shared_window = window
        for widget in self._timelines:
            if widget is not source and widget.isVisible():
                widget.apply_window(*window)
