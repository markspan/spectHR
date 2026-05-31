# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
uitools.py, shared GUI helpers used by the plot widgets.

Exports
-------
* :func:`show_export_summary`  , uniform post-export message box.
* :class:`OverviewWindow`      , draggable rectangle on an overview axis.
* :func:`make_nav_button`      , icon button factory used by both
  ``PrepPlotWidget`` and ``HRPlotWidget`` navigation bars.
* :func:`style_axis_clean`     , hide y-axis and non-bottom spines.
* :func:`swap_canvas`          , drop-in canvas replacement, the
  hide-then-reparent-then-deleteLater dance that avoids the orphan
  top-level window when the host dock is the active tab during a swap.
* :func:`build_epoch_grid`     , 2-column scrollable grid of single-plot
  tiles used by PSD / Profile / Spectrogram.
* :func:`wire_y_zoom_shortcuts`, Up / Down arrows bound to YZoomMixin.
"""

from __future__ import annotations

from typing import Callable, Iterable

import qtawesome as qta
import matplotlib.patches as patches
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QTransform
from PySide6.QtWidgets import (
    QBoxLayout,
    QGridLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Post-export dialog
# ---------------------------------------------------------------------------


def show_export_summary(
    parent: QWidget | None,
    *,
    context: str,
    summary: str,
    failures: Iterable[str] = (),
) -> None:
    """Show a uniform post-export message box.

    When *failures* is empty an information dialog is shown with title
    ``"{context} export"`` and *summary* as the body. When at least
    one failure is present the dialog is downgraded to a warning with
    the failures appended as a bulleted list.
    """
    failure_list = list(failures)
    if failure_list:
        body = summary + "\n\nProblems:\n  - " + "\n  - ".join(failure_list)
        QMessageBox.warning(parent, f"{context} export (with warnings)", body)
    else:
        QMessageBox.information(parent, f"{context} export", summary)


# ---------------------------------------------------------------------------
# Overview rectangle
# ---------------------------------------------------------------------------


class OverviewWindow:
    """Draggable rectangle on an overview axis indicating the current zoom window."""

    def __init__(self, ax: Axes, x_min: float, x_max: float) -> None:
        self.ax = ax
        y0, y1 = ax.get_ylim()
        self.patch = patches.Rectangle(
            (x_min, y0),
            x_max - x_min,
            y1 - y0,
            color="blue",
            alpha=0.2,
            animated=False,
        )
        ax.add_patch(self.patch)

    def update_y(self) -> None:
        """Update the vertical span of the patch to match current y-limits."""
        y0, y1 = self.ax.get_ylim()
        self.patch.set_y(y0)
        self.patch.set_height(y1 - y0)

    def set_window(self, x_min: float, x_max: float) -> None:
        """Update rectangle position to a new [x_min, x_max] window."""
        self.patch.set_x(x_min)
        self.patch.set_width(x_max - x_min)
        self.update_y()


# ---------------------------------------------------------------------------
# Navigation button factory
# ---------------------------------------------------------------------------


def make_nav_button(
    icon_name: str | None,
    callback: Callable,
    *,
    rotate: int | bool = False,
    tooltip: str | None = None,
) -> QPushButton:
    """Create a flat icon button for the navigation bar."""
    btn = QPushButton()
    if icon_name:
        icon = qta.icon(icon_name)
        if rotate:
            pixmap = icon.pixmap(QSize(48, 48))
            transform = QTransform().rotate(rotate if isinstance(rotate, int) else 0)
            icon = QIcon(pixmap.transformed(transform))
        btn.setIcon(icon)
        btn.setIconSize(QSize(48, 48))
    btn.setFlat(True)
    btn.setStyleSheet(
        """
        QPushButton {
            margin: 4px;
            width: 56px;
            height: 56px;
            border: none;
        }
        """
    )
    btn.clicked.connect(callback)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


# ---------------------------------------------------------------------------
# Axis styling helper
# ---------------------------------------------------------------------------


def style_axis_clean(ax: Axes) -> None:
    """Hide the y-axis tick marks and remove left, right, and top spines."""
    ax.get_yaxis().set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["top"].set_visible(False)


# ---------------------------------------------------------------------------
# Canvas swap helper
# ---------------------------------------------------------------------------


def swap_canvas(
    layout: QBoxLayout,
    old_canvas: FigureCanvas,
    figure: Figure,
    *,
    index: int = 0,
) -> FigureCanvas:
    """Replace ``old_canvas`` with a fresh ``FigureCanvas(figure)`` at *index*.

    The old canvas is hidden BEFORE setParent(None), otherwise Qt
    promotes a previously-visible widget to a top-level window the
    moment it loses its parent, which surfaces as an orphaned plot in
    its own window when the host dock is the active tab during the
    swap. deleteLater frees the C++ side on the next event-loop turn.
    """
    old_canvas.hide()
    old_canvas.setParent(None)
    old_canvas.deleteLater()
    new_canvas = FigureCanvas(figure)
    layout.insertWidget(index, new_canvas)
    return new_canvas


# ---------------------------------------------------------------------------
# Two-column scrollable epoch grid
# ---------------------------------------------------------------------------


def build_epoch_grid(
    host: QWidget,
    plots,
    single_plot_factory: Callable[[object], QWidget],
    *,
    columns: int = 2,
    install_save_shortcut: bool = True,
) -> list[QWidget]:
    """Build the standard scrollable N-column grid of single-plot widgets.

    Shared by ``PSDPlotWidget``, ``ProfilePlotWidget`` and
    ``SpectrogramPlotWidget`` whose ``__init__`` bodies all follow the
    same shape: white scroll-area, white-grid container, one tile per
    pre-computed plot, focus policy, Shift+Ctrl+P save shortcut.

    Parameters
    ----------
    host
        The QWidget that hosts the grid (typically the plot widget
        itself). Receives a ``QVBoxLayout``, focus policy, and the
        Shift+Ctrl+P save shortcut.
    plots
        Iterable of pre-computed plot-data records, one per epoch.
    single_plot_factory
        Callable that takes a plot-data record and returns the per-tile
        QWidget. The widget classes differ across PSD / Profile /
        Spectrogram, so the host passes a lambda that closes over
        per-widget kwargs.
    columns
        Grid column count. Defaults to 2.
    install_save_shortcut
        When True (default) wire Shift+Ctrl+P to ``host._save_all_plots``
        (provided by ``PlotExportMixin``). Set False if the host does
        not mix in the export helper.

    Returns
    -------
    list of QWidget
        The constructed tiles, in plot-data order, ready to be stashed
        on the host (typically as ``host._subplots``).
    """
    host.setStyleSheet("background-color: white;")
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setStyleSheet("background-color: white;")
    container = QWidget()
    container.setStyleSheet("background-color: white;")
    grid = QGridLayout(container)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(5)

    subplots: list[QWidget] = []
    for idx, data in enumerate(plots):
        tile = single_plot_factory(data)
        subplots.append(tile)
        row, col = divmod(idx, columns)
        grid.addWidget(tile, row, col)

    scroll_area.setWidget(container)
    outer = QVBoxLayout(host)
    outer.addWidget(scroll_area)
    host.setLayout(outer)
    host.setFocusPolicy(Qt.StrongFocus)

    if install_save_shortcut and hasattr(host, "_save_all_plots"):
        save = QShortcut(QKeySequence("Shift+Ctrl+P"), host)
        save.setContext(Qt.WidgetWithChildrenShortcut)
        save.activated.connect(host._save_all_plots)

    return subplots


def wire_y_zoom_shortcuts(host: QWidget) -> None:
    """Install Up / Down arrow shortcuts bound to YZoomMixin methods.

    The host must mix in ``YZoomMixin`` (it provides ``_zoom_in`` and
    ``_zoom_out``). Used by PSD and Profile widgets; the spectrogram
    skips this because its y-axis carries frequency rather than band
    power.

    The shortcuts are scoped to ``WidgetWithChildrenShortcut`` so the
    inner ``QScrollArea`` cannot eat the arrow keys for scrolling
    before they reach the zoom slots.
    """
    z_in = QShortcut(QKeySequence(Qt.Key_Up), host)
    z_in.setContext(Qt.WidgetWithChildrenShortcut)
    z_in.activated.connect(host._zoom_in)

    z_out = QShortcut(QKeySequence(Qt.Key_Down), host)
    z_out.setContext(Qt.WidgetWithChildrenShortcut)
    z_out.activated.connect(host._zoom_out)
