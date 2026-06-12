# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`EpochEditorWidget` — the epoch-table editor dock.

A Gantt-style view of the recording's epochs: one horizontal bar per epoch
on a shared time axis.  Drag a bar's left/right edge to move its start/end;
click a bar's body to toggle whether the epoch is active.  Every change
mutates ``session.epochs[...]`` in place and emits :attr:`epochsChanged`, so
the coordinator refreshes every dock that depends on the epoch table.
"""
from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from spectHR.session import Session

_C_ACTIVE = "#16a085"
_C_INACTIVE = "#bdc3c7"
_EDGE_PX = 8.0     # how near an edge counts as grabbing it (screen px)
_MIN_SPAN = 0.5    # seconds — an epoch may not be dragged narrower than this


class EpochEditorWidget(QWidget):
    """Draggable epoch bars; edits commit into the session and notify."""

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setVisible(False)

        self._rows: dict[int, str] = {}        # row index -> epoch name
        self._drag: tuple[str, str] | None = None   # (name, "start"|"end")
        self._press_name: str | None = None         # body-press candidate to toggle

    # ------------------------------------------------------------------
    # Dock contract
    # ------------------------------------------------------------------

    def set_session(self, session: Session, config=None) -> None:
        self._session = session
        self._config = config
        self.setVisible(True)
        self.refresh()

    def set_epoch(self, name: str) -> None:  # noqa: ARG002 — shows all epochs
        """No-op: the editor always shows the whole epoch table."""

    def refresh(self) -> None:
        if self._session is None:
            return
        self._draw()
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        ax = self.ax
        ax.clear()
        self._rows.clear()
        s = self._session
        assert s is not None

        epochs = sorted(s.epochs.items(), key=lambda kv: float(kv[1].start))
        if not epochs:
            ax.text(0.5, 0.5, "No epochs", ha="center", va="center",
                    transform=ax.transAxes, color="#999")
            ax.set_xticks([]); ax.set_yticks([])
            return

        for i, (name, ep) in enumerate(epochs):
            active = getattr(ep, "active", True)
            ax.add_patch(Rectangle(
                (float(ep.start), i - 0.4), float(ep.end) - float(ep.start), 0.8,
                facecolor=_C_ACTIVE if active else _C_INACTIVE,
                edgecolor="#34495e", alpha=0.85 if active else 0.4, zorder=2,
            ))
            ax.text(
                float(ep.start), i,
                f" {name}  [{float(ep.start):.0f}–{float(ep.end):.0f} s]",
                va="center", ha="left", fontsize=8, zorder=3,
            )
            self._rows[i] = name

        ax.set_ylim(len(epochs) - 0.5, -0.5)   # first epoch on top
        ax.set_yticks([])
        ax.set_xlabel("Time (s)")
        lo, hi = self._extent()
        ax.set_xlim(lo, hi)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        self.fig.tight_layout()

    def _extent(self) -> tuple[float, float]:
        s = self._session
        starts = [float(ep.start) for ep in s.epochs.values()]
        ends = [float(ep.end) for ep in s.epochs.values()]
        ecg = s.ecg
        lo = min(starts + ([float(ecg.times[0])] if ecg is not None and ecg.times.size else []))
        hi = max(ends + ([float(ecg.times[-1])] if ecg is not None and ecg.times.size else []))
        if hi <= lo:
            hi = lo + 1.0
        pad = 0.02 * (hi - lo)
        return lo - pad, hi + pad

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_press(self, event) -> None:
        self._drag = None
        self._press_name = None
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        row = round(event.ydata)
        name = self._rows.get(row)
        if name is None:
            return
        ep = self._session.epochs[name]
        # Pixel distance from the cursor to each edge.
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
            self._drag = None
            self.epochsChanged.emit()
            return
        # A click on a bar body (no drag) toggles the epoch's active state.
        if self._press_name is not None and self._session is not None:
            ep = self._session.epochs[self._press_name]
            ep.active = not getattr(ep, "active", True)
            self._press_name = None
            self.refresh()
            self.epochsChanged.emit()
