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
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from spectHR.session import Session
from spectUI.common import (
    Y_TOP_FLOOR,
    YZoomMixin,
    build_epoch_grid,
    wire_y_zoom_shortcuts,
)
from spectUI.plot_worker import DockScheduler

#: At most this many tiles per row (the rest wrap onto new, scrolled rows).
_MAX_COLUMNS = 2
#: A tile never shrinks below this height (px) however short the dock is.
_MIN_TILE_PX = 170


class EpochGridView(YZoomMixin, QWidget):
    """Scrollable one-tile-per-epoch dock with background per-epoch compute.

    Tiles are laid out at most :data:`_MAX_COLUMNS` wide and each is sized to
    the dock's viewport aspect (height ≈ viewport_height / columns), so the
    page *grows downward* and scrolls vertically rather than cramming every
    epoch onto one screen.
    """

    #: Stable scheduler key (override per dock so generations don't collide).
    DOCK_NAME = "grid"
    #: Minimum beats in an epoch before its result is attempted.
    MIN_BEATS = 4
    #: When True, Up/Down arrows zoom a y-axis shared across all tiles.
    Y_ZOOM = False

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: Session | None = None
        self._config = None
        self._scheduler = DockScheduler()

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._content: QWidget | None = None
        self._scroll: QScrollArea | None = None
        self._columns = 1
        self._status = QLabel("")
        self._status.setStyleSheet("color:#999; padding:8px;")
        self._outer.addWidget(self._status)

        # Y-zoom state (YZoomMixin contract): a shared y-max over tiles that
        # expose ``.ax`` / ``.canvas``.
        self._subplots: list[QWidget] = []
        self._y_top: float = Y_TOP_FLOOR
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
        if self._content is not None:
            self._content.setParent(None)
            self._content.deleteLater()
            self._content = None

        if not results:
            self._status.setText("No active epochs.")
            return
        self._status.setText("")

        content = QWidget()
        self._columns = max(1, min(_MAX_COLUMNS, len(results)))
        self._subplots = build_epoch_grid(
            content, results, self._make_tile,
            columns=self._columns, install_save_shortcut=False,
        )
        self._content = content
        self._scroll = content.findChild(QScrollArea)
        self._outer.addWidget(content)
        self._relayout_tiles()
        if self.Y_ZOOM:
            self._init_y_zoom()

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
        # Expose the primary axis + canvas so YZoomMixin can drive a shared
        # y-axis across all tiles.
        tile.ax = fig.axes[0] if fig.axes else None
        tile.canvas = canvas
        return tile

    # ------------------------------------------------------------------
    # Viewport-aspect tile sizing (grow-down + vertical scroll)
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:   # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._relayout_tiles()

    def _relayout_tiles(self) -> None:
        """Size every tile to the viewport aspect: ``height ≈ vp_h / columns``.

        The 2-column grid stretches each tile to ``vp_w / columns`` wide, so a
        tile's height/width matches the viewport's; two rows then fill the
        dock and further epochs push the page down into the vertical scroll.
        """
        if not self._subplots or self._scroll is None:
            return
        h = self._scroll.viewport().height()
        if h < 50:                       # not laid out yet — use the dock height
            h = max(self.height(), 400)
        tile_h = max(_MIN_TILE_PX, (h - 6) // max(1, self._columns))
        for tile in self._subplots:
            tile.setFixedHeight(tile_h)

    # ------------------------------------------------------------------
    # Shared y-axis zoom (YZoomMixin contract)
    # ------------------------------------------------------------------

    def _init_y_zoom(self) -> None:
        """Adopt one y-max across all tiles and wire Up/Down arrow zoom."""
        tops = [t.ax.get_ylim()[1] for t in self._subplots
                if getattr(t, "ax", None) is not None]
        if tops:
            self._y_top = max(max(tops), Y_TOP_FLOOR)
            self._set_y_top(self._y_top)   # uniform y across epochs (V2)
        if not self._yzoom_wired:
            wire_y_zoom_shortcuts(self)
            self._yzoom_wired = True

    def _set_y_top(self, new_y_top: float) -> None:
        """Apply *new_y_top* to every tile that carries a y-axis."""
        new_y_top = max(float(new_y_top), Y_TOP_FLOOR)
        self._y_top = new_y_top
        for tile in self._subplots:
            ax = getattr(tile, "ax", None)
            if ax is not None:
                ax.set_ylim(bottom=0.0, top=new_y_top)
                tile.canvas.draw_idle()

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
