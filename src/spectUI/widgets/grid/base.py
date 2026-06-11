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
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from spectHR.session import Session
from spectUI.common import build_epoch_grid
from spectUI.plot_worker import DockScheduler


class EpochGridView(QWidget):
    """Scrollable one-tile-per-epoch dock with background per-epoch compute."""

    #: Stable scheduler key (override per dock so generations don't collide).
    DOCK_NAME = "grid"
    #: Minimum beats in an epoch before its result is attempted.
    MIN_BEATS = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: Session | None = None
        self._config = None
        self._scheduler = DockScheduler()

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._content: QWidget | None = None
        self._status = QLabel("")
        self._status.setStyleSheet("color:#999; padding:8px;")
        self._outer.addWidget(self._status)
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
        build_epoch_grid(content, results, self._make_tile, install_save_shortcut=False)
        self._content = content
        self._outer.addWidget(content)

    def _make_tile(self, record) -> QWidget:
        label, result = record
        tile = QWidget()
        fig = Figure(figsize=(3.2, 2.4), facecolor="white")
        canvas = FigureCanvas(fig)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(0, 0, 0, 0)
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
        return tile

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

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
