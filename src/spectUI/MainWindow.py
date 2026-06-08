# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectUI main window.

Architecture
------------
A single :class:`MainWindow` owns:

* A ``CDockManager`` that hosts all docked plot widgets.
* The current :class:`~spectHR.session.Session` and
  :class:`~spectHR.config.WorkspaceView`.
* A :class:`~spectUI.plot_worker.DockScheduler` for off-thread computation.

All docked widgets must implement the
:class:`~spectUI.common.timeline.TimelinePlotWidget` interface:

    widget.set_session(session, config)   — called on file load / workspace change
    widget.set_epoch(name)                — called on epoch navigation

The ``_epoch_box`` QComboBox in the toolbar selects the active epoch for all
docks simultaneously.

Dock registration
-----------------
Call :meth:`add_dock` after ``__init__`` to attach a widget to the manager.
Each dock is bookkeepked so ``_broadcast_session`` and ``_broadcast_epoch``
can fan-out updates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
    QWidget,
)
from PySide6QtAds import CDockManager, CDockWidget, DockWidgetArea

import spectHR
from spectHR.DataSet.loaders import load
from spectHR.session import Session
from spectHR.Tools.Logger import logger
from spectHR.config import WorkspaceView, log_level_from_workspace

from spectUI.common.timeline import TimelinePlotWidget
from spectUI.perspectives import PerspectiveMenu
from spectUI.plot_worker import DockScheduler
from spectUI.workSpace import (
    default_workspace,
    get_export_dir,
    load_workspace,
    save_workspace,
)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """Application main window."""

    _ORG  = "spectHR"
    _APP  = "spectHR"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("spectHR")
        self.resize(1400, 900)

        CDockManager.setConfigFlag(CDockManager.OpaqueSplitterResize,   True)
        CDockManager.setConfigFlag(CDockManager.XmlCompressionEnabled,  False)
        CDockManager.setAutoHideConfigFlags(CDockManager.DefaultAutoHideConfig)

        self._dock_manager = CDockManager(self)
        self._scheduler    = DockScheduler()

        self._session:        Session | None = None
        self._workspace:      dict           = default_workspace()
        self._workspace_path: Path  | None   = None
        self._docks:          list[tuple[CDockWidget, TimelinePlotWidget]] = []

        self._setup_menu()
        self._setup_toolbar()
        self._restore_session()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_menu(self) -> None:
        mb = self.menuBar()

        # File menu
        file_menu = mb.addMenu("&File")

        open_act = QAction("&Open…", self, shortcut=QKeySequence.Open)
        open_act.triggered.connect(self.open_file)
        file_menu.addAction(open_act)

        file_menu.addSeparator()

        ws_open_act = QAction("Open workspace…", self)
        ws_open_act.triggered.connect(self.open_workspace)
        file_menu.addAction(ws_open_act)

        ws_save_act = QAction("Save workspace", self, shortcut=QKeySequence.Save)
        ws_save_act.triggered.connect(self.save_current_workspace)
        file_menu.addAction(ws_save_act)

        ws_save_as_act = QAction("Save workspace as…", self)
        ws_save_as_act.triggered.connect(self.save_workspace_as)
        file_menu.addAction(ws_save_as_act)

        file_menu.addSeparator()

        quit_act = QAction("&Quit", self, shortcut=QKeySequence.Quit)
        quit_act.triggered.connect(QApplication.quit)
        file_menu.addAction(quit_act)

        # View > Layout (perspectives)
        view_menu = mb.addMenu("&View")
        self._perspective_menu = PerspectiveMenu(
            view_menu.addMenu("&Layout"), self._dock_manager
        )

    def _setup_toolbar(self) -> None:
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        # Epoch selector
        tb.addWidget(QLabel("  Epoch: "))
        self._epoch_box = QComboBox()
        self._epoch_box.setMinimumWidth(160)
        self._epoch_box.currentTextChanged.connect(self._on_epoch_selected)
        tb.addWidget(self._epoch_box)

    # ------------------------------------------------------------------
    # Dock management
    # ------------------------------------------------------------------

    def add_dock(
        self,
        widget: TimelinePlotWidget,
        title:  str,
        area:   DockWidgetArea = DockWidgetArea.CenterDockWidgetArea,
        *,
        reference: CDockWidget | None = None,
    ) -> CDockWidget:
        """Wrap *widget* in a CDockWidget and add it to the dock manager.

        Returns the :class:`CDockWidget` so the caller can use it as a
        ``reference`` for subsequent docks.
        """
        dock = CDockWidget(title)
        dock.setWidget(widget)
        dock.setObjectName(title.replace(" ", "_"))

        if reference is not None:
            self._dock_manager.addDockWidgetTabToArea(dock, reference.dockAreaWidget())
        else:
            self._dock_manager.addDockWidget(area, dock)

        widget.epoch_request.connect(self._on_epoch_request)
        self._docks.append((dock, widget))

        if self._session is not None:
            config = WorkspaceView(self._workspace)
            widget.set_session(self._session, config)

        return dock

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def open_file(self) -> None:
        dirs  = self._workspace.get("Directories", {}) or {}
        start = dirs.get("DataDirectory", str(Path.home()))

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open physiological recording",
            start,
            "Recordings (*.EVT *.evt *.EDF *.edf *.xdf *.XDF *.pkl *.txt *.csv)"
            ";;All files (*)",
        )
        if not path:
            return

        try:
            session = load(path)
        except Exception as exc:
            QMessageBox.critical(self, "Load error", str(exc))
            logger.error(f"Failed to load {path}: {exc}")
            return

        self._load_session(session)

    def _load_session(self, session: Session) -> None:
        self._session = session
        self.setWindowTitle(f"spectHR — {session.name}")
        self._update_epoch_box()
        self._broadcast_session()

    # ------------------------------------------------------------------
    # Workspace operations
    # ------------------------------------------------------------------

    def open_workspace(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open workspace", str(Path.home()), "Workspace (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            self._workspace      = load_workspace(path)
            self._workspace_path = Path(path)
        except Exception as exc:
            QMessageBox.critical(self, "Workspace error", str(exc))
            return
        self._apply_workspace()

    def save_current_workspace(self) -> None:
        if self._workspace_path is None:
            self.save_workspace_as()
        else:
            save_workspace(self._workspace, self._workspace_path)

    def save_workspace_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save workspace", str(Path.home()), "Workspace (*.json)"
        )
        if not path:
            return
        self._workspace_path = Path(path)
        save_workspace(self._workspace, self._workspace_path)

    def _apply_workspace(self) -> None:
        import logging
        level = log_level_from_workspace(self._workspace)
        logging.getLogger("spectHR").setLevel(level)
        if self._session is not None:
            self._broadcast_session()

    # ------------------------------------------------------------------
    # Epoch navigation
    # ------------------------------------------------------------------

    def _update_epoch_box(self) -> None:
        self._epoch_box.blockSignals(True)
        self._epoch_box.clear()
        if self._session is not None:
            self._epoch_box.addItems(list(self._session.epochs))
        self._epoch_box.blockSignals(False)
        if self._epoch_box.count():
            self._epoch_box.setCurrentIndex(0)

    def _on_epoch_selected(self, name: str) -> None:
        if name:
            self._broadcast_epoch(name)

    def _on_epoch_request(self, name: str) -> None:
        """A dock requested an epoch change — synchronise the epoch box."""
        idx = self._epoch_box.findText(name)
        if idx >= 0:
            self._epoch_box.setCurrentIndex(idx)
        else:
            self._broadcast_epoch(name)

    # ------------------------------------------------------------------
    # Broadcast helpers
    # ------------------------------------------------------------------

    def _broadcast_session(self) -> None:
        if self._session is None:
            return
        config = WorkspaceView(self._workspace)
        for _, widget in self._docks:
            try:
                widget.set_session(self._session, config)
            except Exception as exc:
                logger.warning(f"set_session failed on {widget!r}: {exc}")

    def _broadcast_epoch(self, name: str) -> None:
        for _, widget in self._docks:
            try:
                widget.set_epoch(name)
            except Exception as exc:
                logger.warning(f"set_epoch({name!r}) failed on {widget!r}: {exc}")

    # ------------------------------------------------------------------
    # QSettings persistence
    # ------------------------------------------------------------------

    def _restore_session(self) -> None:
        settings = QSettings(self._ORG, self._APP)
        geometry = settings.value("mainWindow/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        ws_path = settings.value("workspace/path")
        if ws_path and Path(str(ws_path)).exists():
            try:
                self._workspace      = load_workspace(ws_path)
                self._workspace_path = Path(str(ws_path))
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        settings = QSettings(self._ORG, self._APP)
        settings.setValue("mainWindow/geometry", self.saveGeometry())
        if self._workspace_path is not None:
            settings.setValue("workspace/path", str(self._workspace_path))
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import sys

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("spectHR")
    app.setOrganizationName("spectHR")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
