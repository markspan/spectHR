# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later!
"""
:class:`PoincareWidget`, the IBI Poincaré scatter dock.

All active epochs are overlaid on one square axis (origin at 0,0), each a
colour-coded ``IBIₙ`` vs ``IBIₙ₊₁`` cloud with its SD1/SD2 ellipse and a
vertical column of per-epoch checkboxes to toggle visibility (V2's "epoch
scheduling").  The point cloud, ellipse descriptors and per-point times all
come from ``spectHR`` (:func:`poincare_points` / :func:`poincare_descriptors`);
the widget only draws and handles interaction.

Interaction
-----------
* Left-click a point → annotate it with its epoch, IBI pair and time.  The
  annotation is **draggable** and is **removed by right-clicking** it, this is
  delegated to :mod:`mplcursors` (``multiple=True``), exactly as V2 did, so the
  drag/remove behaviour is the library's, not a hand-rolled re-implementation.
* Double-click a point → :attr:`annotationActivated` carries the beat time,
  which the host uses to jump to the pre-processing dock zoomed onto that IBI.
* Toggling an epoch checkbox flips ``epoch.active`` and emits
  :attr:`epochsChanged` so the rest of the docks refresh.
"""
from __future__ import annotations

import mplcursors
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Ellipse
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spectHR.analysis.derived_series import poincare_descriptors, poincare_points
from spectHR.session import Session

# Qualitative palette cycled across epochs.
_EPOCH_COLORS = ["#2980b9", "#c0392b", "#16a085", "#8e44ad",
                 "#e67e22", "#2c3e50", "#27ae60", "#d35400"]
_PICK_PX = 12.0          # click tolerance for the double-click jump (screen px)


class PoincareWidget(QWidget):
    """Multi-epoch IBI Poincaré scatter with mplcursors annotations."""

    annotationActivated = Signal(float)   # beat time (s) of a double-clicked point
    epochsChanged = Signal()              # an epoch's active state was toggled

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: Session | None = None
        self._config = None

        self.fig = Figure(facecolor="white")
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        # Double-click → jump to prep.  Annotation add/drag/remove is owned by
        # mplcursors; this handler only carries the double-click gesture.
        self.canvas.mpl_connect("button_press_event", self._on_press)

        # Epoch checkboxes: a vertical column on the right (V2 layout), in a
        # scroll area so a recording with many epochs stays usable.
        self._cb_container = QWidget()
        self._cb_layout = QVBoxLayout(self._cb_container)
        self._cb_layout.setContentsMargins(4, 4, 4, 4)
        self._cb_layout.setSpacing(2)
        self._checkboxes: dict[str, QCheckBox] = {}

        cb_scroll = QScrollArea()
        cb_scroll.setWidgetResizable(True)
        cb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cb_scroll.setWidget(self._cb_container)
        cb_scroll.setMaximumWidth(170)

        # name -> (x_ms, y_ms, time_s, color); scatter artists per epoch.
        self._clouds: dict[str, tuple] = {}
        self._scatters: dict[str, object] = {}
        self._cursor = None     # the active mplcursors.Cursor

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas, stretch=3)
        layout.addWidget(cb_scroll, stretch=1)
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Dock contract
    # ------------------------------------------------------------------

    def set_session(self, session: Session, config=None) -> None:
        self._session = session
        self._config = config
        self._build_checkboxes()
        self.setVisible(True)
        self.refresh()

    def set_epoch(self, name: str) -> None:  # noqa: ARG002, all epochs shown at once
        """No-op: every active epoch is shown with its own checkbox."""

    def refresh(self) -> None:
        if self._session is None:
            return
        self._sync_checkboxes()
        self._draw()
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Checkboxes ("epoch scheduling")
    # ------------------------------------------------------------------

    def _build_checkboxes(self) -> None:
        while self._cb_layout.count():
            item = self._cb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()
        if self._session is None:
            return
        for i, (name, ep) in enumerate(self._session.epochs.items()):
            cb = QCheckBox(name)
            cb.setChecked(getattr(ep, "active", True))
            cb.setStyleSheet(f"color:{self._color(i)};")
            cb.stateChanged.connect(self._on_toggle)
            self._cb_layout.addWidget(cb)
            self._checkboxes[name] = cb
        self._cb_layout.addStretch()

    def _sync_checkboxes(self) -> None:
        """Update checkbox states to match ``ep.active`` without firing _on_toggle."""
        if self._session is None:
            return
        for name, cb in self._checkboxes.items():
            ep = self._session.epochs.get(name)
            if ep is not None:
                cb.blockSignals(True)
                cb.setChecked(getattr(ep, "active", True))
                cb.blockSignals(False)

    def _on_toggle(self) -> None:
        for name, cb in self._checkboxes.items():
            ep = self._session.epochs.get(name)
            if ep is not None:
                ep.active = cb.isChecked()
        self.refresh()
        self.epochsChanged.emit()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        self.ax.clear()
        self._clouds.clear()
        self._scatters.clear()

        hrv = self._session.hrv if self._session else None
        if hrv is None:
            self._teardown_cursor()
            self.ax.text(0.5, 0.5, "No R-peaks", ha="center", va="center",
                         transform=self.ax.transAxes, color="#999")
            self.ax.set_xticks([])
            self.ax.set_yticks([])
            return

        hi = 0.0
        for i, (name, ep) in enumerate(self._session.epochs.items()):
            if not getattr(ep, "active", True):
                continue
            ev = hrv.window(float(ep.start), float(ep.end))
            x, y, t = poincare_points(ev)
            if x.size < 2:
                continue
            color = self._color(i)
            scatter = self.ax.scatter(x, y, s=32, color=color, alpha=0.4,
                                      edgecolors="none", zorder=2, label=name)
            scatter.epoch = name           # looked up in the mplcursors callback
            self._clouds[name] = (x, y, t, color)
            self._scatters[name] = scatter
            hi = max(hi, float(x.max()), float(y.max()))

            desc = poincare_descriptors(ev)
            if desc is not None:
                self.ax.add_patch(Ellipse(
                    (desc.cx, desc.cy), width=2 * desc.sd2, height=2 * desc.sd1,
                    angle=45.0, facecolor="none", edgecolor=color,
                    linewidth=1.5, zorder=3,
                ))

        hi = hi * 1.05 if hi > 0 else 1.0
        self.ax.set_xlim(0.0, hi)
        self.ax.set_ylim(0.0, hi)
        self.ax.plot([0.0, hi], [0.0, hi], ":", color="#7f8c8d", linewidth=1, zorder=1)
        self.ax.set_aspect("equal", adjustable="box")
        self.ax.set_xlabel("IBIₙ (ms)")
        self.ax.set_ylabel("IBIₙ₊₁ (ms)")
        self.fig.tight_layout()

        self._setup_cursor()

    # ------------------------------------------------------------------
    # Annotations, delegated to mplcursors (draggable, right-click removes)
    # ------------------------------------------------------------------

    def _setup_cursor(self) -> None:
        """(Re)create the mplcursors cursor over the current scatter clouds.

        ``multiple=True`` lets several annotations coexist; mplcursors makes
        each one draggable and removes it on a right-click, the V2 behaviour.
        The cursor is rebuilt every redraw because ``ax.clear()`` discards the
        old scatter artists it was bound to.
        """
        self._teardown_cursor()
        artists = list(self._scatters.values())
        if not artists:
            return
        self._cursor = mplcursors.cursor(artists, hover=False, multiple=True)
        self._cursor.connect("add", self._on_cursor_add)

    def _teardown_cursor(self) -> None:
        if self._cursor is not None:
            try:
                self._cursor.remove()
            except Exception:       # pragma: no cover - already-dead artists
                pass
            self._cursor = None

    def _on_cursor_add(self, sel) -> None:
        """Fill a freshly-added mplcursors selection with the point's details."""
        name = getattr(sel.artist, "epoch", None)
        if name is None or name not in self._clouds:
            return
        idx = int(np.round(np.ravel(sel.index)[0])) if np.ndim(sel.index) else int(sel.index)
        sel.annotation.set_text(self._annotation_text(name, idx))
        bbox = sel.annotation.get_bbox_patch()
        if bbox is not None:
            bbox.set_alpha(0.8)

    def _annotation_text(self, name: str, idx: int) -> str:
        x, y, t, _color = self._clouds[name]
        idx = max(0, min(int(idx), len(t) - 1))
        return f"{name}\nIBI {x[idx]:.0f}→{y[idx]:.0f} ms\nt = {t[idx]:.1f} s"

    # ------------------------------------------------------------------
    # Double-click → jump to the pre-processing dock
    # ------------------------------------------------------------------

    def _on_press(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None:
            return
        if event.dblclick and event.button == 1:
            hit = self._nearest_point(event)
            if hit is not None:
                name, idx = hit
                _x, _y, t, _c = self._clouds[name]
                self.annotationActivated.emit(float(t[idx]))

    def _nearest_point(self, event) -> "tuple[str, int] | None":
        best: tuple[str, int] | None = None
        best_d = _PICK_PX
        for name, (x, y, _t, _c) in self._clouds.items():
            px = self.ax.transData.transform(np.column_stack([x, y]))
            d = np.hypot(px[:, 0] - event.x, px[:, 1] - event.y)
            i = int(np.argmin(d))
            if d[i] < best_d:
                best_d, best = d[i], (name, i)
        return best

    @staticmethod
    def _color(i: int) -> str:
        return _EPOCH_COLORS[i % len(_EPOCH_COLORS)]
