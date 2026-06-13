# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`EpochGridView` — base for per-epoch computed-figure docks.

The shape shared by the PSD / profile / transfer / spectrogram docks: a
scrollable grid with one tile per active epoch, each tile a small figure of
an analysis result.  The per-epoch computation is potentially expensive, so
it runs on a background pool thread via
:class:`~spectUI.plot_worker.DockScheduler` (which discards a stale result
when a newer edit supersedes it); only the cheap tile rendering happens on
the UI thread.

Tiles are laid out at most :attr:`EpochGridView.MAX_COLUMNS` wide and sized to
the dock's viewport aspect, so the page grows downward and scrolls vertically.
A thin toolbar carries an *Equal y-axis* checkbox (when the dock has a single
magnitude y-axis and more than one epoch) that links every tile's y-axis to
the largest; Up / Down arrows then zoom that axis.  Subclasses can add their
own controls to the toolbar (e.g. the profile dock's band checkboxes).

Subclasses implement three hooks:

``_resolve(config)``         (main thread) cache any settings the compute
                             needs, so the worker never touches Qt state.
``_compute_epoch(events)``   (worker thread) compute one epoch's result from
                             its epoch-scoped ``"hrv"`` Events; pure / headless.
``_render_tile(fig, label, result)``  (main thread) draw one tile.
"""
from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from spectHR.session import Session
from spectUI.common import (
    Y_TOP_FLOOR,
    Y_ZOOM_STEP_DOWN,
    Y_ZOOM_STEP_UP,
    build_epoch_grid,
    wire_y_zoom_shortcuts,
)
from spectUI.plot_worker import DockScheduler

#: A tile never shrinks below this height (px) however short the dock is.
_MIN_TILE_PX = 170


class EpochGridView(QWidget):
    """Scrollable one-tile-per-epoch dock with background per-epoch compute."""

    #: Stable scheduler key (override per dock so generations don't collide).
    DOCK_NAME = "grid"
    #: Minimum beats in an epoch before its result is attempted.
    MIN_BEATS = 4
    #: At most this many tiles per row (the rest wrap onto scrolled rows).
    MAX_COLUMNS = 2
    #: Multiplier on the per-tile height (1.0 = viewport aspect).  >1 makes a
    #: taller tile — e.g. the 3-D spectrogram, whose surface needs height but
    #: leaves whitespace at the sides, so two still sit comfortably side by side.
    TILE_HEIGHT_FACTOR = 1.0
    #: True when each tile has one magnitude y-axis that can be linked/zoomed
    #: (PSD / profile / transfer-modulus).  False for the frequency-axis docks
    #: (spectrogram 2-D / 3-D).
    Y_ZOOM = False

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: Session | None = None
        self._config = None
        self._scheduler = DockScheduler()

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # Toolbar row (hidden until it carries a visible control).
        self._toolbar_row = QWidget()
        self._toolbar = QHBoxLayout(self._toolbar_row)
        self._toolbar.setContentsMargins(6, 2, 6, 2)
        self._equal_y_cb = QCheckBox("Equal y-axis")
        self._equal_y_cb.setChecked(True)        # linked by default (as before)
        self._equal_y_cb.setToolTip("Link every plot's y-axis to the largest")
        self._equal_y_cb.toggled.connect(self._on_equal_y_toggled)
        self._toolbar.addWidget(self._equal_y_cb)
        self._toolbar.addStretch()
        self._toolbar_row.setVisible(False)
        self._outer.addWidget(self._toolbar_row)
        self._build_toolbar()                    # subclass extras

        self._content: QWidget | None = None
        self._scroll: QScrollArea | None = None
        self._columns = 1
        self._status = QLabel("")
        self._status.setStyleSheet("color:#999; padding:8px;")
        self._outer.addWidget(self._status)

        self._subplots: list[QWidget] = []
        self._last_results: list | None = None   # cached for cheap re-render
        # Y-axis control state (persists across refreshes).
        self._equal_y = True
        self._y_zoom_factor = 1.0
        self._yzoom_wired = False
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Dock contract
    # ------------------------------------------------------------------

    def set_session(self, session: Session, config=None) -> None:
        self._session = session
        self._config = config
        self.setVisible(True)
        self.refresh()

    def set_epoch(self, name: str) -> None:  # noqa: ARG002 — grid shows all epochs
        """No-op: the grid always shows every active epoch."""

    def refresh(self) -> None:
        """Recompute every active epoch's result on a pool thread, then re-grid."""
        session = self._session
        if session is None:
            return
        self._resolve(self._config)
        self._status.setText("Computing…")

        active = [(name, ep) for name, ep in session.epochs.items()
                  if getattr(ep, "active", True)]

        def compute():
            results = []
            for name, _ep in active:
                try:
                    scoped = session.scoped_to(name)
                    hrv = scoped.events.get("hrv")
                    if hrv is None or hrv.times.size < self.MIN_BEATS:
                        results.append((name, None))
                    else:
                        results.append((name, self._compute_epoch(hrv, scoped)))
                except Exception as exc:  # noqa: BLE001 — surface per-tile, never crash
                    results.append((name, _ComputeError(str(exc))))
            return results

        self._scheduler.submit(self.DOCK_NAME, compute, self._build_grid)

    # ------------------------------------------------------------------
    # Grid construction (main thread)
    # ------------------------------------------------------------------

    def _build_grid(self, results: list) -> None:
        self._last_results = results
        self._rebuild()

    def _rebuild(self) -> None:
        """(Re)build the tile grid from the cached results (no recompute)."""
        results = self._last_results
        if self._content is not None:
            self._content.setParent(None)
            self._content.deleteLater()
            self._content = None

        if not results:
            self._status.setText("No active epochs.")
            self._toolbar_row.setVisible(self._toolbar_has_extras())
            return
        self._status.setText("")

        content = QWidget()
        self._columns = max(1, min(self.MAX_COLUMNS, len(results)))
        self._subplots = build_epoch_grid(
            content, results, self._make_tile, columns=self._columns,
        )
        self._content = content
        self._scroll = content.findChild(QScrollArea)
        self._outer.addWidget(content)
        self._relayout_tiles()

        # Y-axis controls: only for magnitude-axis docks, only when several
        # epochs make linking meaningful.
        show_equal_y = self.Y_ZOOM and len(self._subplots) > 1
        self._equal_y_cb.setVisible(show_equal_y)
        self._toolbar_row.setVisible(show_equal_y or self._toolbar_has_extras())
        if self.Y_ZOOM:
            if not self._yzoom_wired:
                wire_y_zoom_shortcuts(self)      # Up / Down arrow y-zoom
                self._yzoom_wired = True
            self._apply_y()

    def _make_tile(self, record) -> QWidget:
        label, result = record
        tile = QWidget()
        tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(0, 0, 0, 0)
        fig = Figure(figsize=(3.2, 2.4), facecolor="white")
        canvas = FigureCanvas(fig)
        layout.addWidget(canvas)
        if isinstance(result, _ComputeError):
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, f"{label}\n{result.message}", ha="center",
                    va="center", transform=ax.transAxes, fontsize=8, color="#c0392b")
            ax.set_xticks([]); ax.set_yticks([])
        elif result is None:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, f"{label}\n(insufficient data)", ha="center",
                    va="center", transform=ax.transAxes, fontsize=8, color="#999")
            ax.set_xticks([]); ax.set_yticks([])
        else:
            self._render_tile(fig, label, result)
        canvas.draw_idle()
        # Expose the primary axis + canvas and remember the data-driven y-top so
        # the equal-y link / arrow zoom can rescale without re-rendering.
        tile.ax = fig.axes[0] if fig.axes else None
        tile.canvas = canvas
        tile._natural_top = (
            float(tile.ax.get_ylim()[1]) if tile.ax is not None else None
        )
        return tile

    # ------------------------------------------------------------------
    # Viewport-aspect tile sizing (grow-down + vertical scroll)
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:   # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._relayout_tiles()

    def _relayout_tiles(self) -> None:
        """Size every tile to the viewport aspect: ``height ≈ vp_h / columns``."""
        if not self._subplots or self._scroll is None:
            return
        h = self._scroll.viewport().height()
        if h < 50:                       # not laid out yet — use the dock height
            h = max(self.height(), 400)
        base_h = (h - 6) / max(1, self._columns)
        tile_h = max(_MIN_TILE_PX, int(base_h * self.TILE_HEIGHT_FACTOR))
        for tile in self._subplots:
            tile.setFixedHeight(tile_h)

    # ------------------------------------------------------------------
    # Y-axis link + zoom (only when Y_ZOOM)
    # ------------------------------------------------------------------

    def _on_equal_y_toggled(self, checked: bool) -> None:
        self._equal_y = bool(checked)
        self._apply_y()

    def _zoom_in(self) -> None:
        """Up arrow: shrink the y-max (zoom in)."""
        self._y_zoom_factor *= Y_ZOOM_STEP_UP
        self._apply_y()

    def _zoom_out(self) -> None:
        """Down arrow: grow the y-max (zoom out)."""
        self._y_zoom_factor *= Y_ZOOM_STEP_DOWN
        self._apply_y()

    def _apply_y(self) -> None:
        """Rescale tile y-axes per the equal-y link and the zoom factor."""
        tiles = [t for t in self._subplots
                 if getattr(t, "ax", None) is not None
                 and getattr(t, "_natural_top", None)]
        if not tiles:
            return
        shared = max(t._natural_top for t in tiles)
        for t in tiles:
            base = shared if self._equal_y else t._natural_top
            top = max(base * self._y_zoom_factor, Y_TOP_FLOOR)
            t.ax.set_ylim(bottom=0.0, top=top)
            t.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    @staticmethod
    def _view(config):
        """Return a :class:`WorkspaceView` from a Parameters / dict / None."""
        from spectHR.config import WorkspaceView
        if isinstance(config, WorkspaceView):
            return config
        return WorkspaceView(config if isinstance(config, dict) else None)

    def _build_toolbar(self) -> None:
        """Add dock-specific toolbar controls (left of the stretch).  Default: none."""

    def _toolbar_has_extras(self) -> bool:
        """True when the dock added its own always-on toolbar controls."""
        return False

    def _resolve(self, config) -> None:
        """Cache settings the worker needs (main thread).  Default: nothing."""

    def _compute_epoch(self, events, scoped: Session):
        """Compute one epoch's result from its scoped Events.  Override."""
        raise NotImplementedError

    def _render_tile(self, fig: Figure, label: str, result) -> None:
        """Draw one tile from a successful result.  Override."""
        raise NotImplementedError


class _ComputeError:
    """Marker carrying a per-epoch compute failure message to the tile."""

    __slots__ = ("message",)

    def __init__(self, message: str) -> None:
        self.message = message
