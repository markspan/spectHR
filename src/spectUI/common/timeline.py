# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Base timeline plot widget and shared display utilities.

``TimelinePlotWidget`` is the common base class for every docked plot that
shows physiological data over a time axis.  Subclasses override ``_refresh``
to render their specific view; the base class manages the matplotlib
figure/canvas, epoch navigation, y-zoom, and figure export.

Types exported for import by widget modules:

    TimeSeconds     NewType float alias for timestamps.
    EpochName       NewType str alias for epoch labels.
    ViewState       Current epoch + time-window state.
    AxisYState      Y-axis limits state.
    draw_interval_arrows
                    Utility: draw shaded spans for labelled intervals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from spectHR.session import Session
from spectUI.common.plot_export import PlotExportMixin
from spectUI.common.plot_zoom import YZoomMixin


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

TimeSeconds = NewType("TimeSeconds", float)
EpochName   = NewType("EpochName",   str)


# ---------------------------------------------------------------------------
# Lightweight state containers
# ---------------------------------------------------------------------------


@dataclass
class ViewState:
    """Current display state: which epoch, and the visible time window."""

    epoch_name: str   = "experiment"
    t_start:    float = 0.0
    t_end:      float = 1.0


@dataclass
class AxisYState:
    """Y-axis limits, maintained across epoch switches by YZoomMixin."""

    y_min: float = 0.0
    y_max: float = 1.0


# ---------------------------------------------------------------------------
# Shared drawing utility
# ---------------------------------------------------------------------------


def draw_interval_arrows(
    ax: Axes,
    starts: np.ndarray,
    ends:   np.ndarray,
    labels: np.ndarray | None = None,
    *,
    color:  str   = "gray",
    alpha:  float = 0.25,
) -> None:
    """Shade each ``[start, end]`` interval on *ax*.

    Parameters
    ----------
    ax
        Target matplotlib axes.
    starts, ends
        1-D arrays of interval boundaries in seconds.
    labels
        Optional per-interval label array.  When provided, alternating
        labels get a slightly higher alpha to distinguish phase pairs
        (e.g. INH / EXH).
    color, alpha
        Shading colour and base opacity.
    """
    for i, (t0, t1) in enumerate(zip(starts, ends)):
        a = alpha * 1.4 if (i % 2 == 0) else alpha
        ax.axvspan(float(t0), float(t1), color=color, alpha=a, linewidth=0)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class TimelinePlotWidget(QWidget, PlotExportMixin, YZoomMixin):
    """Base class for docked plot widgets that display data over an epoch.

    Subclass contract
    -----------------
    Override :meth:`_refresh` to render the current ``_session`` /
    ``_epoch_name`` combination.  Call ``self._canvas.draw_idle()`` at the
    end of ``_refresh`` to flush the figure.

    The base class provides:

    * A ``matplotlib`` ``Figure`` + ``FigureCanvas`` in a full-size layout.
    * :meth:`set_session` — loads a new :class:`~spectHR.session.Session`
      and triggers ``_refresh``.
    * :meth:`set_epoch` — switches the active epoch and triggers ``_refresh``.
    * :attr:`_epoch` — the active :class:`~spectHR.session.Epoch` (or ``None``).
    * :attr:`_epoch_names` — ordered list of epoch labels.
    * ``PlotExportMixin`` — Shift+Ctrl+P figure export.
    * ``YZoomMixin`` — Up/Down arrow y-axis zoom.

    Signals
    -------
    epoch_request(str)
        Emitted when the widget wants to change the globally active epoch
        (e.g. the user clicked a nav button).  MainWindow listens and calls
        ``set_epoch`` on all docks.
    """

    epoch_request = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._session:     Session | None = None
        self._config       = None           # WorkspaceView; set by set_session
        self._view         = ViewState()
        self._y_state      = AxisYState()

        self._fig    = Figure(tight_layout=True)
        self._canvas = FigureCanvas(self._fig)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)

    # ------------------------------------------------------------------
    # Public interface (called by MainWindow)
    # ------------------------------------------------------------------

    def set_session(self, session: Session, config) -> None:
        """Load *session* and switch to its first epoch, then refresh."""
        self._session = session
        self._config  = config
        if session.epochs:
            self._view.epoch_name = next(iter(session.epochs))
        self._refresh()

    def set_epoch(self, name: str) -> None:
        """Switch to epoch *name* and refresh.  No-op if name is unknown."""
        if self._session is None:
            return
        if name not in self._session.epochs:
            return
        self._view.epoch_name = name
        self._refresh()

    # ------------------------------------------------------------------
    # Subclass hook
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Redraw for the current session/epoch.  Override in subclasses."""

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def _epoch(self):
        """The active :class:`~spectHR.session.Epoch`, or ``None``."""
        if self._session is None:
            return None
        return self._session.epochs.get(self._view.epoch_name)

    @property
    def _epoch_names(self) -> list[str]:
        """Ordered list of epoch labels in the current session."""
        if self._session is None:
            return []
        return list(self._session.epochs.keys())
