# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`AnalyticView` — base for non-timeline plot docks.

A thin matplotlib host that implements the dock contract the coordinator
relies on — ``set_session(session, config)``, ``set_epoch(name)``,
``refresh()`` — and delegates the actual drawing to a single ``_draw(fig)``
hook.  Subclasses compute via ``spectHR`` and plot; they hold no analysis
logic and no per-frame state beyond the loaded session and the active epoch.
"""
from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget

from spectHR.session import Session


class AnalyticView(QWidget):
    """Figure/canvas host with the dock refresh contract."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: Session | None = None
        self._config = None
        self._epoch_name: str | None = None

        self.fig = Figure(facecolor="white")
        self.canvas = FigureCanvas(self.fig)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Dock contract
    # ------------------------------------------------------------------

    def set_session(self, session: Session, config=None) -> None:
        """Load *session* and render."""
        self._session = session
        self._config = config
        if self._epoch_name is None and session.epochs:
            self._epoch_name = next(iter(session.epochs))
        self.setVisible(True)
        self.refresh()

    def set_epoch(self, name: str) -> None:
        """Switch the active epoch and redraw (no-op if unknown)."""
        if self._session is None or name not in self._session.epochs:
            return
        self._epoch_name = name
        self.refresh()

    def refresh(self) -> None:
        """Re-draw from the current session; cheap to call on any data change."""
        if self._session is None:
            return
        self.fig.clear()
        try:
            self._draw(self.fig)
        except Exception:  # noqa: BLE001 — a compute failure must not crash the UI
            from spectHR.Tools.Logger import logger
            logger.exception("%s draw failed", type(self).__name__)
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Hook
    # ------------------------------------------------------------------

    def _draw(self, fig: Figure) -> None:
        """Plot into *fig*.  Must be overridden."""
        raise NotImplementedError
