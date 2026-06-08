# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Application settings — machine-specific preferences stored in QSettings.

:class:`AppSettings` is separate from :class:`~spectUI.workspace.Workspace`
(analysis parameters) because directory paths and window geometry are
per-machine preferences that should never travel inside a workspace file.

QSettings uses the platform-conventional location:
  Windows : ``%APPDATA%\\spectHR\\spectHR.ini``
  Linux   : ``~/.config/spectHR/spectHR.ini``
  macOS   : ``~/Library/Application Support/spectHR/spectHR.ini``
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMainWindow

from PySide6QtAds import CDockManager


_ORG = "spectHR"
_APP = "spectHR"

_DEFAULTS = {
    "data_dir":    str(Path.home() / "Documents" / "spectHR"),
    "cache_dir":   str(Path.home() / "Documents" / "spectHR" / "cache"),
    "output_dir":  str(Path.home() / "Documents" / "spectHR" / "export"),
}


class AppSettings:
    """Typed wrapper around QSettings for application-level preferences.

    Instantiate once in ``MainWindow.__init__`` and keep as
    ``self._settings``.  Every property has both a getter and a setter
    so reading and writing are symmetric:

    >>> s = AppSettings()
    >>> s.data_dir = Path("/data/experiments")
    >>> s.data_dir
    PosixPath('/data/experiments')
    """

    def __init__(self) -> None:
        self._qs = QSettings(_ORG, _APP)

    # ------------------------------------------------------------------
    # Working directories
    # ------------------------------------------------------------------

    @property
    def data_dir(self) -> Path:
        return Path(self._qs.value("directories/data", _DEFAULTS["data_dir"]))

    @data_dir.setter
    def data_dir(self, path: Path | str) -> None:
        self._qs.setValue("directories/data", str(path))

    @property
    def cache_dir(self) -> Path:
        return Path(self._qs.value("directories/cache", _DEFAULTS["cache_dir"]))

    @cache_dir.setter
    def cache_dir(self, path: Path | str) -> None:
        self._qs.setValue("directories/cache", str(path))

    @property
    def output_dir(self) -> Path:
        return Path(self._qs.value("directories/output", _DEFAULTS["output_dir"]))

    @output_dir.setter
    def output_dir(self, path: Path | str) -> None:
        self._qs.setValue("directories/output", str(path))

    @property
    def directories(self) -> dict:
        """Flat dict compatible with ``DirectorySelectorDialog``."""
        return {
            "DataDirectory":   str(self.data_dir),
            "CacheDirectory":  str(self.cache_dir),
            "OutputDirectory": str(self.output_dir),
        }

    @directories.setter
    def directories(self, dirs: dict) -> None:
        """Accept the dict returned by ``DirectorySelectorDialog.get_directories()``."""
        if "DataDirectory"   in dirs: self.data_dir   = dirs["DataDirectory"]
        if "CacheDirectory"  in dirs: self.cache_dir  = dirs["CacheDirectory"]
        if "OutputDirectory" in dirs: self.output_dir = dirs["OutputDirectory"]

    def export_dir(self, context: str = "") -> Path:
        """Return the output directory for *context*, creating it if needed."""
        path = self.output_dir / context if context else self.output_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Workspace path
    # ------------------------------------------------------------------

    @property
    def workspace_path(self) -> Path | None:
        v = self._qs.value("workspace/path", "")
        return Path(v) if v and Path(v).exists() else None

    @workspace_path.setter
    def workspace_path(self, path: Path | str | None) -> None:
        self._qs.setValue("workspace/path", str(path) if path else "")

    # ------------------------------------------------------------------
    # Window state
    # ------------------------------------------------------------------

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
