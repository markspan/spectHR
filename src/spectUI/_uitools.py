# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
_uitools.py - Shared GUI helpers used by the plot widgets.

Exports
-------
* :func:`show_export_summary` - uniform post-export message box.
* :class:`OverviewWindow`    - draggable rectangle on an overview axis.
* :func:`make_nav_button`    - icon button factory used by both
  ``PrepPlotWidget`` and ``HRPlotWidget`` navigation bars.
* :func:`style_axis_clean`   - hide y-axis and non-bottom spines.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

import qtawesome as qta
from matplotlib.axes import Axes
import matplotlib.patches as patches
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QTransform
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget


# ---------------------------------------------------------------------------
# Post-export dialog
# ---------------------------------------------------------------------------


def show_export_summary(
    parent: Optional[QWidget],
    *,
    context: str,
    summary: str,
    failures: Iterable[str] = (),
) -> None:
    """Show a uniform post-export message box.

    When *failures* is empty an information dialog is shown with title
    ``"{context} export"`` and *summary* as the body. When at least one
    failure is present the dialog is downgraded to a warning with the
    failures appended as a bulleted list.

    Parameters
    ----------
    parent : QWidget or None
        Parent widget for the dialog.
    context : str
        Short human label that names the export (``"PSD"``, ``"Profile"``, ...).
    summary : str
        The main message line.
    failures : iterable of str, optional
        Per-file failure messages.
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
    icon_name: Optional[str],
    callback: Callable,
    *,
    rotate: "int | bool" = False,
    tooltip: Optional[str] = None,
) -> QPushButton:
    """Create a flat icon button for the navigation bar.

    Parameters
    ----------
    icon_name : str or None
        qtawesome icon name (e.g. ``"fa6s.backward"``). No icon is set when
        ``None``.
    callback : callable
        Slot connected to ``clicked``.
    rotate : int or False
        Degrees to rotate the icon pixmap clock-wise. ``False`` means no
        rotation.
    tooltip : str or None
        Tool tip string shown on hover.
    """
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
