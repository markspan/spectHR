# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectHR main window, dock-based variant.

Layout is built on PySide6-QtAds. Every former tab is now a CDockWidget
that can be dragged, floated, retabbed or moved to a second monitor.
The menubar, status bar and QActions are constructed directly in
_build_menubar / _wire_view_menu; the older form.ui loader has been
retired.
"""
from __future__ import annotations

import logging
import os
import pickle
import sys
import webbrowser
from pathlib import Path

import numpy as np
import qtawesome as qta
from platformdirs import user_config_path, user_documents_path

# Force Matplotlib to use the Qt backend inside a PySide6 app (macOS-safe).
os.environ.setdefault("MPLBACKEND", "QtAgg")
import matplotlib

matplotlib.use("QtAgg", force=True)

import PySide6QtAds as QtAds
from PySide6.QtCore import QByteArray, QSettings, QSize, Qt
from PySide6.QtGui import QAction, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QStyle,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import spectUI as spQt
from spectHR._version import __version__
from spectHR.DataSet.Epoch import Epoch
from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.Series import CardioSeries
from spectHR.Tools.Logger import logger
from spectUI import perspectives


# QSettings: stored in a per-user INI file rather than the platform
# registry. The path comes from platformdirs so it lands in the
# conventional config location on every OS:
#   Windows: %APPDATA%\spectHR\spectHR.ini
#   Linux  : ~/.config/spectHR/spectHR.ini
#   macOS  : ~/Library/Application Support/spectHR/spectHR.ini
# _ORG_NAME and _APP_NAME are kept around so the legacy registry
# store can be detected and migrated once on startup.
_ORG_NAME             = "spectHR"
_APP_NAME             = "spectHR"
_SETTINGS_GEOMETRY    = "MainWindow/geometry"
_SETTINGS_WINDOWSTATE = "MainWindow/windowState"
_SETTINGS_DOCKSTATE   = "MainWindow/dockState"
_SETTINGS_LAST_PERSP  = "MainWindow/lastPerspective"
_SETTINGS_PERSPS      = "Perspectives"


def _settings_path() -> Path:
    """Absolute path to the INI file, parent dir created on demand."""
    config_dir = Path(user_config_path("spectHR", appauthor=False))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "spectHR.ini"


def _make_settings() -> QSettings:
    """INI-backed QSettings store, the only call site that needs to know
    where the file lives."""
    return QSettings(str(_settings_path()), QSettings.IniFormat)


def _migrate_from_registry_if_needed() -> None:
    """Copy any legacy registry-backed settings into the new INI store.

    Runs once. If the INI already has content the migration is
    skipped, so a user who deletes the INI deliberately is not
    silently re-populated from the registry. The legacy registry
    keys are left in place, deleting them is something a user can
    do manually with regedit once they have confirmed the INI works
    for them.
    """
    target = _settings_path()
    try:
        if target.exists() and target.stat().st_size > 0:
            return
    except OSError:
        return
    legacy = QSettings(_ORG_NAME, _APP_NAME)
    keys = legacy.allKeys()
    if not keys:
        return
    fresh = _make_settings()
    for key in keys:
        fresh.setValue(key, legacy.value(key))
    fresh.sync()
    logger.info(
        "Migrated %d setting(s) from registry to %s", len(keys), target,
    )

# Dock objectName strings. CDockManager.saveState keys the saved layout
# by objectName, so these are on-disk contract: do not change once shipped.
_DOCK_TREE          = "dock.workspace"
_DOCK_PREPROCESSING = "dock.preprocessing"
_DOCK_IBI           = "dock.ibi"
_DOCK_POINCARE      = "dock.poincare"
_DOCK_EPOCHS        = "dock.epochs"
_DOCK_PSD               = "dock.psd"
_DOCK_SPECTROGRAM       = "dock.spectrogram"
_DOCK_TRANSFER          = "dock.transfer"
_DOCK_TRANSFER_PROFILE  = "dock.transferprofile"
_DOCK_PROFILES          = "dock.profiles"
_DOCK_PARAMETERS    = "dock.parameters"
_DOCK_LOG           = "dock.log"


class _QtLogHandler(logging.Handler):
    """Logging handler that appends records to a QPlainTextEdit widget."""

    def __init__(self, widget: QPlainTextEdit):
        super().__init__()
        self._widget = widget
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record):
        try:
            msg = self.format(record)
            self._widget.appendPlainText(msg)
            # Keep the view scrolled to the latest entry.
            self._widget.moveCursor(QTextCursor.End)
        except Exception:
            self.handleError(record)


class MainWindow(QMainWindow):
    """
    Main application window for the spectHR HRV analyser.

    Workspace dict chapters,

        workspace["Directories"]       , DataDirectory, CacheDirectory, OutputDirectory.
        workspace["FrequencyAnalysis"] , HRV frequency band configuration.
        workspace["CardioParameters"]  , IBI classification and ECG preprocessing.

    Layout is a tabified central dock group with the workspace tree on
    the left and the log dock at the bottom (hidden by default). Last
    layout and named perspectives persist via QSettings.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self):
        super().__init__()
        logging.getLogger("matplotlib.font_manager").disabled = True

        # Touching statusBar() once forces QMainWindow to create one,
        # so QAction.setStatusTip messages have somewhere to land.
        self.statusBar()

        self.setWindowTitle(f"spectHR (v{__version__}) - ECG / HRV Analysis")
        self.resize(1920, 1080)

        # ---- application state --------------------------------------
        self.dataset: PhysioData | None = None
        self.savename: Path | None = None

        # Refresh registry, dock objectName -> refresh fn.
        self._refresh_fns: dict[str, callable] = {}

        # ---- workspace ----------------------------------------------
        self.workspace_file = user_documents_path() / "DefaultWorkSpace.json"
        self.workspace = spQt.LoadWorkspace(self.workspace_file)

        # ---- dock layout --------------------------------------------
        # CDockManager installs itself as the QMainWindow central widget.
        QtAds.CDockManager.setConfigFlag(
            QtAds.CDockManager.OpaqueSplitterResize, True,
        )
        QtAds.CDockManager.setConfigFlag(
            QtAds.CDockManager.XmlCompressionEnabled, False,
        )
        self.dock_manager = QtAds.CDockManager(self)

        self._build_docks()
        self._build_menubar()
        self._wire_view_menu()

        # Capture built-in perspectives before any saved user state is
        # restored, so the user always has a way back from a bad drag.
        self._capture_builtin_perspectives()

        # Restore last session. Must follow _build_docks() so the dock
        # objectNames it keys on are already registered.
        self._restore_session()

        # Tree population fires selectionChanged, which expects every
        # dock to already exist, so do it last.
        spQt.PopulateTree(self.tree_widget, self.workspace)

    # ------------------------------------------------------------------
    # Dock construction
    # ------------------------------------------------------------------

    def _build_docks(self) -> None:
        """
        Create every CDockWidget and place it in the dock manager.

        Default layout, workspace tree left, seven analysis views
        tabified centre, log bottom and hidden.
        """
        # ---- workspace tree dock ------------------------------------
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabel("Workspace")
        self.tree_widget.setRootIsDecorated(True)
        self.tree_widget.setAnimated(True)
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.show_context_menu)
        self.tree_widget.itemSelectionChanged.connect(self.on_file_selection)

        tree_dock = self._make_dock(_DOCK_TREE, "Workspace", self.tree_widget)
        self.dock_manager.addDockWidget(QtAds.LeftDockWidgetArea, tree_dock)
        self.tree_dock = tree_dock

        # ---- analysis plot widgets ----------------------------------
        self.prep_plot_widget       = spQt.PrepPlotWidget()
        self.hr_plot_widget         = spQt.HRPlotWidget()
        self.poincare_plot_widget   = spQt.PoincarePlotWidget()
        self.epoch_plot_widget      = spQt.EpochPlotWidget()
        self.parameters_plot_widget = spQt.ParametersPlotWidget()

        # PSD / Profiles live in their own scroll area. The inner plot
        # widget is rebuilt on every refresh, so we hold the layout,
        # not the widget.
        self.psd_scroll,        self.psd_layout        = self._make_scrollable_host()
        self.spectrogram_scroll,      self.spectrogram_layout      = self._make_scrollable_host()
        self.transfer_scroll,         self.transfer_layout         = self._make_scrollable_host()
        self.transfer_profile_scroll, self.transfer_profile_layout = self._make_scrollable_host()
        self.profile_scroll,          self.profile_layout          = self._make_scrollable_host()

        # ---- log dock content ---------------------------------------
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        font = QFont("Courier New", 9)
        self.log_view.setFont(font)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        # Route all spectHR log output to the Log dock as well as the console.
        self._log_handler = _QtLogHandler(self.log_view)
        logging.getLogger("spectHR").addHandler(self._log_handler)

        # ---- centre tab group ---------------------------------------
        # First dock seeds the centre area, the rest are tabified into it.
        prep_dock = self._make_dock(
            _DOCK_PREPROCESSING, "Preprocessing", self.prep_plot_widget,
        )
        first_area = self.dock_manager.addDockWidget(
            QtAds.CenterDockWidgetArea, prep_dock,
        )

        def _tab(name: str, title: str, widget: QWidget) -> QtAds.CDockWidget:
            dock = self._make_dock(name, title, widget)
            self.dock_manager.addDockWidget(
                QtAds.CenterDockWidgetArea, dock, first_area,
            )
            return dock

        ibi_dock         = _tab(_DOCK_IBI,         "IBI Series",  self.hr_plot_widget)
        poincare_dock    = _tab(_DOCK_POINCARE,    "Poincare",    self.poincare_plot_widget)
        epochs_dock      = _tab(_DOCK_EPOCHS,      "Epochs",      self.epoch_plot_widget)
        psd_dock         = _tab(_DOCK_PSD,         "PSD",         self.psd_scroll)
        spectrogram_dock      = _tab(_DOCK_SPECTROGRAM,      "Spectrogram",      self.spectrogram_scroll)
        transfer_dock         = _tab(_DOCK_TRANSFER,         "Transfer",         self.transfer_scroll)
        transfer_profile_dock = _tab(_DOCK_TRANSFER_PROFILE, "Transfer profile", self.transfer_profile_scroll)
        profiles_dock         = _tab(_DOCK_PROFILES,         "Profiles",         self.profile_scroll)
        params_dock      = _tab(_DOCK_PARAMETERS,  "Parameters",  self.parameters_plot_widget)

        # ---- log dock -----------------------------------------------
        log_dock = self._make_dock(_DOCK_LOG, "Log", self.log_view)
        self.dock_manager.addDockWidget(QtAds.BottomDockWidgetArea, log_dock)
        log_dock.toggleView(False)  # hidden by default

        self.docks: dict[str, QtAds.CDockWidget] = {
            _DOCK_TREE:             tree_dock,
            _DOCK_PREPROCESSING:    prep_dock,
            _DOCK_IBI:              ibi_dock,
            _DOCK_POINCARE:         poincare_dock,
            _DOCK_EPOCHS:           epochs_dock,
            _DOCK_PSD:              psd_dock,
            _DOCK_SPECTROGRAM:      spectrogram_dock,
            _DOCK_TRANSFER:         transfer_dock,
            _DOCK_TRANSFER_PROFILE: transfer_profile_dock,
            _DOCK_PROFILES:         profiles_dock,
            _DOCK_PARAMETERS:       params_dock,
            _DOCK_LOG:              log_dock,
        }

        # ---- refresh wiring -----------------------------------------
        # Each content dock owns a refresh fn fired on visibilityChanged.
        # Replaces the old on_tab_changed index dispatch, and refreshes
        # unconditionally so peak edits, epoch toggles and parameter
        # changes always show up next time the dock is brought forward.
        self._refresh_fns = {
            _DOCK_PREPROCESSING:    self._refresh_preprocessing,
            _DOCK_IBI:              self._refresh_ibi,
            _DOCK_POINCARE:         self._refresh_poincare,
            _DOCK_EPOCHS:           self._refresh_epochs,
            _DOCK_PSD:              self._refresh_psd,
            _DOCK_SPECTROGRAM:      self._refresh_spectrogram,
            _DOCK_TRANSFER:         self._refresh_transfer,
            _DOCK_TRANSFER_PROFILE: self._refresh_transfer_profile,
            _DOCK_PROFILES:         self._refresh_profile,
            _DOCK_PARAMETERS:       self._refresh_parameters,
        }

        for name, refresh_fn in self._refresh_fns.items():
            dock = self.docks[name]
            # Capture name by default-arg, otherwise the closure binds
            # the loop variable and every dock would route to the last.
            dock.visibilityChanged.connect(
                lambda visible, n=name: self._on_dock_visible(n, visible),
            )

    def _make_dock(
        self,
        object_name: str,
        title: str,
        widget: QWidget,
    ) -> QtAds.CDockWidget:
        """Create a CDockWidget with stable object name and embedded widget.

        Uses the dock-manager-aware constructor introduced in QtAds 4.x;
        the bare ``CDockWidget(title)`` form was deprecated upstream.
        """
        dock = QtAds.CDockWidget(self.dock_manager, title)
        dock.setObjectName(object_name)
        dock.setWidget(widget)
        return dock

    def _make_scrollable_host(self) -> tuple[QScrollArea, QVBoxLayout]:
        """
        Build the scroll-area + content-widget pair used by PSD and Profile.

        Returns the inner layout too, the refresh helpers swap the plot
        widget on every call so they need direct addWidget / takeAt
        access against the same layout shape the old .ui forms had.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout()
        content.setLayout(layout)
        scroll.setWidget(content)
        return scroll, layout

    # ------------------------------------------------------------------
    # Menu and action wiring
    # ------------------------------------------------------------------

    def _build_menubar(self) -> None:
        """
        Build the WorkSpace, Edits and Help menus and their actions,
        and a matching icon+text toolbar.

        Each action is created once and reused by both surfaces, so the
        toolbar buttons and the menu entries fire the same slot and the
        keyboard shortcut belongs to a single QAction.

        The View menu is added in :meth:`_wire_view_menu`, slotted just
        before Help via :attr:`_help_menu` so the established WorkSpace,
        Edits, View, Help order is preserved. View intentionally has no
        toolbar mirror, the dock toggle actions already live in the View
        menu and the docks themselves carry tab strips.
        """
        # ---- WorkSpace menu actions ----------------------------------
        # Material Design Icons (mdi6) for the sharper, more angular
        # silhouette. FontAwesome Sharp is a Pro family and is not in
        # qtawesome's bundled fonts; mdi6 is the closest free analogue.
        act_open = QAction(qta.icon("mdi6.folder-open"), "Open Workspace", self)
        act_open.setShortcut("Ctrl+O")
        act_open.setStatusTip("Open a workspace file")
        act_open.setToolTip("Open a workspace file")
        act_open.triggered.connect(self.OpenWorkSpace)

        act_edit_ws = QAction(qta.icon("mdi6.file-tree"), "Edit Workspace", self)
        act_edit_ws.setShortcut("Ctrl+E")
        act_edit_ws.setStatusTip("Edit workspace directories")
        act_edit_ws.setToolTip("Edit workspace directories")
        act_edit_ws.triggered.connect(self.EditWorkSpace)

        act_save_ws = QAction(qta.icon("mdi6.content-save"), "Save Workspace", self)
        act_save_ws.setShortcut("Ctrl+S")
        act_save_ws.setStatusTip("Save the current workspace")
        act_save_ws.setToolTip("Save the current workspace")
        act_save_ws.triggered.connect(self.SaveWorkSpace)

        act_settings = QAction(qta.icon("mdi6.cog"), "Settings", self)
        act_settings.setShortcut("Ctrl+Shift+S")
        act_settings.setStatusTip("Edit parameters")
        act_settings.setToolTip("Edit parameters")
        act_settings.triggered.connect(self.EditParameters)

        # ---- Edits menu actions --------------------------------------
        act_add_epoch = QAction(qta.icon("mdi6.plus"), "Add Epoch", self)
        act_add_epoch.setShortcut("Ctrl+N")
        act_add_epoch.setStatusTip("Add a new epoch spanning the full recording")
        act_add_epoch.setToolTip("Add a new epoch spanning the full recording")
        act_add_epoch.triggered.connect(self.add_epoch)

        # ---- Help menu actions ---------------------------------------
        act_docs = QAction(qta.icon("mdi6.book-open-page-variant"), "Documentation", self)
        act_docs.setShortcut("Ctrl+D")
        act_docs.setStatusTip("Open the spectHR documentation")
        act_docs.setToolTip("Open the spectHR documentation")
        act_docs.triggered.connect(
            lambda: webbrowser.open(
                "https://github.com/markspan/spectHR/blob/V2/readme.MD"
            )
        )

        # ---- assemble menubar ----------------------------------------
        menubar = self.menuBar()

        ws_menu = menubar.addMenu("WorkSpace")
        ws_menu.addAction(act_open)
        ws_menu.addSeparator()
        ws_menu.addAction(act_edit_ws)
        ws_menu.addAction(act_save_ws)
        ws_menu.addSeparator()
        ws_menu.addAction(act_settings)

        edits_menu = menubar.addMenu("Edits")
        edits_menu.addAction(act_add_epoch)

        # Help anchors the right end of the strip; _wire_view_menu
        # uses self._help_menu as the insertion point for View.
        self._help_menu = menubar.addMenu("Help")
        self._help_menu.addAction(act_docs)

        # ---- assemble toolbar ---------------------------------------
        # Icon+text style, grouped to mirror the menubar layout. The
        # objectName is on the QSettings on-disk contract because
        # QMainWindow.saveState includes toolbar positions, do not
        # change once shipped.
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("toolbar.main")
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        # 2.0x the platform-default toolbar metric, rounded. Using
        # PM_ToolBarIconSize keeps the bump proportional across
        # platforms instead of pinning a hard pixel count. The enum
        # lives on the QStyle class in PySide6, not on style instances.
        base = self.style().pixelMetric(QStyle.PixelMetric.PM_ToolBarIconSize)
        bumped = max(int(round(base * 2.0)), base + 1)
        toolbar.setIconSize(QSize(bumped, bumped))
        toolbar.addAction(act_open)
        toolbar.addAction(act_edit_ws)
        toolbar.addAction(act_save_ws)
        toolbar.addSeparator()
        toolbar.addAction(act_settings)
        toolbar.addSeparator()
        toolbar.addAction(act_add_epoch)
        toolbar.addSeparator()
        toolbar.addAction(act_docs)
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        self._main_toolbar = toolbar

    def _wire_view_menu(self) -> None:
        """
        Build the View menu at runtime.

        One toggle action per dock, plus a Layout submenu for
        perspectives. Inserted just before Help so the established
        WorkSpace, Edits, View, Help order reads naturally.
        """
        menubar = self.menuBar()
        view_menu = QMenu("View", self)
        menubar.insertMenu(self._help_menu.menuAction(), view_menu)
        self.view_menu = view_menu

        for name in (
            _DOCK_TREE,
            _DOCK_PREPROCESSING,
            _DOCK_IBI,
            _DOCK_POINCARE,
            _DOCK_EPOCHS,
            _DOCK_PSD,
            _DOCK_SPECTROGRAM,
            _DOCK_TRANSFER,
            _DOCK_TRANSFER_PROFILE,
            _DOCK_PROFILES,
            _DOCK_PARAMETERS,
            _DOCK_LOG,
        ):
            view_menu.addAction(self.docks[name].toggleViewAction())

        view_menu.addSeparator()

        layout_menu = view_menu.addMenu("Layout")
        self.perspective_menu = perspectives.PerspectiveMenu(
            self, self.dock_manager, layout_menu,
        )

    # ------------------------------------------------------------------
    # Perspective and session-state plumbing
    # ------------------------------------------------------------------

    def _capture_builtin_perspectives(self) -> None:
        """
        Snapshot the built-in named perspectives.

        Default is the post-construction layout. Compare splits Epochs
        and Poincare under the centre area for artefact QC. PSD focus
        floats the PSD dock so it can live on a second monitor. All
        three are captured against the fresh layout, before any saved
        user state is restored, so they always resolve to something
        sensible.
        """
        # Default ---------------------------------------------------------
        self.dock_manager.addPerspective(perspectives.BUILTIN_DEFAULT)

        # Compare ---------------------------------------------------------
        # Move Epochs out into a vertical split under the centre area,
        # add Poincare alongside it as a tab.
        epochs_dock = self.docks[_DOCK_EPOCHS]
        poincare_dock = self.docks[_DOCK_POINCARE]
        if not epochs_dock.isFloating():
            self.dock_manager.addDockWidget(
                QtAds.BottomDockWidgetArea,
                epochs_dock,
                self.docks[_DOCK_PREPROCESSING].dockAreaWidget(),
            )
        if not poincare_dock.isFloating():
            self.dock_manager.addDockWidgetTab(
                QtAds.CenterDockWidgetArea, poincare_dock
            )
        self.dock_manager.addPerspective(perspectives.BUILTIN_COMPARE)

        # Reset before capturing PSD focus so the perspectives compose
        # rather than stack.
        self.dock_manager.openPerspective(perspectives.BUILTIN_DEFAULT)

        # PSD focus -------------------------------------------------------
        psd_dock = self.docks[_DOCK_PSD]
        if not psd_dock.isFloating():
            psd_dock.setFloating()
        self.dock_manager.addPerspective(perspectives.BUILTIN_PSDFOCUS)

        # Back to default as the displayed layout.
        self.dock_manager.openPerspective(perspectives.BUILTIN_DEFAULT)

    def _restore_session(self) -> None:
        """
        Restore window geometry and dock layout from the INI store.

        Two passes, user-saved perspectives first (loadPerspectives),
        then the last-active dock state (restoreState). With no saved
        state the default captured in _capture_builtin_perspectives
        stands.

        Runs the one-shot registry-to-INI migration first so a user
        upgrading from a registry-backed build keeps their saved
        layout and perspectives.
        """
        _migrate_from_registry_if_needed()
        settings = _make_settings()

        # Named perspectives ------------------------------------------
        settings.beginGroup(_SETTINGS_PERSPS)
        try:
            self.dock_manager.loadPerspectives(settings)
        finally:
            settings.endGroup()
        # Newly loaded perspectives change the menu contents.
        self.perspective_menu.rebuild()

        # Window chrome -----------------------------------------------
        geom = settings.value(_SETTINGS_GEOMETRY)
        if isinstance(geom, QByteArray) and not geom.isEmpty():
            self.restoreGeometry(geom)
        win_state = settings.value(_SETTINGS_WINDOWSTATE)
        if isinstance(win_state, QByteArray) and not win_state.isEmpty():
            self.restoreState(win_state)

        # Dock layout -------------------------------------------------
        dock_state = settings.value(_SETTINGS_DOCKSTATE)
        if isinstance(dock_state, QByteArray) and not dock_state.isEmpty():
            self.dock_manager.restoreState(dock_state)
        else:
            # First-run, leave the default tabified layout in place.
            pass

    def closeEvent(self, event) -> None:
        """Persist current geometry, window state and dock layout on close."""
        # Re-dock every floating panel before saving state.  Floating dock
        # containers are independent top-level windows; if we save state while
        # they are still floating the INI records them that way, and on the next
        # launch ADS tries to recreate the floating windows, but the C++ objects
        # are gone, causing a RuntimeError in visibilityChanged callbacks.
        # Re-docking first means the saved state is always fully embedded, so
        # restart is clean regardless of what the user left floating.
        for dock in self.docks.values():
            try:
                if dock.isFloating():
                    self.dock_manager.addDockWidget(
                        QtAds.CenterDockWidgetArea, dock
                    )
            except RuntimeError:
                pass

        settings = _make_settings()

        # Named perspectives (writes one subkey per perspective name).
        settings.beginGroup(_SETTINGS_PERSPS)
        try:
            self.dock_manager.savePerspectives(settings)
        finally:
            settings.endGroup()

        settings.setValue(_SETTINGS_GEOMETRY,    self.saveGeometry())
        settings.setValue(_SETTINGS_WINDOWSTATE, self.saveState())
        settings.setValue(_SETTINGS_DOCKSTATE,   self.dock_manager.saveState())

        self.dock_manager.deleteLater()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Per-dock visibilityChanged dispatch
    # ------------------------------------------------------------------

    def _on_dock_visible(self, name: str, visible: bool) -> None:
        """
        Refresh the dock whenever it is brought forward.

        Matches the old QTabWidget.currentChanged behaviour, persist the
        dataset, then recompute the plot. Always recompute (no dirty
        flag), so peak edits, epoch toggles, parameter tweaks and any
        other side-effects of working in another dock always appear.

        Floating content docks are refreshed too. A floating dock
        stays visible regardless of which tab is active in the main
        window, so its own visibilityChanged signal never fires on a
        centre-tab switch. Without this they go stale after edits
        made in other docks (epoch resizing, peak edits, parameter
        changes).
        """
        if not visible:
            return
        if self.dataset is None:
            return
        refresh_fn = self._refresh_fns.get(name)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # Persist current state before recomputing, the old
            # on_tab_changed did the same on every tab switch.
            if self.savename is not None:
                self.dataset.save(self.savename)
            if refresh_fn is not None:
                refresh_fn()
            # Floating content docks piggy-back on every visibility
            # change so they catch mutations done elsewhere.
            for other_name, dock in self.docks.items():
                if other_name == name:
                    continue
                other_fn = self._refresh_fns.get(other_name)
                if other_fn is None:
                    continue
                if dock.isClosed() or not dock.isFloating():
                    continue
                other_fn()
        finally:
            QApplication.restoreOverrideCursor()

    def _refresh_preprocessing(self) -> None:
        self.show_preprocessing_plot(self.dataset)

    def _refresh_ibi(self) -> None:
        self.show_hr_plot(self.dataset)

    def _refresh_poincare(self) -> None:
        self.show_poincare_plot(self.dataset)

    def _refresh_epochs(self) -> None:
        self.show_epoch_plot(self.dataset)

    def _refresh_psd(self) -> None:
        self.show_psd_plot(self.dataset)

    def _refresh_spectrogram(self) -> None:
        self.show_spectrogram_plot(self.dataset)

    def _refresh_transfer(self) -> None:
        self.show_transfer_plot(self.dataset)

    def _refresh_transfer_profile(self) -> None:
        self.show_transfer_profile_plot(self.dataset)

    def _refresh_profile(self) -> None:
        self.show_profile_plot(self.dataset)

    def _refresh_parameters(self) -> None:
        self.show_parameters_plot(self.dataset)

    # ------------------------------------------------------------------
    # Workspace menu actions
    # ------------------------------------------------------------------

    def OpenWorkSpace(self):
        """Open a JSON workspace file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select a file", "", "workspace Files (*.json);;Text Files (*.txt)"
        )
        if file_path:
            self.workspace_file = file_path
            self.workspace = spQt.LoadWorkspace(file_path)
            spQt.PopulateTree(self.tree_widget, self.workspace)

    def SaveWorkSpace(self):
        """Save the current workspace to a JSON file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Select a file", "", "workspace Files (*.json);;Text Files (*.txt)"
        )
        if file_path:
            try:
                spQt.SaveWorkspace(self.workspace, file_path)
            except Exception as e:
                logger.warning(f"Could not save workspace: {e}")

    def EditWorkSpace(self):
        """Edit the Directories section of the workspace."""
        dialog = spQt.DirectorySelectorDialog(self.workspace["Directories"])
        if dialog.exec_() == QInputDialog.Accepted:
            self.workspace["Directories"] = dialog.get_directories()
            spQt.PopulateTree(self.tree_widget, self.workspace)

    def EditParameters(self):
        """
        Edit all non-directory parameters in the workspace via a dynamic form.

        On OK,

        1. The updated values are written back into self.workspace.
        2. The workspace JSON file is saved immediately so the changes persist.
        3. The PSD and Profile docks are refreshed if a dataset is loaded,
           the other docks are marked dirty so they refresh on next show.
        """
        dialog = spQt.ParametersEditorDialog(self.workspace, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            self.workspace = dialog.get_parameters(self.workspace)

            try:
                spQt.SaveWorkspace(self.workspace, self.workspace_file)
            except Exception as e:
                logger.warning(f"Could not save workspace after parameter edit: {e}")

            if self.dataset is not None:
                # PSD, Spectrogram, Transfer (+ profile), and Profiles
                # depend directly on what was edited (bands, window,
                # step, PSD method, coherence threshold, etc.), refresh
                # them now. Other docks recompute on next show.
                self.show_psd_plot(self.dataset)
                self.show_spectrogram_plot(self.dataset)
                self.show_transfer_plot(self.dataset)
                self.show_transfer_profile_plot(self.dataset)
                self.show_profile_plot(self.dataset)

    # ------------------------------------------------------------------
    # Workspace tree context menu
    # ------------------------------------------------------------------

    def show_context_menu(self, position):
        item = self.tree_widget.itemAt(position)
        if not item:
            return
        if (
            not item.text(0).lower().endswith(".xdf")
            and not item.text(0).lower().endswith(".txt")
            and not item.text(0).lower().endswith(".evt")
        ):
            return

        context_menu = QMenu(self)
        reload_action    = QAction("Reload Raw", self)
        invert_action    = QAction("Invert ECG Polarity", self)
        retrigger_action = QAction("Retrigger ECG", self)

        reload_action.triggered.connect(lambda: self.reload(item))
        invert_action.triggered.connect(self.invert)
        retrigger_action.triggered.connect(self.retrigger)

        context_menu.addAction(reload_action)
        context_menu.addAction(invert_action)
        context_menu.addAction(retrigger_action)
        context_menu.exec_(self.tree_widget.viewport().mapToGlobal(position))

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def retrigger(
        self, *, min_peak_distance_ms: float = 300.0, classify: bool = True
    ) -> None:
        """Retrigger R-peak detection on the current dataset."""
        if self.dataset is None:
            return
        if self.dataset.active_band is None:
            raise RuntimeError("No active band selected")

        QApplication.setOverrideCursor(Qt.WaitCursor)
        ecg_accessor = self.dataset["ecg"]
        ecg_ts = ecg_accessor.timeseries
        cs = CardioSeries.from_timeseries(
            ecg_ts,
            min_peak_distance_ms=min_peak_distance_ms,
            classify=False,
        )

        cs.times = np.array([np.nan])
        cs.labels = np.array(["TL"])
        cs._pd = self.dataset
        cs._stream = ecg_accessor
        self.dataset.hrv_map[self.dataset.active_band] = cs

        for key, epoch in self.dataset.epochs.items():
            if not epoch.active:
                continue
            ecg_view = ecg_ts.view(epoch.start, epoch.end)
            cs.replace_from_timeseries(
                ecg_view,
                start=epoch.start,
                end=epoch.end,
                min_peak_distance_ms=min_peak_distance_ms,
                classify=False,
            )

        if classify:
            cs.classify_ibi()

        QApplication.restoreOverrideCursor()
        self.dataset.save(self.savename)
        self.show_preprocessing_plot(self.dataset)

    def reload(self, item):
        """Discard cache and reload from raw file."""
        self.dataset.save(self.savename)
        backup = (
            Path(self.workspace["Directories"]["CacheDirectory"]) / "LASTDELETED.pkl"
        )
        os.replace(self.savename, backup)
        self.on_file_selection()

    def invert(self):
        """Invert ECG polarity and reprocess."""
        if self.dataset is None:
            return
        self.dataset["ecg"].timeseries.flip()
        self.dataset.preprocess_ecg(
            respiration_per_epoch=self._respiration_per_epoch(),
        )
        self.dataset.save(self.savename)
        self.show_preprocessing_plot(self.dataset)

    def _respiration_per_epoch(self) -> bool:
        """Read the ``RespirationAnalysis.per_epoch`` flag from the workspace.

        Centralised here so the three ``preprocess_ecg`` call sites stay
        in sync as more respiration-analysis knobs get added.
        """
        ra = (self.workspace or {}).get("RespirationAnalysis", {}) or {}
        return bool(ra.get("per_epoch", False))

    # ------------------------------------------------------------------
    # File selection
    # ------------------------------------------------------------------

    def on_file_selection(self):
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        meta = item.data(0, Qt.UserRole)
        if meta is None:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        dirs = self.workspace["Directories"]

        # CASE 1, dataset root node ------------------------------------
        if meta.get("type") == "dataset":
            filename = meta["filename"]
            self.savename = Path(dirs["CacheDirectory"]) / (
                Path(filename).stem + ".pkl"
            )

            if Path(self.savename).exists():
                with open(self.savename, "rb") as f:
                    dataset = pickle.load(f)
                if not dataset.hrv_map or dataset.active_band is None:
                    if getattr(dataset, "has_ecg", False):
                        dataset.preprocess_ecg(
                            respiration_per_epoch=self._respiration_per_epoch(),
                        )
                    if dataset.active_band is None and dataset.band_map:
                        dataset.active_band = next(iter(dataset.band_map))
                    dataset.save(self.savename)
                else:
                    _resaved = False

                    # ------------------------------------------------------
                    # Migration 1, locked R-tops saved without IBI classification
                    # ------------------------------------------------------
                    # Cached datasets saved before the locked-branch
                    # classify_ibi() fix have all R-top labels at the
                    # default "N", an impossible result for real ECG of
                    # any length. Re-classify in place, no ECG re-filtering
                    # needed.
                    for _cs in dataset.hrv_map.values():
                        if (
                            getattr(_cs, "rtops_locked", False)
                            and _cs.times.size > 1
                            and all(_lbl == "N" for _lbl in _cs.labels)
                        ):
                            logger.info(
                                "Migration 1: classifying locked R-tops that were "
                                "saved without IBI classification."
                            )
                            _cs.classify_ibi()
                            _resaved = True

                    # ------------------------------------------------------
                    # Migration 2, CARSPAN epoch-start convention
                    # ------------------------------------------------------
                    # Cached datasets saved before the epoch-start fix have
                    # epoch starts equal to the EVT marker time
                    # (e.g. 313.900 s) instead of the last R-peak before
                    # the marker (e.g. 313.096 s).
                    #
                    # Detection, if any non-experiment epoch's start time
                    # matches a "Start Epoch #N" time in the TaskSeries
                    # EventSeries, the old convention is still in use.
                    if "TaskSeries" in dataset.events:
                        _task_ev = dataset.events["TaskSeries"]
                        _start_marker_times = {
                            float(t)
                            for t, lbl in zip(_task_ev.times, _task_ev.labels)
                            if str(lbl).lower().startswith("start ")
                        }
                        _old_convention = any(
                            abs(_ep.start - _smt) < 0.001
                            for _epoch_name, _ep in dataset.epochs.items()
                            if _epoch_name != "experiment"
                            for _smt in _start_marker_times
                        )
                        if _old_convention:
                            logger.info(
                                "Migration 2: updating CARSPAN epoch starts to last "
                                "R-peak before each start marker."
                            )
                            for _cs in dataset.hrv_map.values():
                                for _epoch_name, _ep in dataset.epochs.items():
                                    if _epoch_name == "experiment":
                                        continue
                                    if any(
                                        abs(_ep.start - _smt) < 0.001
                                        for _smt in _start_marker_times
                                    ):
                                        _preceding = _cs.times[_cs.times < _ep.start]
                                        if _preceding.size > 0:
                                            _ep.start = float(_preceding[-1])
                            _resaved = True

                    if _resaved:
                        dataset.save(self.savename)
            else:
                dataset = PhysioData(Path(dirs["DataDirectory"]) / Path(filename))
                if dataset.has_ecg:
                    dataset.preprocess_ecg(
                        respiration_per_epoch=self._respiration_per_epoch(),
                    )
                if dataset.active_band is None:
                    dataset.active_band = next(iter(dataset.band_map))
                dataset.save(self.savename)

            band_ids = sorted(
                {
                    name.split("[")[-1][:-1]
                    for name in dataset.timeseries
                    if "[" in name and "]" in name
                }
            )
            if len(band_ids) > 1:
                if not meta.get("bands_expanded", False):
                    item.takeChildren()
                    for band in band_ids:
                        child = QTreeWidgetItem(item, [f"Band {band}"])
                        child.setData(
                            0,
                            Qt.UserRole,
                            {
                                "type": "band",
                                "band_id": band,
                                "filename": filename,
                            },
                        )
                    meta["bands_expanded"] = True
                    item.setData(0, Qt.UserRole, meta)
                    item.setExpanded(True)
                    QApplication.restoreOverrideCursor()
                    return

            self.dataset = dataset
            self._on_dataset_loaded()
            QApplication.restoreOverrideCursor()
            return

        # CASE 2, band node -------------------------------------------
        if meta.get("type") == "band":
            filename = meta["filename"]
            band_id = meta["band_id"]
            self.savename = Path(dirs["CacheDirectory"]) / (
                Path(filename).stem + ".pkl"
            )
            if self.savename.exists():
                with open(self.savename, "rb") as f:
                    dataset = pickle.load(f)
                dataset.active_band = band_id
            else:
                dataset = spQt.PreProcessFile(self.workspace, filename)
                dataset.active_band = band_id
                dataset.save(self.savename)

            self.dataset = dataset
            self._on_dataset_loaded()
            QApplication.restoreOverrideCursor()

    def _on_dataset_loaded(self) -> None:
        """
        Hook fired once a dataset is in self.dataset.

        Eagerly refresh every content dock, matching the original
        on_file_selection. Subsequent dock switches refresh on their
        own via _on_dock_visible.

        Docks whose underlying data isn't available on this dataset are
        closed (Preprocessing without ECG, Transfer + Transfer-profile
        without a respiration channel). The View-menu entry stays
        enabled so the user can re-open them - on re-open the widget
        renders its own "No respiration channel" placeholder.
        """
        # Preprocessing dock visibility follows ECG availability.
        has_ecg = bool(getattr(self.dataset, "has_ecg", False))
        self.docks[_DOCK_PREPROCESSING].toggleView(has_ecg)

        # Transfer-family docks follow respiration availability. When
        # the recording has no respiration channel we close them, grey
        # out their View-menu toggle, and arm a visibility-guard that
        # explains via QMessageBox if anything else (perspective
        # restore, programmatic call) tries to open them.
        rsp_map = getattr(self.dataset, "rsp_map", None) or {}
        has_rsp = bool(rsp_map)
        for name in (_DOCK_TRANSFER, _DOCK_TRANSFER_PROFILE):
            dock = self.docks[name]
            dock.toggleView(has_rsp and not dock.isClosed())
            action = dock.toggleViewAction()
            action.setEnabled(has_rsp)
            if not has_rsp:
                action.setToolTip(
                    "Disabled: this recording has no respiration channel"
                )
            else:
                action.setToolTip("")
        if not has_rsp:
            self._arm_transfer_rsp_guard()
        else:
            self._disarm_transfer_rsp_guard()

        skip_when_missing = {
            _DOCK_PREPROCESSING:    not has_ecg,
            _DOCK_TRANSFER:         not has_rsp,
            _DOCK_TRANSFER_PROFILE: not has_rsp,
        }
        for name, refresh_fn in self._refresh_fns.items():
            # Skip refresh on docks whose data isn't on this dataset.
            # The dock is already hidden; the placeholder will render
            # only if/when the user toggles it back on.
            if skip_when_missing.get(name, False):
                continue
            refresh_fn()

    def _arm_transfer_rsp_guard(self) -> None:
        """Install one-shot visibility guards on the Transfer docks.

        Triggered from _on_dataset_loaded when the loaded recording has
        no respiration channel. If anything makes either dock visible
        afterwards (perspective restore, programmatic call), the guard
        closes it again and pops an explanatory QMessageBox.
        """
        for name in (_DOCK_TRANSFER, _DOCK_TRANSFER_PROFILE):
            dock = self.docks[name]
            slot = getattr(self, f"_rsp_guard_{name}", None)
            if slot is not None:
                # Already armed for this dock, don't duplicate.
                continue

            def make_slot(_dock=dock, _name=name):
                def _slot(visible: bool) -> None:
                    if not visible:
                        return
                    # Force closed and explain. Block signals briefly so
                    # toggleView(False) doesn't bounce through here.
                    _dock.blockSignals(True)
                    try:
                        _dock.toggleView(False)
                    finally:
                        _dock.blockSignals(False)
                    QMessageBox.warning(
                        self,
                        "Transfer analysis unavailable",
                        "Cannot open the Transfer view.\n\n"
                        "This analysis estimates how the breathing signal "
                        "drives heart-rate variability, so it needs a "
                        "respiration channel in the recording. The "
                        "currently loaded file has none.",
                    )
                return _slot

            slot = make_slot()
            dock.visibilityChanged.connect(slot)
            setattr(self, f"_rsp_guard_{name}", slot)

    def _disarm_transfer_rsp_guard(self) -> None:
        """Drop any guards installed by _arm_transfer_rsp_guard."""
        for name in (_DOCK_TRANSFER, _DOCK_TRANSFER_PROFILE):
            dock = self.docks[name]
            slot = getattr(self, f"_rsp_guard_{name}", None)
            if slot is None:
                continue
            try:
                dock.visibilityChanged.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
            setattr(self, f"_rsp_guard_{name}", None)

    # ------------------------------------------------------------------
    # Plot helpers, unchanged semantics, now write into dock-hosted layouts
    # ------------------------------------------------------------------

    def show_preprocessing_plot(self, data):
        if data is None:
            return
        if data.has_ecg:
            self.docks[_DOCK_PREPROCESSING].toggleView(True)
            self.prep_plot_widget.prepPlot(data)
        else:
            self.docks[_DOCK_PREPROCESSING].toggleView(False)

    def show_hr_plot(self, data):
        if data is not None:
            self.hr_plot_widget.hrPlot(data)

    def show_epoch_plot(self, data):
        if data is not None:
            self.epoch_plot_widget.plotEpochs(data)

    def show_poincare_plot(self, data):
        if data is not None:
            self.poincare_plot_widget.poincarePlot(data)

    def _clear_layout(self, layout) -> None:
        """Remove all widgets from *layout*, deleting them immediately."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

    def _swap_in_epoch_plot(self, layout, dataset, factory) -> None:
        """
        Replace the contents of ``layout`` with a freshly-built plot widget.

        Shared body for the PSD, Spectrogram and Profile docks. Each
        of them keeps a permanent QScrollArea in MainWindow and swaps
        the inner plot widget on every refresh, the only thing that
        varies between them is which widget class to construct.

        ``factory`` takes ``(views, labels, workspace)`` and returns
        a QWidget. The active-epoch (label, view) pairs are collected
        here so the per-dock helpers stay one-liners.
        """
        if dataset is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        pairs = []
        for label, epoch in dataset.epochs.items():
            if not epoch.active:
                continue
            try:
                pairs.append((label, dataset.hrv[label]))
            except Exception:
                continue
        if not pairs:
            return
        labels, views = zip(*pairs)
        layout.addWidget(factory(views, labels, self.workspace))

    def show_psd_plot(self, dataset) -> None:
        self._swap_in_epoch_plot(
            self.psd_layout, dataset,
            lambda v, l, w: spQt.PSDPlotWidget(v, l, workspace=w),
        )

    def show_spectrogram_plot(self, dataset) -> None:
        self._swap_in_epoch_plot(
            self.spectrogram_layout, dataset,
            lambda v, l, w: spQt.SpectrogramPlotWidget(v, l, workspace=w),
        )

    def show_transfer_plot(self, dataset) -> None:
        if not getattr(dataset, "rsp_map", None):
            self._clear_layout(self.transfer_layout)
            return
        self._swap_in_epoch_plot(
            self.transfer_layout, dataset,
            lambda v, l, w: spQt.TransferPlotWidget(v, l, workspace=w),
        )

    def show_transfer_profile_plot(self, dataset) -> None:
        if not getattr(dataset, "rsp_map", None):
            self._clear_layout(self.transfer_profile_layout)
            return
        self._swap_in_epoch_plot(
            self.transfer_profile_layout, dataset,
            lambda v, l, w: spQt.TransferProfilePlotWidget(v, l, workspace=w),
        )

    def show_profile_plot(self, dataset) -> None:
        self._swap_in_epoch_plot(
            self.profile_layout, dataset,
            lambda v, l, w: spQt.ProfilePlotWidget(v, l, workspace=w),
        )

    def show_parameters_plot(self, data):
        if data is not None:
            self.parameters_plot_widget.display_parameters(data, self.workspace)

    # ------------------------------------------------------------------
    # Epoch creation
    # ------------------------------------------------------------------

    def add_epoch(self):
        if self.dataset is None:
            return
        epoch_label, ok = QInputDialog.getText(self, "Add Epoch", "Epoch Label:")
        if not ok or not epoch_label:
            return
        if "ecg" in self.dataset.timeseries:
            start_time = self.dataset["ecg"].timeseries.times[0]
            end_time = self.dataset["ecg"].timeseries.times[-1]
        elif hasattr(self.dataset, "hrv") and self.dataset.hrv is not None:
            start_time = self.dataset.hrv.times[0]
            end_time = self.dataset.hrv.times[-1]
        else:
            return
        self.dataset.epochs[epoch_label] = Epoch(
            active=True, start=start_time, end=end_time
        )
        self.epoch_plot_widget.plotEpochs(self.dataset)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName(_ORG_NAME)
    app.setApplicationName(_APP_NAME)

    default_font = QFont("Segoe UI", 12)
    default_font.setBold(False)
    app.setStyle("WindowsVista")
    app.setFont(default_font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
