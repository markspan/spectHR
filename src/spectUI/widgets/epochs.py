# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`EpochEditorWidget`, the epoch-table editor dock.

A Gantt-style view of the recording's epochs (V2 ``epochPlotWidget``,
re-implemented on the immutable Session): one coloured bar per epoch on a
shared time axis, the epoch names down the y-axis.

Interaction
-----------
* Drag a bar's left/right edge to move its start/end.
* Click a bar's body to toggle whether the epoch is active (inactive epochs
  are dimmed rather than hidden).
* Click an epoch's y-axis label to rename it, or clear the name to delete it.

Every change mutates ``session.epochs`` in place and emits
:attr:`epochsChanged`, so the coordinator refreshes every dependent dock.
"""
from __future__ import annotations

import matplotlib.cm as cm
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from PySide6.QtCore import Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QInputDialog, QMenu, QVBoxLayout, QWidget

from spectHR.session import Epoch, Session

_EDGE_PX = 8.0     # how near an edge counts as grabbing it (screen px)
_MIN_SPAN = 0.5    # seconds, an epoch may not be dragged narrower than this


class EpochEditorWidget(QWidget):
    """Draggable, renamable epoch bars; edits commit into the session."""

    epochsChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: Session | None = None
        self._config = None

        self.fig = Figure(facecolor="white")
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("pick_event", self._on_label_pick)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setVisible(False)

        self._rows: list[str] = []                  # row index -> epoch name
        self._drag: tuple[str, str] | None = None    # (name, "start"|"end")
        self._press_name: str | None = None          # body-press candidate to toggle
        # Row order frozen during a drag so a bar does not jump rows (and
        # colours) when its start crosses another epoch's start.
        self._row_order: list[str] | None = None

    # ------------------------------------------------------------------
    # Dock contract
    # ------------------------------------------------------------------

    def set_session(self, session: Session, config=None) -> None:
        # Re-sort by start only for a freshly loaded recording (a new epochs
        # dict); a re-broadcast of the same session keeps the edited order.
        if self._session is None or session.epochs is not self._session.epochs:
            self._row_order = None
        self._session = session
        self._config = config
        self.setVisible(True)
        self.refresh()

    def set_epoch(self, name: str) -> None:  # noqa: ARG002, shows all epochs
        """No-op: the editor always shows the whole epoch table."""

    def refresh(self) -> None:
        if self._session is None:
            return
        self._draw()
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _ordered_epochs(self) -> list[tuple[str, object]]:
        """Epoch ``(name, epoch)`` pairs in display-row order.

        Sorted by start **once**, when a recording is first shown; thereafter
        the order is held fixed so editing an epoch (dragging its start past a
        neighbour, renaming it) never reshuffles the rows.  Newly added epochs
        append at the bottom; removed ones drop out.
        """
        items = dict(self._session.epochs)
        if self._row_order is None:
            self._row_order = sorted(items, key=lambda n: float(items[n].start))
        order = [n for n in self._row_order if n in items]
        order += [n for n in items if n not in order]   # new epochs at the end
        self._row_order = order
        return [(n, items[n]) for n in order]

    def _draw(self) -> None:
        ax = self.ax
        ax.clear()
        s = self._session
        assert s is not None

        epochs = self._ordered_epochs()
        self._rows = [name for name, _ in epochs]
        if not epochs:
            ax.text(0.5, 0.5, "No epochs", ha="center", va="center",
                    transform=ax.transAxes, color="#999")
            ax.set_xticks([])
            ax.set_yticks([])
            return

        colors = cm.tab20(np.linspace(0, 1, len(epochs)))
        for i, (name, ep) in enumerate(epochs):
            active = getattr(ep, "active", True)
            ax.add_patch(Rectangle(
                (float(ep.start), i - 0.4), float(ep.end) - float(ep.start), 0.8,
                facecolor=colors[i], edgecolor="black",
                alpha=0.6 if active else 0.18, zorder=2,
            ))
            ax.text(float(ep.start), i, f" {float(ep.start):.0f}", va="center",
                    ha="left", fontsize=7, rotation="vertical", zorder=3)
            ax.text(float(ep.end), i, f"{float(ep.end):.0f} ", va="center",
                    ha="right", fontsize=7, rotation="vertical", zorder=3)

        ax.set_yticks(range(len(epochs)))
        ax.set_yticklabels(self._rows)
        for lbl in ax.get_yticklabels():
            lbl.set_picker(True)        # clickable → rename / delete
        ax.set_ylim(len(epochs) - 0.5, -0.5)   # first epoch on top
        ax.set_xlabel("Time (s)")
        ax.set_xlim(*self._extent())
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        self.fig.tight_layout()

    def _extent(self) -> tuple[float, float]:
        s = self._session
        starts = [float(ep.start) for ep in s.epochs.values()]
        ends = [float(ep.end) for ep in s.epochs.values()]
        ecg = s.ecg
        if ecg is not None and ecg.times.size:
            starts.append(float(ecg.times[0]))
            ends.append(float(ecg.times[-1]))
        lo, hi = min(starts), max(ends)
        if hi <= lo:
            hi = lo + 1.0
        pad = 0.02 * (hi - lo)
        return lo - pad, hi + pad

    def _full_span(self) -> tuple[float, float]:
        """The recording's time span (unpadded) for a new full-sized epoch."""
        s = self._session
        ch = s.ecg or s.resp or s.bp
        if ch is not None and ch.times.size:
            return float(ch.times[0]), float(ch.times[-1])
        hrv = s.hrv
        if hrv is not None and hrv.times.size:
            return float(hrv.times[0]), float(hrv.times[-1])
        if s.epochs:
            return (min(float(e.start) for e in s.epochs.values()),
                    max(float(e.end) for e in s.epochs.values()))
        return 0.0, 1.0

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self) -> None:
        if self._session is None:
            return
        menu = QMenu(self)
        add_act        = menu.addAction("Add epoch")
        menu.addSeparator()
        select_all_act   = menu.addAction("Select all")
        deselect_all_act = menu.addAction("Deselect all")
        chosen = menu.exec(QCursor.pos())
        if chosen is add_act:
            self._add_full_epoch()
        elif chosen is select_all_act:
            self._set_all_active(True)
        elif chosen is deselect_all_act:
            self._set_all_active(False)

    def _set_all_active(self, state: bool) -> None:
        if self._session is None:
            return
        for ep in self._session.epochs.values():
            ep.active = state
        self.refresh()
        self.epochsChanged.emit()

    def _add_full_epoch(self) -> None:
        """Ask for a name, then add a new epoch spanning the whole recording."""
        name, ok = QInputDialog.getText(self, "Add epoch", "Epoch name:")
        if ok:
            self.add_epoch(name.strip())

    def add_epoch(self, name: str) -> None:
        """Add a full-recording-span epoch named *name* (blank/duplicate → no-op)."""
        if self._session is None or not name or name in self._session.epochs:
            return
        lo, hi = self._full_span()
        self._session.epochs[name] = Epoch(name, lo, hi, True)
        self.refresh()
        self.epochsChanged.emit()

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_press(self, event) -> None:
        self._drag = None
        self._press_name = None
        if event.button == 3:                 # right-click → context menu
            self._show_context_menu()
            return
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        row = round(event.ydata)
        if not (0 <= row < len(self._rows)):
            return
        name = self._rows[row]
        ep = self._session.epochs[name]
        sx = self.ax.transData.transform((float(ep.start), 0))[0]
        ex = self.ax.transData.transform((float(ep.end), 0))[0]
        if abs(event.x - sx) <= _EDGE_PX:
            self._drag = (name, "start")
        elif abs(event.x - ex) <= _EDGE_PX:
            self._drag = (name, "end")
        else:
            self._press_name = name

    def _on_motion(self, event) -> None:
        if self._drag is None or event.xdata is None or self._session is None:
            return
        name, edge = self._drag
        ep = self._session.epochs[name]
        if edge == "start":
            ep.start = min(float(event.xdata), float(ep.end) - _MIN_SPAN)
        else:
            ep.end = max(float(event.xdata), float(ep.start) + _MIN_SPAN)
        self.refresh()

    def _on_release(self, event) -> None:
        if self._drag is not None:
            self._drag = None             # order stays as-is, no re-sort
            self.epochsChanged.emit()
            return
        if self._press_name is not None and self._session is not None:
            ep = self._session.epochs[self._press_name]
            ep.active = not getattr(ep, "active", True)
            self._press_name = None
            self.refresh()
            self.epochsChanged.emit()

    def _on_label_pick(self, event) -> None:
        """Click an epoch's y-axis label to rename it (blank name deletes it)."""
        lbl = event.artist
        if self._session is None or lbl not in self.ax.get_yticklabels():
            return
        old = lbl.get_text()
        if old not in self._session.epochs:
            return
        new, ok = QInputDialog.getText(
            self, "Rename epoch", "New name (blank to delete):", text=old
        )
        if not ok:
            return
        new = new.strip()
        if new == "":
            self._session.epochs.pop(old, None)
            self._reorder_after_rename(old, None)
        elif new != old and new not in self._session.epochs:
            self._session.epochs[new] = self._session.epochs.pop(old)
            self._reorder_after_rename(old, new)
        else:
            return
        self.refresh()
        self.epochsChanged.emit()

    def _reorder_after_rename(self, old: str, new: str | None) -> None:
        """Keep a renamed epoch in its row (or drop it when deleted)."""
        if self._row_order is None or old not in self._row_order:
            return
        idx = self._row_order.index(old)
        if new is None:
            self._row_order.pop(idx)
        else:
            self._row_order[idx] = new
