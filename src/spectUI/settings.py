# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Window-state persistence — the only machine-specific preference kept outside
the workspace file.

Window geometry and the dock layout are per-machine UI state (not analysis
"settings"), so they live in QSettings rather than in ``workspace.json``.  All
*settings* — analysis parameters and the working directories — live together
in the single :class:`~spectUI.parameters.Parameters` workspace, saved to /
loaded from ``~/workspace.json`` (see :class:`~spectUI.MainWindow`).

QSettings uses the platform-conventional location:
  Windows : ``%APPDATA%\\spectHR\\spectHR.ini`` (or the registry)
  Linux   : ``~/.config/spectHR/spectHR.ini``
  macOS   : ``~/Library/Application Support/spectHR/spectHR.ini``
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMainWindow

from PySide6QtAds import CDockManager


_ORG = "spectHR"
_APP = "spectHR"


class AppSettings:
    """QSettings wrapper for window geometry and the dock layout."""

    def __init__(self) -> None:
        self._qs = QSettings(_ORG, _APP)

    def save_window(self, window: QMainWindow, dock_manager: CDockManager) -> None:
        """Persist window geometry and dock layout."""
        self._qs.setValue("window/geometry",   window.saveGeometry())
        self._qs.setValue("window/dock_state", dock_manager.saveState())

    def restore_window(self, window: QMainWindow, dock_manager: CDockManager) -> None:
        """Restore window geometry and dock layout."""
        geometry = self._qs.value("window/geometry")
        if geometry:
            window.restoreGeometry(geometry)
        state = self._qs.value("window/dock_state")
        if state:
            dock_manager.restoreState(state)
