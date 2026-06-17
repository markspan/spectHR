# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Window-state persistence, the only machine-specific preference kept outside
the workspace file.

Window geometry and the dock layout are per-machine UI state (not analysis
"settings"), so they live in QSettings rather than in ``workspace.json``.  All
*settings*, analysis parameters and the working directories, live together
in the single :class:`~spectUI.parameters.Parameters` workspace, saved to /
loaded from ``~/workspace.json`` (see :class:`~spectUI.MainWindow`).

We force the **INI format** (not the platform-native backend) so the state
always lands in a human-readable file under the user's config directory rather
than the Windows registry:
  Windows : ``%APPDATA%\\spectHR\\spectHR.ini``
  Linux   : ``~/.config/spectHR/spectHR.ini``
  macOS   : ``~/Library/Preferences/spectHR/spectHR.ini``
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMainWindow

from PySide6QtAds import CDockManager


_ORG = "spectHR"
_APP = "spectHR"


class AppSettings:
    """QSettings wrapper for window geometry, the dock layout and the saved
    dock perspectives (named layouts)."""

    def __init__(self, settings: QSettings | None = None) -> None:
        # Tests inject an isolated QSettings (an explicit .ini file); production
        # uses an INI file in the user's config dir (never the registry, even on
        # Windows, the two-arg QSettings would default to NativeFormat there).
        self._qs = settings if settings is not None else QSettings(
            QSettings.IniFormat, QSettings.UserScope, _ORG, _APP)

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

    def save_perspectives(self, dock_manager: CDockManager) -> None:
        """Persist every named perspective (built-in and user-defined)."""
        dock_manager.savePerspectives(self._qs)

    def load_perspectives(self, dock_manager: CDockManager) -> bool:
        """Restore saved perspectives into *dock_manager*.

        ``CDockManager.loadPerspectives`` *clears* the existing perspective map
        before reading, so it is only called when the settings actually hold
        some, otherwise it would wipe the built-ins captured at startup on a
        first run.  Returns ``True`` when perspectives were loaded.
        """
        n = self._qs.beginReadArray("Perspectives")
        self._qs.endArray()
        if n <= 0:
            return False
        dock_manager.loadPerspectives(self._qs)
        return True
