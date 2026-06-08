# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectUI main window.

Dock layout
-----------
Left:   workspace file browser (QTreeWidget)
Center: 12 tabified plot docks (placeholders until widgets are built)
Bottom: log output (hidden by default)

Workspace callbacks
-------------------
Only directory configuration is wired for now:
  * Open / Save workspace  — JSON file I/O
  * Settings               — DirectorySelectorDialog (DataDirectory /
                             CacheDirectory / OutputDirectory)

All plot-dock refresh callbacks are stubs; they will be connected as each
widget is implemented.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, QSettings, QSize
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6QtAds import CDockManager, CDockWidget, DockWidgetArea

from spectHR.Tools.Logger import logger
from spectHR.config import WorkspaceView, log_level_from_workspace
from spectHR.session import Session

from spectUI.common.uitools import make_nav_button
from spectUI.perspectives import (
    BUILTIN_COMPARE,
    BUILTIN_DEFAULT,
    BUILTIN_PSDFOCUS,
    PerspectiveMenu,
)
from spectUI.plot_worker import DockScheduler
from spectUI.widgets.WorkSpaceEditor import DirectorySelectorDialog, ParametersEditorDialog
from spectUI.workSpace import (
    PopulateTree,
    default_workspace,
    get_export_dir,
    load_workspace,
    save_workspace,
)

# ---------------------------------------------------------------------------
# Dock object-name constants
# ---------------------------------------------------------------------------

_DOCK_WORKSPACE      = "dock.workspace"
_DOCK_PREPROCESSING  = "dock.preprocessing"
_DOCK_IBI            = "dock.ibi"
_DOCK_BP             = "dock.bp"
_DOCK_POINCARE       = "dock.poincare"
_DOCK_EPOCHS         = "dock.epochs"
_DOCK_PSD            = "dock.psd"
_DOCK_SPECTROGRAM    = "dock.spectrogram"
_DOCK_SPECTROGRAM3D  = "dock.spectrogram3d"
_DOCK_TRANSFER       = "dock.transfer"
_DOCK_TRANSFERPROFILE= "dock.transferprofile"
_DOCK_PROFILES       = "dock.profiles"
_DOCK_PARAMETERS     = "dock.parameters"
_DOCK_LOG            = "dock.log"


# ---------------------------------------------------------------------------
# Placeholder widget
# ---------------------------------------------------------------------------

class _Placeholder(QWidget):
    """Greyed-out dock filler shown while the real widget is not yet built."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        lbl = QLabel(name)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color: #aaa; font-size: 16pt;")
        layout.addWidget(lbl)
        self.setStyleSheet("background: #f8f8f8;")


# ---------------------------------------------------------------------------
# Qt log handler
# ---------------------------------------------------------------------------

class _QtLogHandler(logging.Handler):
    """Append log records to a QPlainTextEdit, thread-safe via invokeMethod."""

    def __init__(self, widget: QPlainTextEdit) -> None:
        super().__init__()
        self._widget = widget
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        # Qt widgets must only be touched from the main thread; use a
        # queued invocation so worker-thread log calls are safe.
        self._widget.metaObject().invokeMethod(
            self._widget,
            "appendPlainText",
            Qt.QueuedConnection,
            msg,
        )


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Application main window."""

    _ORG = "spectHR"
    _APP = "spectHR"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("spectHR")
        self.resize(1400, 900)

        CDockManager.setConfigFlag(CDockManager.OpaqueSplitterResize,   True)
        CDockManager.setConfigFlag(CDockManager.XmlCompressionEnabled,  False)
        CDockManager.setAutoHideConfigFlags(CDockManager.DefaultAutoHideConfig)

        self._dock_manager   = CDockManager(self)
        self._scheduler      = DockScheduler()
        self._session: Session | None = None
        self._workspace: dict = default_workspace()
        self._workspace_path: Path | None = None

        # dock name → CDockWidget (built in _build_docks)
        self._docks: dict[str, CDockWidget] = {}

        self._build_docks()
        self._build_menubar()
        self._capture_builtin_perspectives()
        self._restore_session()
        self._apply_log_level()

    # ------------------------------------------------------------------
    # Dock construction
    # ------------------------------------------------------------------

    def _build_docks(self) -> None:
        """Create all 14 CDockWidgets and add them to the manager."""

        # --- Workspace file browser (left) ---
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemDoubleClicked.connect(self._on_file_activated)
        ws_dock = self._make_dock(_DOCK_WORKSPACE, "Workspace", self._tree)
        self._dock_manager.addDockWidget(DockWidgetArea.LeftDockWidgetArea, ws_dock)

        # --- Centre tabified plot docks ---
        centre_docks = [
            (_DOCK_PREPROCESSING,   "Preprocessing"),
            (_DOCK_IBI,             "HR Series"),
            (_DOCK_BP,              "Blood Pressure"),
            (_DOCK_POINCARE,        "Poincaré"),
            (_DOCK_EPOCHS,          "Epochs"),
            (_DOCK_PSD,             "PSD"),
            (_DOCK_SPECTROGRAM,     "Spectrogram"),
            (_DOCK_SPECTROGRAM3D,   "Spectrogram 3D"),
            (_DOCK_TRANSFER,        "Transfer"),
            (_DOCK_TRANSFERPROFILE, "Transfer Profile"),
            (_DOCK_PROFILES,        "Profiles"),
            (_DOCK_PARAMETERS,      "Parameters"),
        ]
        reference_area = None
        for obj_name, title in centre_docks:
            widget = _Placeholder(title)
            dock   = self._make_dock(obj_name, title, widget)
            if reference_area is None:
                self._dock_manager.addDockWidget(
                    DockWidgetArea.CenterDockWidgetArea, dock
                )
                reference_area = dock.dockAreaWidget()
            else:
                self._dock_manager.addDockWidgetTabToArea(dock, reference_area)

        # --- Log dock (bottom, hidden by default) ---
        self._log_widget = QPlainTextEdit()
        self._log_widget.setReadOnly(True)
        self._log_widget.setMaximumBlockCount(2000)
        log_dock = self._make_dock(_DOCK_LOG, "Log", self._log_widget)
        self._dock_manager.addDockWidget(DockWidgetArea.BottomDockWidgetArea, log_dock)
        log_dock.toggleView(False)

        # Wire Python logging → log dock
        handler = _QtLogHandler(self._log_widget)
        logging.getLogger("spectHR").addHandler(handler)

    def _make_dock(self, obj_name: str, title: str, widget: QWidget) -> CDockWidget:
        dock = CDockWidget(title)
        dock.setObjectName(obj_name)
        dock.setWidget(widget)
        self._docks[obj_name] = dock
        return dock

    # ------------------------------------------------------------------
    # Menu bar and toolbar
    # ------------------------------------------------------------------

    def _build_menubar(self) -> None:
        mb = self.menuBar()

        # ---- WorkSpace menu ----
        ws_menu = mb.addMenu("&WorkSpace")

        open_act = QAction(qta.icon("fa5s.folder-open"), "&Open workspace…", self)
        open_act.setShortcut(QKeySequence("Ctrl+O"))
        open_act.triggered.connect(self.open_workspace)
        ws_menu.addAction(open_act)

        ws_menu.addSeparator()

        edit_act = QAction(qta.icon("fa5s.edit"), "&Edit workspace…", self)
        edit_act.setShortcut(QKeySequence("Ctrl+E"))
        edit_act.triggered.connect(self.edit_workspace)
        ws_menu.addAction(edit_act)

        save_act = QAction(qta.icon("fa5s.save"), "&Save workspace", self)
        save_act.setShortcut(QKeySequence("Ctrl+S"))
        save_act.triggered.connect(self.save_current_workspace)
        ws_menu.addAction(save_act)

        ws_menu.addSeparator()

        settings_act = QAction(qta.icon("fa5s.cog"), "Directory &settings…", self)
        settings_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        settings_act.triggered.connect(self.open_directory_settings)
        ws_menu.addAction(settings_act)

        ws_menu.addSeparator()

        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(QApplication.quit)
        ws_menu.addAction(quit_act)

        # ---- View menu ----
        view_menu = mb.addMenu("&View")
        self._wire_view_menu(view_menu)

        # ---- Help menu ----
        help_menu = mb.addMenu("&Help")
        doc_act = QAction(qta.icon("fa5s.question-circle"), "&Documentation", self)
        doc_act.setShortcut(QKeySequence("Ctrl+D"))
        doc_act.triggered.connect(self._open_docs)
        help_menu.addAction(doc_act)

        # ---- Toolbar ----
        tb = self.addToolBar("Main")
        tb.setObjectName("toolbar.main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(20, 20))

        # Open workspace button
        open_btn = make_nav_button("fa5s.folder-open", self.open_workspace,
                                   tooltip="Open workspace (Ctrl+O)")
        tb.addWidget(open_btn)

        # Edit + Save stacked pair (half-height)
        pair = QWidget()
        pair_layout = QVBoxLayout(pair)
        pair_layout.setContentsMargins(0, 0, 0, 0)
        pair_layout.setSpacing(0)
        pair_layout.addWidget(
            make_nav_button("fa5s.edit", self.edit_workspace,
                            tooltip="Edit workspace (Ctrl+E)")
        )
        pair_layout.addWidget(
            make_nav_button("fa5s.save", self.save_current_workspace,
                            tooltip="Save workspace (Ctrl+S)")
        )
        tb.addWidget(pair)
        tb.addSeparator()

        # Directory settings
        tb.addWidget(
            make_nav_button("fa5s.cog", self.open_directory_settings,
                            tooltip="Directory settings (Ctrl+Shift+S)")
        )
        tb.addSeparator()

        # Add epoch (placeholder — no callback yet)
        self._add_epoch_btn = make_nav_button(
            "fa5s.plus-circle", lambda: None,
            tooltip="Add epoch (Ctrl+N)"
        )
        self._add_epoch_btn.setEnabled(False)
        tb.addWidget(self._add_epoch_btn)
        tb.addSeparator()

        # Documentation
        tb.addWidget(
            make_nav_button("fa5s.question-circle", self._open_docs,
                            tooltip="Documentation (Ctrl+D)")
        )

    def _wire_view_menu(self, view_menu) -> None:
        """Add per-dock toggle actions and the Layout submenu."""
        # Individual dock visibility toggles
        display_names = {
            _DOCK_WORKSPACE:      "Workspace",
            _DOCK_PREPROCESSING:  "Preprocessing",
            _DOCK_IBI:            "HR Series",
            _DOCK_BP:             "Blood Pressure",
            _DOCK_POINCARE:       "Poincaré",
            _DOCK_EPOCHS:         "Epochs",
            _DOCK_PSD:            "PSD",
            _DOCK_SPECTROGRAM:    "Spectrogram",
            _DOCK_SPECTROGRAM3D:  "Spectrogram 3D",
            _DOCK_TRANSFER:       "Transfer",
            _DOCK_TRANSFERPROFILE:"Transfer Profile",
            _DOCK_PROFILES:       "Profiles",
            _DOCK_PARAMETERS:     "Parameters",
            _DOCK_LOG:            "Log",
        }
        for obj_name, label in display_names.items():
            dock = self._docks.get(obj_name)
            if dock is None:
                continue
            act = dock.toggleViewAction()
            act.setText(label)
            view_menu.addAction(act)

        view_menu.addSeparator()

        self._perspective_menu = PerspectiveMenu(
            self, self._dock_manager, view_menu.addMenu("&Layout")
        )

    # ------------------------------------------------------------------
    # Built-in perspectives
    # ------------------------------------------------------------------

    def _capture_builtin_perspectives(self) -> None:
        """Snapshot the three factory layouts after all docks are placed."""
        self._dock_manager.addPerspective(BUILTIN_DEFAULT)

        # Compare: Epochs dock moves to a bottom split
        epochs = self._docks.get(_DOCK_EPOCHS)
        if epochs:
            self._dock_manager.addDockWidget(
                DockWidgetArea.BottomDockWidgetArea, epochs
            )
        self._dock_manager.addPerspective(BUILTIN_COMPARE)

        # Restore default before PSD Focus snapshot
        self._dock_manager.openPerspective(BUILTIN_DEFAULT)
        self._dock_manager.addPerspective(BUILTIN_PSDFOCUS)

        # Leave the default active
        self._dock_manager.openPerspective(BUILTIN_DEFAULT)

    # ------------------------------------------------------------------
    # Workspace actions
    # ------------------------------------------------------------------

    def open_workspace(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Open workspace",
            str(self._workspace.get("Directories", {}).get("DataDirectory", Path.home())),
            "Workspace (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            self._workspace      = load_workspace(path)
            self._workspace_path = Path(path)
        except Exception as exc:
            QMessageBox.critical(self, "Workspace error", str(exc))
            return
        self._on_workspace_changed()

    def save_current_workspace(self) -> None:
        if self._workspace_path is None:
            self._save_workspace_as()
        else:
            save_workspace(self._workspace, self._workspace_path)

    def _save_workspace_as(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Save workspace", str(Path.home()), "Workspace (*.json)"
        )
        if not path:
            return
        self._workspace_path = Path(path)
        save_workspace(self._workspace, self._workspace_path)

    def edit_workspace(self) -> None:
        """Open the full parameters editor (all workspace sections)."""
        dlg = ParametersEditorDialog(self._workspace, self)
        if dlg.exec():
            self._workspace = dlg.get_parameters(self._workspace)
            self._on_workspace_changed()

    def open_directory_settings(self) -> None:
        """Open the directory-only settings dialog."""
        dirs = dict(self._workspace.get("Directories", {}))
        dlg  = DirectorySelectorDialog(dirs, self)
        if dlg.exec():
            self._workspace.setdefault("Directories", {}).update(
                dlg.get_directories()
            )
            self._on_workspace_changed()

    def _on_workspace_changed(self) -> None:
        """Called after any workspace modification."""
        self._apply_log_level()
        PopulateTree(self._tree, self._workspace)
        # TODO: re-broadcast session with new config when widgets are ready

    def _apply_log_level(self) -> None:
        level = log_level_from_workspace(self._workspace)
        logging.getLogger("spectHR").setLevel(level)

    # ------------------------------------------------------------------
    # File tree
    # ------------------------------------------------------------------

    def _on_file_activated(self, item, _column: int = 0) -> None:
        """Double-click on a file item in the workspace tree."""
        data = item.data(0, Qt.UserRole)
        if not data or data.get("type") != "dataset":
            return
        # TODO: load session and broadcast to docks
        path = data.get("filename", "")
        logger.info(f"File selected: {path}  (loading not yet wired)")

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _open_docs(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(
            QUrl("https://github.com/markspan/spectHR")
        )

    # ------------------------------------------------------------------
    # QSettings persistence
    # ------------------------------------------------------------------

    def _restore_session(self) -> None:
        settings = QSettings(self._ORG, self._APP)
        geometry = settings.value("MainWindow/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        dock_state = settings.value("MainWindow/dockState")
        if dock_state:
            self._dock_manager.restoreState(dock_state)
        ws_path = settings.value("workspace/path")
        if ws_path and Path(str(ws_path)).exists():
            try:
                self._workspace      = load_workspace(ws_path)
                self._workspace_path = Path(str(ws_path))
            except Exception:
                pass
        PopulateTree(self._tree, self._workspace)

    def closeEvent(self, event) -> None:
        settings = QSettings(self._ORG, self._APP)
        settings.setValue("MainWindow/geometry",  self.saveGeometry())
        settings.setValue("MainWindow/dockState", self._dock_manager.saveState())
        if self._workspace_path is not None:
            settings.setValue("workspace/path", str(self._workspace_path))
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
