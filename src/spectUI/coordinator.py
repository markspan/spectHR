# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`DataCoordinator` — keeps the docks in sync with the data and each other.

One :class:`~spectHR.session.Session` is the single source of truth.  When an
editing dock changes part of it — R-peaks, blood-pressure calibration, the
epoch table — the docks that *derive* from that part must repaint.  Rather
than wire "when X changes, refresh Y" across every widget, each dock declares
*what it depends on* (a :class:`DataChange` mask) and implements ``refresh()``;
the coordinator owns the mapping.

Two responsibilities, both dependency-driven:

* **Refresh fan-out.**  :meth:`notify` walks the registered docks and refreshes
  those whose dependencies intersect the change — immediately if the dock is
  visible, lazily (on next show, via :meth:`widget_shown`) otherwise, so a
  hidden, expensive dock recomputes at most once when the user reveals it.
* **Window sync.**  Timeline docks registered with :meth:`register_timeline`
  scroll together: when one reports a new window the others follow.

The coordinator is Qt-aware (it reads ``isVisible`` and connects signals) but
holds no analysis logic — it is pure UI orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Flag, auto

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget


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
    dirty: bool = False


class DataCoordinator(QObject):
    """Dependency-aware refresh + window-sync coordinator for the docks."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[_Entry] = []
        self._timelines: list = []
        # The window all timeline docks share; the last one any dock reported.
        self._shared_window: tuple[float, float] | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, widget: QWidget, depends: DataChange) -> None:
        """Register *widget* to be refreshed when *depends* changes.

        The widget must implement ``refresh()`` and (being a ``QWidget``)
        ``isVisible()``.
        """
        self._entries.append(_Entry(widget, depends))

    def register_timeline(self, widget) -> None:
        """Register a timeline dock so its window stays in sync with siblings.

        The widget must expose ``viewChanged`` (signal), ``current_window()``
        and ``apply_window(x_min, x_max)`` — the :class:`TimelineView` contract.
        """
        self._timelines.append(widget)
        widget.viewChanged.connect(lambda w=widget: self._sync_window(w))

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

        A timeline dock adopts the shared window so the axes stay coupled even
        across a hide/show; any dock marked dirty while hidden is refreshed.
        """
        if widget in self._timelines and self._shared_window is not None:
            widget.apply_window(*self._shared_window)
        for entry in self._entries:
            if entry.widget is widget and entry.dirty:
                entry.dirty = False
                entry.widget.refresh()

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
