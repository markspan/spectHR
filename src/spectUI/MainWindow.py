# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectUI main window.

Dock layout
-----------
Left:   workspace file browser (QTreeWidget).
Center: 12 tabified plot docks (placeholders until widgets are built).
Bottom: log output (:class:`~spectUI.widgets.log_widget.LogWidget`,
        hidden by default).

Only workspace I/O and directory settings are wired.
Plot-dock callbacks are stubs pending widget implementation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6QtAds import CDockManager, CDockWidget, DockWidgetArea

from spectHR._version import __version__
from spectHR.Tools.Logger import logger
from spectHR.session import Session

from spectUI.perspectives import (
    BUILTIN_COMPARE,
    BUILTIN_DEFAULT,
    BUILTIN_PSDFOCUS,
    PerspectiveMenu,
)
from spectUI.plot_worker import DockScheduler
from spectUI.settings import AppSettings
from spectUI.widgets.WorkSpaceEditor import DirectorySelectorDialog, ParametersEditorDialog
from spectUI.widgets.log_widget import LogWidget
from spectUI.parameters import Parameters, populate_tree

# ---------------------------------------------------------------------------
# Dock object-name constants
# ---------------------------------------------------------------------------

_DOCK_WORKSPACE       = "dock.workspace"
_DOCK_PREPROCESSING   = "dock.preprocessing"
_DOCK_HR              = "dock.hr"
_DOCK_BP              = "dock.bp"
_DOCK_POINCARE        = "dock.poincare"
_DOCK_EPOCHS          = "dock.epochs"
_DOCK_PSD             = "dock.psd"
_DOCK_SPECTROGRAM     = "dock.spectrogram"
_DOCK_SPECTROGRAM3D   = "dock.spectrogram3d"
_DOCK_TRANSFER        = "dock.transfer"
_DOCK_TRANSFERPROFILE = "dock.transferprofile"
_DOCK_PROFILES        = "dock.profiles"
_DOCK_RESULTS         = "dock.results"
_DOCK_LOG             = "dock.log"

_CENTRE_DOCKS: tuple[tuple[str, str], ...] = (
    (_DOCK_PREPROCESSING,   "Preprocessing"),
    (_DOCK_HR,              "HR Series"),
    (_DOCK_BP,              "Blood Pressure"),
    (_DOCK_POINCARE,        "Poincaré"),
    (_DOCK_EPOCHS,          "Epochs"),
    (_DOCK_PSD,             "PSD"),
    (_DOCK_SPECTROGRAM,     "Spectrogram"),
    (_DOCK_SPECTROGRAM3D,   "Spectrogram 3D"),
    (_DOCK_TRANSFER,        "Transfer"),
    (_DOCK_TRANSFERPROFILE, "Transfer Profile"),
    (_DOCK_PROFILES,        "Profiles"),
    (_DOCK_RESULTS,      "Results"),
)

_VIEW_LABELS: dict[str, str] = {
    _DOCK_WORKSPACE:       "Workspace",
    _DOCK_PREPROCESSING:   "Preprocessing",
    _DOCK_HR:              "HR Series",
    _DOCK_BP:              "Blood Pressure",
    _DOCK_POINCARE:        "Poincaré",
    _DOCK_EPOCHS:          "Epochs",
    _DOCK_PSD:             "PSD",
    _DOCK_SPECTROGRAM:     "Spectrogram",
    _DOCK_SPECTROGRAM3D:   "Spectrogram 3D",
    _DOCK_TRANSFER:        "Transfer",
    _DOCK_TRANSFERPROFILE: "Transfer Profile",
    _DOCK_PROFILES:        "Profiles",
    _DOCK_RESULTS:      "Results",
    _DOCK_LOG:             "Log",
}


# ---------------------------------------------------------------------------
# Placeholder
# ---------------------------------------------------------------------------

class _Placeholder(QWidget):
    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lbl = QLabel(name)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#bbb; font-size:16pt;")
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)
        self.setStyleSheet("background:#f8f8f8;")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Application main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"spectHR  v{__version__}")
        self.resize(1400, 900)

        CDockManager.setConfigFlag(CDockManager.OpaqueSplitterResize,  True)
        CDockManager.setConfigFlag(CDockManager.XmlCompressionEnabled, False)
        CDockManager.setAutoHideConfigFlags(CDockManager.DefaultAutoHideConfig)

        self._dock_manager    = CDockManager(self)
        self._scheduler       = DockScheduler()
        self._settings        = AppSettings()
        self._parameters       = Parameters.default()
        self._parameters_path: Path | None = None
        self._session: Session | None     = None

        self._docks: dict[str, CDockWidget] = {}

        self._build_docks()
        self._build_menu_and_toolbar()
        self._capture_builtin_perspectives()
        self._restore()

    # ------------------------------------------------------------------
    # Dock construction
    # ------------------------------------------------------------------

    def _build_docks(self) -> None:
        # Left: workspace file browser
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemDoubleClicked.connect(self._on_file_activated)
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        self._add_dock(_DOCK_WORKSPACE, "Workspace", self._tree,
                       DockWidgetArea.LeftDockWidgetArea)

        # Centre: tabified plot placeholders
        reference_area = None
        for obj_name, title in _CENTRE_DOCKS:
            dock = self._add_dock(obj_name, title, _Placeholder(title))
            if reference_area is None:
                self._dock_manager.addDockWidget(
                    DockWidgetArea.CenterDockWidgetArea, dock
                )
                reference_area = dock.dockAreaWidget()
            else:
                self._dock_manager.addDockWidgetTabToArea(dock, reference_area)

        # Bottom: log (hidden by default)
        self._log_widget = LogWidget()
        log_dock = self._add_dock(_DOCK_LOG, "Log", self._log_widget,
                                  DockWidgetArea.BottomDockWidgetArea)
        log_dock.toggleView(False)

    def _add_dock(
        self,
        obj_name: str,
        title:    str,
        widget:   QWidget,
        area:     DockWidgetArea | None = None,
    ) -> CDockWidget:
        dock = CDockWidget(self._dock_manager, title)
        dock.setObjectName(obj_name)
        dock.setWidget(widget)
        self._docks[obj_name] = dock
        if area is not None:
            self._dock_manager.addDockWidget(area, dock)
        return dock

    # ------------------------------------------------------------------
    # Menu bar + toolbar
    # ------------------------------------------------------------------

    def _build_menu_and_toolbar(self) -> None:
        self._open_act     = self._action("fa5s.cog",               "&Open settings…",       self.open_workspace,          "Ctrl+O")
        self._edit_act     = self._action("fa5s.edit",             "&Edit settings…",       self.edit_workspace,          "Ctrl+E")
        self._save_act     = self._action("fa5s.save",             "&Save settings",        self.save_workspace,          "Ctrl+S")
        self._settings_act = self._action("fa5s.folder-open",      "Directory &settings…",  self.open_directory_settings, "Ctrl+Shift+S")
        self._doc_act      = self._action("fa5s.question-circle",  "&Documentation",        self._open_docs,              "Ctrl+D")
        self._add_epoch_act= self._action("fa5s.plus-circle",      "Add &Epoch",            lambda: None,                 "Ctrl+N")
        self._add_epoch_act.setEnabled(False)

        # ---- Settings menu ----
        ws_menu = self.menuBar().addMenu("&Settings")
        ws_menu.addAction(self._open_act)
        ws_menu.addSeparator()
        ws_menu.addAction(self._edit_act)
        ws_menu.addAction(self._save_act)
        ws_menu.addSeparator()
        ws_menu.addAction(self._settings_act)
        ws_menu.addSeparator()
        quit_act = QAction("&Quit", self, shortcut=QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(QApplication.quit)
        ws_menu.addAction(quit_act)

        # ---- View menu ----
        view_menu = self.menuBar().addMenu("&View")
        for obj_name, label in _VIEW_LABELS.items():
            dock = self._docks.get(obj_name)
            if dock:
                act = dock.toggleViewAction()
                act.setText(label)
                view_menu.addAction(act)
        view_menu.addSeparator()
        self._perspective_menu = PerspectiveMenu(
            self, self._dock_manager, view_menu.addMenu("&Layout")
        )

        # ---- Help menu ----
        self.menuBar().addMenu("&Help").addAction(self._doc_act)

        # ---- Toolbar ----
        tb = self.addToolBar("Main")
        tb.setObjectName("toolbar.main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(20, 20))

        tb.addAction(self._open_act)

        # Edit + Save stacked (half-height)
        pair = QWidget()
        pair.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(pair)
        vbox.setContentsMargins(2, 2, 2, 2)
        vbox.setSpacing(0)
        for act, label in ((self._edit_act, "Edit"), (self._save_act, "Save")):
            btn = QToolButton()
            btn.setDefaultAction(act)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setIconSize(QSize(16, 16))
            btn.setText(label)
            btn.setStyleSheet("QToolButton { background: transparent; }")
            vbox.addWidget(btn)
        tb.addWidget(pair)
        tb.addSeparator()

        tb.addAction(self._settings_act)
        tb.addSeparator()
        tb.addAction(self._add_epoch_act)
        tb.addSeparator()
        tb.addAction(self._doc_act)

    def _action(
        self,
        icon:     str,
        text:     str,
        slot,
        shortcut: str | None = None,
    ) -> QAction:
        act = QAction(qta.icon(icon), text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        return act

    # ------------------------------------------------------------------
    # Built-in perspectives
    # ------------------------------------------------------------------

    def _capture_builtin_perspectives(self) -> None:
        self._dock_manager.addPerspective(BUILTIN_DEFAULT)

        epochs = self._docks.get(_DOCK_EPOCHS)
        if epochs:
            self._dock_manager.addDockWidget(
                DockWidgetArea.BottomDockWidgetArea, epochs
            )
        self._dock_manager.addPerspective(BUILTIN_COMPARE)

        self._dock_manager.openPerspective(BUILTIN_DEFAULT)
        self._dock_manager.addPerspective(BUILTIN_PSDFOCUS)
        self._dock_manager.openPerspective(BUILTIN_DEFAULT)

    # ------------------------------------------------------------------
    # Workspace actions
    # ------------------------------------------------------------------

    def open_workspace(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open workspace", str(self._settings.data_dir),
            "Parameters (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            self._parameters      = Parameters.load(path)
            self._parameters_path = Path(path)
        except Exception as exc:
            QMessageBox.critical(self, "Parameters error", str(exc))
            return
        self._on_workspace_changed()

    def save_workspace(self) -> None:
        if self._parameters_path is None:
            self._save_workspace_as()
        else:
            self._parameters.save(self._parameters_path)

    def _save_workspace_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save workspace", str(self._settings.data_dir),
            "Parameters (*.json)",
        )
        if not path:
            return
        self._parameters_path = Path(path)
        self._parameters.save(self._parameters_path)

    def edit_workspace(self) -> None:
        dlg = ParametersEditorDialog(self._parameters.to_dict(), self)
        if dlg.exec():
            self._parameters = Parameters.from_dict(
                dlg.get_parameters(self._parameters.to_dict())
            )
            self._on_workspace_changed()

    def open_directory_settings(self) -> None:
        dlg = DirectorySelectorDialog(self._settings.directories, self)
        if dlg.exec():
            self._settings.directories = dlg.get_directories()
            populate_tree(self._tree, self._settings.data_dir)

    def _on_workspace_changed(self) -> None:
        import logging
        logging.getLogger("spectHR").setLevel(self._parameters.log_level)
        # TODO: re-broadcast to plot docks once widgets are built

    # ------------------------------------------------------------------
    # File tree
    # ------------------------------------------------------------------

    def _on_tree_item_clicked(self, item, _col: int) -> None:
        if not (item.flags() & Qt.ItemIsSelectable):
            self._tree.clearSelection()

    def _on_file_activated(self, item, _col: int = 0) -> None:
        data = item.data(0, Qt.UserRole)
        if not data or data.get("type") != "dataset":
            return
        logger.info(f"File selected: {data.get('filename')}  (loading not yet wired)")

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _open_docs(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://github.com/markspan/spectHR"))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _restore(self) -> None:
        ws_path = self._settings.workspace_path
        if ws_path:
            try:
                self._parameters      = Parameters.load(ws_path)
                self._parameters_path = ws_path
            except Exception:
                pass
        self._settings.restore_window(self, self._dock_manager)
        populate_tree(self._tree, self._settings.data_dir)

    def closeEvent(self, event) -> None:
        self._settings.save_window(self, self._dock_manager)
        if self._parameters_path is not None:
            self._settings.workspace_path = self._parameters_path
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("spectHR")
    app.setOrganizationName("spectHR")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
