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
import json
import os
import pickle
import sys
import webbrowser
from pathlib import Path
from typing import Any

import qtawesome as qta
from platformdirs import user_config_path, user_documents_path

# Force Matplotlib to use the Qt backend inside a PySide6 app (macOS-safe).
os.environ.setdefault("MPLBACKEND", "QtAgg")
import matplotlib

matplotlib.use("QtAgg", force=True)

import PySide6QtAds as QtAds
from PySide6.QtCore import QByteArray, QObject, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QStyle,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import spectUI as spQt
from spectUI.plot_worker import DockScheduler
from spectUI.workSpace import WorkspaceConfig
from spectHR._version import __version__
from spectHR.DataSet.Epoch import Epoch
from spectHR.DataSet.PhysioData import PhysioData
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
_DOCK_BP            = "dock.bp"
_DOCK_POINCARE      = "dock.poincare"
_DOCK_EPOCHS        = "dock.epochs"
_DOCK_PSD               = "dock.psd"
_DOCK_SPECTROGRAM       = "dock.spectrogram"
_DOCK_SPECTROGRAM_3D    = "dock.spectrogram3d"   # 3-D surface companion
_DOCK_TRANSFER          = "dock.transfer"
_DOCK_TRANSFER_PROFILE  = "dock.transferprofile"
_DOCK_PROFILES          = "dock.profiles"
_DOCK_PARAMETERS    = "dock.parameters"
_DOCK_LOG           = "dock.log"

# Docks whose widget is *expensive to compute* and depends only on the
# active epochs + workspace settings (never on the timeline zoom/pan
# window). These are signature-cached so a tab activation re-displays the
# existing widget when nothing changed (see ``_refresh_dock``).
#
# The cheap docks deliberately left OUT - Preprocessing, IBI / HR series,
# Blood pressure, Poincare, Epochs - are quick to redraw and (for the
# three timeline docks) depend on the shared view window, which the cache
# signature does not track. They always refresh on activation so they
# pick up zoom/pan changes made in a sibling timeline.
_CACHED_DOCKS = frozenset({
    _DOCK_PREPROCESSING,
    _DOCK_IBI,
    _DOCK_BP,
    _DOCK_POINCARE,
    _DOCK_EPOCHS,
    _DOCK_PSD,
    _DOCK_SPECTROGRAM,
    _DOCK_SPECTROGRAM_3D,
    _DOCK_TRANSFER,
    _DOCK_TRANSFER_PROFILE,
    _DOCK_PROFILES,
    _DOCK_PARAMETERS,
})

# Timeline docks whose view can drift while hidden; on a cache hit we still
# call redraw() to sync the shared zoom/pan window without re-running the
# full (slow) plot-build.
_TIMELINE_DOCKS = frozenset({_DOCK_PREPROCESSING, _DOCK_IBI, _DOCK_BP})


class _QtLogHandler(logging.Handler):
    """Logging handler that appends records to a QPlainTextEdit widget.

    Records can arrive from background worker threads (e.g. the R-top
    classification or the heavy plot-dock prefetch). Touching a QWidget
    off the main thread is undefined behaviour, so the formatted message
    is delivered through a queued signal: the ``_Emitter`` QObject lives
    on the main thread, so its ``message`` signal is marshalled there
    regardless of which thread called ``emit``.
    """

    class _Emitter(QObject):
        message = Signal(str)

    def __init__(self, widget: QPlainTextEdit):
        super().__init__()
        self._widget = widget
        self._emitter = self._Emitter()
        self._emitter.message.connect(self._append)
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    def _append(self, msg: str) -> None:
        """Runs on the main thread (queued from emit)."""
        try:
            self._widget.appendPlainText(msg)
            # Keep the view scrolled to the latest entry.
            self._widget.moveCursor(QTextCursor.End)
        except RuntimeError:
            pass  # widget's C++ object was deleted

    def emit(self, record):
        try:
            self._emitter.message.emit(self.format(record))
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
        # Set to True whenever peaks, epochs, or parameters are mutated
        # so the pkl is only written to disk when there is actually
        # something new to persist.
        self._dirty: bool = False

        # Cache of the last-rendered signature per content dock, keyed by
        # dock objectName. A dock is rebuilt only when its inputs (active
        # epochs + workspace settings) change since it was last rendered -
        # see ``_plot_cache_signature`` and ``_refresh_dock``. This lets a
        # tab activation re-display the existing widget instead of
        # recomputing when nothing changed. Cleared whenever the dataset is
        # mutated (peaks / epochs edited -> ``_dirty`` save) or the
        # workspace settings are edited.
        self._plot_sig: dict[str, Any] = {}

        # Background worker scheduler - one concurrent worker per dock.
        # All heavy plot computation (PSD / Profiles / Spectrogram / Transfer /
        # Parameters) runs on the global thread pool; results are delivered
        # back on the main thread via cross-thread Qt signals.
        self._scheduler = DockScheduler()

        # Set while a perspective (dock layout) is being opened. ADS tears
        # down and rebuilds every dock in C++ during the switch, firing a
        # storm of visibilityChanged signals; running the heavy per-dock
        # refresh re-entrantly inside that teardown is what used to take the
        # whole app down. While this is True, _on_dock_visible skips the
        # refresh and a single deferred one runs afterwards.
        self._switching_perspective = False

        # Refresh registry, dock objectName -> refresh fn.
        self._refresh_fns: dict[str, callable] = {}

        # ---- workspace ----------------------------------------------
        self.workspace_file = user_documents_path() / "DefaultWorkSpace.json"
        self.workspace: WorkspaceConfig = spQt.LoadWorkspace(self.workspace_file)
        # Apply the configured minimum log level (Logging.level) as early as
        # possible - before the rest of construction logs anything - so the
        # user's choice governs essentially all run-time output, not just
        # what happens after the Log dock is built.
        self._apply_log_level()

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
        self.bp_plot_widget         = spQt.BPPlotWidget()
        self.poincare_plot_widget   = spQt.PoincarePlotWidget()
        self.epoch_plot_widget      = spQt.EpochPlotWidget()
        self.parameters_plot_widget = spQt.ParametersPlotWidget()

        # Mark the dataset dirty only on a *real* edit in the editing docks
        # (R-peak add/move/remove, epoch resize/rename/delete), rather than
        # whenever those docks lose focus. This keeps the plot caches valid
        # when the user merely views the Preprocessing / Epochs dock.
        self.prep_plot_widget.dataEdited.connect(self._mark_data_edited)
        self.epoch_plot_widget.dataEdited.connect(self._mark_data_edited)
        self.poincare_plot_widget.dataEdited.connect(self._mark_data_edited)

        # The timeline docks (Preprocessing, HR series, Blood pressure)
        # share one view window via ``data.view``. When the user zooms /
        # pans / drags the overview in one, mirror it onto the others so
        # they follow automatically instead of only updating when their
        # own overview is clicked.
        self._timeline_widgets = (
            self.prep_plot_widget,
            self.hr_plot_widget,
            self.bp_plot_widget,
        )
        for w in self._timeline_widgets:
            w.viewChanged.connect(self._sync_timeline_views)

        # PSD / Profiles live in their own scroll area. The inner plot
        # widget is rebuilt on every refresh, so we hold the layout,
        # not the widget.
        self.psd_scroll,        self.psd_layout        = self._make_scrollable_host()
        self.spectrogram_scroll,      self.spectrogram_layout      = self._make_scrollable_host()
        self.spectrogram3d_scroll,    self.spectrogram3d_layout    = self._make_scrollable_host()
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
        # The logger's minimum level was already set from the workspace right
        # after it was loaded (see __init__ top), so the dock only ever
        # receives records at or above the configured level.
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

        ibi_dock         = _tab(_DOCK_IBI,         "HR Series",   self.hr_plot_widget)
        bp_dock          = _tab(_DOCK_BP,          "Blood Pressure", self.bp_plot_widget)
        poincare_dock    = _tab(_DOCK_POINCARE,    "Poincare",    self.poincare_plot_widget)
        epochs_dock      = _tab(_DOCK_EPOCHS,      "Epochs",      self.epoch_plot_widget)
        psd_dock         = _tab(_DOCK_PSD,         "PSD",         self.psd_scroll)
        spectrogram_dock      = _tab(_DOCK_SPECTROGRAM,      "Spectrogram",      self.spectrogram_scroll)
        spectrogram3d_dock    = _tab(_DOCK_SPECTROGRAM_3D,   "Spectrogram 3D",   self.spectrogram3d_scroll)
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
            _DOCK_BP:               bp_dock,
            _DOCK_POINCARE:         poincare_dock,
            _DOCK_EPOCHS:           epochs_dock,
            _DOCK_PSD:              psd_dock,
            _DOCK_SPECTROGRAM:      spectrogram_dock,
            _DOCK_SPECTROGRAM_3D:   spectrogram3d_dock,
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
            _DOCK_BP:               self._refresh_bp,
            _DOCK_POINCARE:         self._refresh_poincare,
            _DOCK_EPOCHS:           self._refresh_epochs,
            _DOCK_PSD:              self._refresh_psd,
            _DOCK_SPECTROGRAM:      self._refresh_spectrogram,
            _DOCK_SPECTROGRAM_3D:   self._refresh_spectrogram3d,
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

        act_quit = QAction(qta.icon("mdi6.exit-to-app"), "Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.setStatusTip("Quit spectHR")
        act_quit.setToolTip("Quit spectHR")
        act_quit.triggered.connect(self._quit_with_confirmation)

        ws_menu = menubar.addMenu("WorkSpace")
        ws_menu.addAction(act_open)
        ws_menu.addSeparator()
        ws_menu.addAction(act_edit_ws)
        ws_menu.addAction(act_save_ws)
        ws_menu.addSeparator()
        ws_menu.addAction(act_settings)
        ws_menu.addSeparator()
        ws_menu.addAction(act_quit)

        #edits_menu = menubar.addMenu("Edits")
        #edits_menu.addAction(act_add_epoch)

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
        bumped = max(int(round(base * 1.0)), base + 1)
        toolbar.setIconSize(QSize(bumped, bumped))
        toolbar.addAction(act_open)

        # Edit + Save workspace: half-size icons stacked vertically so they
        # occupy the same horizontal space as one full-size button but signal
        # visually that they are a related pair.
        small = max(base // 2, 12)
        ws_pair = QWidget()
        ws_pair.setAttribute(Qt.WA_TranslucentBackground)
        ws_pair_layout = QVBoxLayout(ws_pair)
        ws_pair_layout.setContentsMargins(0, 2, 0, 2)
        ws_pair_layout.setSpacing(1)
        _pair_btns: list[QToolButton] = []
        for _action in (act_edit_ws, act_save_ws):
            _btn = QToolButton()
            _btn.setDefaultAction(_action)
            _btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            _btn.setIconSize(QSize(small, small))
            _btn.setAutoRaise(True)
            ws_pair_layout.addWidget(_btn)
            _pair_btns.append(_btn)
        # Pin both buttons to the width of the wider one so they are
        # equal-width without stretching to fill the whole toolbar.
        _max_w = max(b.sizeHint().width() for b in _pair_btns)
        for b in _pair_btns:
            b.setFixedWidth(_max_w)
        toolbar.addWidget(ws_pair)

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
            _DOCK_BP,
            _DOCK_POINCARE,
            _DOCK_EPOCHS,
            _DOCK_PSD,
            _DOCK_SPECTROGRAM,
            _DOCK_SPECTROGRAM_3D,
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

    def open_perspective(self, name: str) -> None:
        """Switch to dock layout *name*, guarding against a crash.

        Opening a perspective makes ADS tear down and rebuild the entire
        dock layout in C++. If anything goes wrong mid-switch the app used
        to vanish without a trace. Here the switch is wrapped so a failure
        is logged, reported, and falls back to the Default layout instead
        of killing the program. Per-dock refreshes are suppressed during
        the switch (see ``_switching_perspective``) and a single safe
        refresh is scheduled afterwards, off the ADS teardown stack.
        """
        self._switching_perspective = True
        try:
            self.dock_manager.openPerspective(name)
        except Exception:
            logger.exception("Failed to open perspective %r", name)
            QMessageBox.warning(
                self,
                "Layout error",
                f"Could not switch to the {name!r} layout.\n\n"
                "Falling back to the Default layout.",
            )
            try:
                self.dock_manager.openPerspective(perspectives.BUILTIN_DEFAULT)
            except Exception:
                logger.exception("Fallback to Default perspective also failed")
        finally:
            self._switching_perspective = False

        # One controlled refresh of the now-visible docks, scheduled so it
        # runs after ADS has finished rebuilding rather than re-entrantly.
        QTimer.singleShot(0, self._refresh_visible_docks)

    def _refresh_visible_docks(self) -> None:
        """Refresh every alive, visible dock once (post perspective switch)."""
        if self.dataset is None:
            return
        try:
            sig = self._plot_cache_signature(self.dataset)
        except Exception:
            logger.exception("Plot signature failed after perspective switch")
            return
        for name, dock in self.docks.items():
            if not self._dock_alive(dock):
                continue
            if dock.isClosed() or not dock.isVisible():
                continue
            self._refresh_dock(name, sig)

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
        """Persist the dataset, then geometry / window state / dock layout.

        Reached by both close paths: the Quit action (which calls
        ``self.close()``) and the window's close button. Saving the dataset
        here is the only on-close persistence point, so unsaved R-peak /
        epoch edits are flushed before the app exits.
        """
        self._save_current_dataset_if_dirty()

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

    def _apply_log_level(self) -> None:
        """Set the ``spectHR`` logger to the workspace-configured minimum level.

        Reads ``Logging.level`` from the current workspace and applies it to
        the logger, so records below the chosen severity are dropped before
        they reach either the console or the Log dock. Called on start-up and
        whenever the workspace is edited or opened.
        """
        level = spQt.log_level_from_workspace(self.workspace)
        logging.getLogger("spectHR").setLevel(level)

    def _save_current_dataset_if_dirty(self) -> None:
        """Persist the active dataset to its cache file if it has unsaved edits.

        R-peak / epoch edits mark the dataset dirty but no longer save on
        every dock switch — pickling the full recording is slow and froze
        the UI. Instead we save at the two moments the dataset stops being
        the active one: when another file is selected and when the app is
        closed (Quit or the window's close button). Both paths call this.
        """
        if self._dirty and self.dataset is not None and self.savename is not None:
            try:
                self.dataset.save(self.savename)
                self._dirty = False
            except Exception:
                logger.exception("Failed to save dataset to %s", self.savename)

    def _mark_data_edited(self) -> None:
        """A real edit happened in an editing dock (R-peaks / epochs).

        Fired by the editing widgets' ``dataEdited`` signal. Marks the
        dataset dirty (so it is persisted when the dataset stops being
        active — see _save_current_dataset_if_dirty) and
        drops every cached plot signature so the computed docks recompute
        from the mutated data. Because this is driven by genuine edits,
        simply viewing the Preprocessing / Epochs dock no longer
        invalidates anything.

        Any computed dock (PSD, Profile, Parameters, …) that is already
        visible is refreshed immediately so the user does not have to
        switch away and back to see the change reflected.
        """
        self._dirty = True
        self._plot_sig.clear()
        self._scheduler.invalidate()

        if self.dataset is None:
            return
        sig = self._plot_cache_signature(self.dataset)
        for name, dock in self.docks.items():
            if name not in _CACHED_DOCKS:
                continue
            if not self._dock_alive(dock):
                continue
            if dock.isClosed() or not dock.isVisible():
                continue
            self._refresh_dock(name, sig)

    def _sync_timeline_views(self) -> None:
        """Mirror a committed view-window change onto the other timelines.

        Connected to every timeline widget's ``viewChanged`` signal. The
        sending widget already redrew itself; here we redraw the *other*
        currently-visible timeline docks so the shared window stays in
        sync live. Hidden / closed docks are skipped - they re-read the
        shared ``data.view`` (and so show the right window) the next time
        they are brought forward via ``_on_dock_visible``.
        """
        source = self.sender()
        for w in self._timeline_widgets:
            try:
                if w is source or not w.isVisible():
                    continue
                if getattr(w, "data", None) is None or getattr(w.data, "view", None) is None:
                    continue
                w.redraw()
            except Exception:
                logger.debug("timeline view-sync redraw failed", exc_info=True)

    def _on_dock_visible(self, name: str, visible: bool) -> None:
        """
        Refresh the dock when it is brought forward, if its inputs changed.

        On activation we persist the dataset (if a real edit marked it
        dirty) and then ask :meth:`_refresh_dock` to rebuild the dock -
        which it does only when the dock's cache signature changed, so an
        unchanged expensive dock re-displays its existing widget instead
        of recomputing. The cheap docks always refresh (see
        ``_CACHED_DOCKS``).

        Floating content docks are refreshed alongside, because a floating
        dock stays visible regardless of which centre tab is active and so
        never fires its own visibilityChanged on a tab switch; without this
        they would miss edits made elsewhere. They are gated by the same
        signature, so a floating dock only recomputes when it actually
        needs to.
        """
        # Dirtiness is now driven by the editing widgets' dataEdited signal
        # (see _mark_data_edited), so a dock merely losing focus no longer
        # invalidates anything - viewing the Preprocessing / Epochs dock
        # without editing keeps every plot cache valid.
        if not visible:
            return
        # During a perspective switch ADS rebuilds the whole layout; defer
        # refreshing to the single pass in _refresh_visible_docks so we
        # never run heavy plot builds re-entrantly inside that teardown.
        if self._switching_perspective:
            return
        if self.dataset is None:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # Edits no longer save here — persisting the full recording is
            # slow and froze the UI on the first dock switch after an edit.
            # The dataset is now saved only when it stops being active (file
            # switch or app close); see _save_current_dataset_if_dirty.
            # Cache invalidation already happened in _mark_data_edited, so a
            # dirty dataset's stale docks are recomputed regardless.
            #
            # One signature for this activation; _refresh_dock reuses the
            # already-rendered widget when the dock's signature is
            # unchanged (no data / settings change since it was built).
            sig = self._plot_cache_signature(self.dataset)
            self._refresh_dock(name, sig)
            # Floating content docks piggy-back on every visibility
            # change so they catch mutations done elsewhere. The signature
            # gate in _refresh_dock keeps this cheap - an expensive dock
            # whose inputs are unchanged is skipped, transfer plots included.
            for other_name, dock in self.docks.items():
                if other_name == name:
                    continue
                if not self._dock_alive(dock):
                    continue
                if dock.isClosed() or not dock.isFloating():
                    continue
                self._refresh_dock(other_name, sig)
        finally:
            QApplication.restoreOverrideCursor()

    def _refresh_preprocessing(self) -> None:
        self.show_preprocessing_plot(self.dataset)

    def _refresh_ibi(self) -> None:
        self.show_hr_plot(self.dataset)

    def _refresh_bp(self) -> None:
        self.show_bp_plot(self.dataset)

    def _refresh_poincare(self) -> None:
        self.show_poincare_plot(self.dataset)

    def _refresh_epochs(self) -> None:
        self.show_epoch_plot(self.dataset)

    def _refresh_psd(self) -> None:
        self.show_psd_plot(self.dataset)

    def _refresh_spectrogram(self) -> None:
        self.show_spectrogram_plot(self.dataset)

    def _refresh_spectrogram3d(self) -> None:
        self.show_spectrogram3d_plot(self.dataset)

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

    def _quit_with_confirmation(self) -> None:
        """Ask the user to confirm before closing the application."""
        reply = QMessageBox.question(
            self,
            "Quit spectHR",
            "Are you sure you want to quit?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.close()

    def OpenWorkSpace(self):
        """Open a JSON workspace file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select a file", "", "workspace Files (*.json);;Text Files (*.txt)"
        )
        if file_path:
            self.workspace_file = file_path
            self.workspace = spQt.LoadWorkspace(file_path)
            self._apply_log_level()
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
        3. Because settings changed, every cached plot signature is dropped.
           The docks that depend directly on the edited parameters (PSD,
           Spectrogram, 3-D Spectrogram, Transfer, Transfer profile,
           Profiles) are refreshed now if open; the rest recompute lazily
           the next time they are brought forward.
        """
        dialog = spQt.ParametersEditorDialog(self.workspace, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            self.workspace = WorkspaceConfig(dialog.get_parameters(self.workspace))

            try:
                spQt.SaveWorkspace(self.workspace, self.workspace_file)
            except Exception as e:
                logger.warning(f"Could not save workspace after parameter edit: {e}")

            # The log level may have been changed in the dialog.
            self._apply_log_level()

            if self.dataset is not None:
                # Settings changed -> every cached plot is stale. Clearing
                # the signatures makes each dock recompute (with the new
                # settings) the next time it is shown.
                self._plot_sig.clear()
                self._scheduler.invalidate()
                sig = self._plot_cache_signature(self.dataset)
                # PSD, Spectrogram, and Profiles depend directly on what
                # was edited (bands, window, step, PSD method, coherence
                # threshold, etc.); refresh them now via _refresh_dock so
                # the new signature is stored and they are not recomputed
                # again on first view. Other docks recompute on next show.
                self._refresh_dock(_DOCK_PSD, sig)
                self._refresh_dock(_DOCK_SPECTROGRAM, sig)
                if not self.docks[_DOCK_SPECTROGRAM_3D].isClosed():
                    self._refresh_dock(_DOCK_SPECTROGRAM_3D, sig)
                # The transfer plots are expensive; only recompute them
                # if their dock is open. A closed dock recomputes lazily
                # (with the new settings) the next time it is shown.
                if not self.docks[_DOCK_TRANSFER].isClosed():
                    self._refresh_dock(_DOCK_TRANSFER, sig)
                if not self.docks[_DOCK_TRANSFER_PROFILE].isClosed():
                    self._refresh_dock(_DOCK_TRANSFER_PROFILE, sig)
                self._refresh_dock(_DOCK_PROFILES, sig)
                self._refresh_dock(_DOCK_IBI, sig)

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
            and not item.text(0).lower().endswith(".edf")
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

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.dataset.retrigger(
                min_peak_distance_ms=min_peak_distance_ms, classify=classify
            )
            self.dataset.save(self.savename)
        finally:
            QApplication.restoreOverrideCursor()
        self._dirty = False
        # R-peaks were rebuilt; every computed plot is stale even though the
        # epochs / settings signature did not change.
        self._plot_sig.clear()
        self._scheduler.invalidate()
        self.show_preprocessing_plot(self.dataset)
        self.show_hr_plot(self.dataset)

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
        self._dirty = False
        # ECG polarity flipped and re-detected; every computed plot is stale.
        self._plot_sig.clear()
        self._scheduler.invalidate()
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

        # Flush unsaved edits on the dataset we're leaving before its
        # savename is reassigned below to the newly-selected file.
        self._save_current_dataset_if_dirty()

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
                # A cold cache may need first-time preprocessing; an older
                # cache may need an in-place migration. Both live on the
                # model now (PhysioData.ensure_preprocessed / migrate_cached)
                # and report whether they changed anything so we only re-save
                # when needed.
                if dataset.ensure_preprocessed(
                    respiration_per_epoch=self._respiration_per_epoch()
                ):
                    dataset.save(self.savename)
                elif dataset.migrate_cached():
                    dataset.save(self.savename)
            else:
                dataset = PhysioData(Path(dirs["DataDirectory"]) / Path(filename))
                # Apply the manual BP calibration on the cold load too, so a
                # reloaded single-band file gets BP in mmHg, not raw counts
                # (PreProcessFile does the same for the band-node path).
                spQt.apply_bp_calibration(dataset, self.workspace)
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
        without a blood-pressure or respiration channel). The View-menu
        entry stays enabled so the user can re-open them - on re-open the
        widget renders its own "no input channel" placeholder.
        """
        # Preprocessing dock visibility follows ECG availability.
        has_ecg = bool(getattr(self.dataset, "has_ecg", False))
        self.docks[_DOCK_PREPROCESSING].toggleView(has_ecg)

        # Transfer-family docks need a transfer *input* channel. The output
        # is always the IBI/HR series; the input is blood pressure (the
        # default, for baroreflex sensitivity) or respiration (for RSA),
        # selectable in the workspace. The docks are therefore available
        # when EITHER channel is present, and only disabled (with a guard +
        # explanatory toggle) when both are absent.
        rsp_map = getattr(self.dataset, "rsp_map", None) or {}
        has_rsp = bool(rsp_map)
        timeseries = getattr(self.dataset, "timeseries", None) or {}
        has_bp = "bp" in timeseries
        has_tf_input = has_rsp or has_bp
        for name in (_DOCK_TRANSFER, _DOCK_TRANSFER_PROFILE):
            dock = self.docks[name]
            if not self._dock_alive(dock):
                continue
            dock.toggleView(has_tf_input and not dock.isClosed())
            action = dock.toggleViewAction()
            action.setEnabled(has_tf_input)
            action.setToolTip(
                "" if has_tf_input
                else "Disabled: this recording has no respiration or "
                     "blood-pressure channel"
            )
        if not has_tf_input:
            self._arm_transfer_rsp_guard()
        else:
            self._disarm_transfer_rsp_guard()

        # Blood-pressure dock follows the presence of a "bp" timeseries.
        # When absent we close the dock and disable its View-menu toggle
        # (no placeholder is rendered - the widget simply draws nothing).
        bp_dock = self.docks[_DOCK_BP]
        if self._dock_alive(bp_dock):
            bp_dock.toggleView(has_bp and not bp_dock.isClosed())
            bp_action = bp_dock.toggleViewAction()
            bp_action.setEnabled(has_bp)
            bp_action.setToolTip(
                "" if has_bp
                else "Disabled: this recording has no blood-pressure channel"
            )

        def _closed(dock_name: str) -> bool:
            d = self.docks.get(dock_name)
            return not self._dock_alive(d) or d.isClosed()

        skip_when_missing = {
            _DOCK_PREPROCESSING:    not has_ecg,
            _DOCK_BP:               not has_bp,
            # The transfer plots are expensive (per-epoch coherence /
            # transfer-function estimation). Skip them when the channel is
            # missing *or* the dock is closed, and let visibilityChanged
            # compute lazily the first time the user brings them forward.
            _DOCK_TRANSFER:         not has_tf_input or _closed(_DOCK_TRANSFER),
            _DOCK_TRANSFER_PROFILE: not has_tf_input or _closed(_DOCK_TRANSFER_PROFILE),
            # 3-D spectrogram is the most expensive widget; skip it when
            # the dock is closed and let visibilityChanged handle it lazily.
            _DOCK_SPECTROGRAM_3D:   _closed(_DOCK_SPECTROGRAM_3D),
        }
        # New dataset -> every cached plot is stale.
        self._plot_sig.clear()
        self._scheduler.invalidate()
        sig = self._plot_cache_signature(self.dataset)
        for name in self._refresh_fns:
            # Skip refresh on docks whose data isn't on this dataset.
            # The dock is already hidden; the placeholder will render
            # only if/when the user toggles it back on.
            if skip_when_missing.get(name, False):
                continue
            # Routes through _refresh_dock so the signature is stored now;
            # the first time the user activates this dock afterwards it is
            # reused rather than recomputed.
            self._refresh_dock(name, sig)

        # The parameters dock may already be the active/visible tab when a
        # file is loaded (e.g. on app restart). visibilityChanged therefore
        # doesn't fire for it, so the only path is through the loop above.
        # If _on_dock_visible fired mid-loop (from an earlier toggleView) and
        # stored the sig, the loop's _refresh_dock sees a match and skips the
        # refresh. Guard against that by forcing it unconditionally here.
        self._plot_sig.pop(_DOCK_PARAMETERS, None)
        self._refresh_dock(_DOCK_PARAMETERS, sig)

    @staticmethod
    def _dock_alive(dock) -> bool:
        """Return True if the CDockWidget's C++ backing object still exists.

        PySide6QtAds dock widgets are parented to the CDockManager; when
        ``deleteLater()`` is called on the manager at close time the C++
        objects are destroyed, but Python lambdas connected to signals may
        still fire.  Any method call on a deleted C++ object raises
        ``RuntimeError``; this guard catches that gracefully.
        """
        try:
            dock.objectName()   # any innocuous CDockWidget method
            return True
        except RuntimeError:
            return False

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
                        "This analysis estimates how an input signal drives "
                        "heart-rate variability — blood pressure (for "
                        "baroreflex sensitivity) or respiration (for RSA) — "
                        "so it needs a blood-pressure or respiration channel "
                        "in the recording. The currently loaded file has "
                        "neither.",
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
        try:
            if data.has_ecg:
                self.docks[_DOCK_PREPROCESSING].toggleView(True)
                self.prep_plot_widget.prepPlot(data)
            else:
                self.docks[_DOCK_PREPROCESSING].toggleView(False)
        except RuntimeError:
            pass

    def show_hr_plot(self, data):
        if data is None:
            return
        try:
            self.hr_plot_widget.hrPlot(data, workspace=self.workspace)
        except RuntimeError:
            pass

    def show_bp_plot(self, data):
        if data is None:
            return
        try:
            self.bp_plot_widget.bpPlot(data)
        except RuntimeError:
            pass

    def show_epoch_plot(self, data):
        if data is None:
            return
        try:
            self.epoch_plot_widget.plotEpochs(data)
        except RuntimeError:
            pass

    def show_poincare_plot(self, data):
        if data is None:
            return
        try:
            self.poincare_plot_widget.poincarePlot(data)
        except RuntimeError:
            pass

    def _clear_layout(self, layout) -> None:
        """Remove all widgets from *layout*, deleting them immediately."""
        try:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()
        except RuntimeError:
            pass

    def _async_swap_epoch_plot(
        self,
        dock_name: str,
        layout,
        dataset,
        prefetch_fn,
        widget_fn,
    ) -> None:
        """Submit the heavy PSD / Spectrogram / Profile / Transfer computation
        to the global thread pool and swap in the resulting widget on the
        main thread when done.

        Parameters
        ----------
        dock_name:   Stable ``_DOCK_*`` constant; drives the generation counter.
        layout:      The dock's inner ``QVBoxLayout`` whose contents are swapped.
        dataset:     The current ``PhysioData`` instance.
        prefetch_fn: ``(views, labels, workspace) -> list``  — pure compute,
                     called on a **background thread**.
        widget_fn:   ``(views, labels, workspace, precomputed) -> QWidget``  —
                     widget construction with the precomputed data, called on
                     the **main thread** in ``on_done``.
        """
        if dataset is None:
            return
        try:
            self._clear_layout(layout)
            pairs: list = []
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

            # Show a lightweight placeholder while the worker runs. Kept
            # inside the guard: if the dock's layout C++ object was deleted
            # (dock closed/recreated), abort without submitting work.
            loading = QLabel("Computing…")
            loading.setAlignment(Qt.AlignCenter)
            layout.addWidget(loading)
        except RuntimeError:
            return

        workspace = self.workspace

        def compute():
            return prefetch_fn(views, labels, workspace)

        def on_done(precomputed):
            try:
                self._clear_layout(layout)
                layout.addWidget(widget_fn(views, labels, workspace, precomputed))
            except RuntimeError:
                pass
            except Exception as exc:
                logger.warning("Failed to render %s: %s", dock_name, exc, exc_info=True)
                try:
                    err = QLabel(f"Error rendering plot: {exc}")
                    err.setAlignment(Qt.AlignCenter)
                    layout.addWidget(err)
                except RuntimeError:
                    pass

        def on_error(exc):
            try:
                self._clear_layout(layout)
                err = QLabel(f"Error: {exc}")
                err.setAlignment(Qt.AlignCenter)
                layout.addWidget(err)
                logger.warning("Plot computation failed for %s: %s", dock_name, exc)
            except RuntimeError:
                pass

        self._scheduler.submit(dock_name, compute, on_done, on_error)

    def show_psd_plot(self, dataset) -> None:
        self._async_swap_epoch_plot(
            _DOCK_PSD, self.psd_layout, dataset,
            prefetch_fn=spQt.PSDPlotWidget.prefetch,
            widget_fn=lambda v, l, w, pre: spQt.PSDPlotWidget(
                v, l, workspace=w, _precomputed=pre,
            ),
        )

    def show_spectrogram_plot(self, dataset) -> None:
        self._async_swap_epoch_plot(
            _DOCK_SPECTROGRAM, self.spectrogram_layout, dataset,
            prefetch_fn=spQt.SpectrogramPlotWidget.prefetch,
            widget_fn=lambda v, l, w, pre: spQt.SpectrogramPlotWidget(
                v, l, workspace=w, _precomputed=pre,
            ),
        )

    def show_spectrogram3d_plot(self, dataset) -> None:
        """Refresh the Spectrogram 3D dock on a background thread."""
        self._async_swap_epoch_plot(
            _DOCK_SPECTROGRAM_3D, self.spectrogram3d_layout, dataset,
            prefetch_fn=spQt.Spectrogram3DPlotWidget.prefetch,
            widget_fn=lambda v, l, w, pre: spQt.Spectrogram3DPlotWidget(
                v, l, workspace=w, _precomputed=pre,
            ),
        )

    def _plot_cache_signature(self, dataset) -> tuple:
        """Signature of everything the computed plot docks depend on.

        A dock is rebuilt only when this signature changes since it was
        last rendered (see :meth:`_refresh_dock`). It captures:

        * the active epochs (label + bounds), and
        * the whole workspace settings (any analysis parameter, band edge,
          calibration, etc.).

        Using the entire workspace is deliberately conservative: a change
        to *any* setting invalidates every dock, which always recomputes
        the right thing (at worst it recomputes a dock whose own settings
        did not change - cheap and rare). ``Directories`` is excluded
        because it never affects a plot.

        R-peak / epoch *edits* don't change this signature on their own,
        so they are handled separately by clearing ``_plot_sig`` on every
        edit (see :meth:`_mark_data_edited`).
        """
        epochs = tuple(
            (label, float(ep.start), float(ep.end))
            for label, ep in getattr(dataset, "epochs", {}).items()
            if getattr(ep, "active", False)
        )
        ws = self.workspace or {}
        try:
            ws_sig = json.dumps(
                {k: v for k, v in ws.items() if k != "Directories"},
                sort_keys=True, default=str,
            )
        except Exception:
            # Fall back to a repr if anything in the workspace is not
            # JSON-serialisable; still stable within a session.
            ws_sig = repr(sorted(
                (k, repr(v)) for k, v in ws.items() if k != "Directories"
            ))
        return (epochs, ws_sig)

    def _refresh_dock(self, name: str, sig: tuple) -> None:
        """Refresh dock *name* only if its inputs changed since last render.

        Compares *sig* (from :meth:`_plot_cache_signature`) against the
        signature stored when the dock was last rendered. On a match the
        existing widget is left untouched - the user's request: when
        nothing in the data or settings changed, re-display the old widget
        instead of recomputing. Otherwise the dock's refresh fn runs and
        the new signature is stored.
        """
        refresh_fn = self._refresh_fns.get(name)
        if refresh_fn is None:
            return
        if name in _CACHED_DOCKS and self._plot_sig.get(name) == sig:
            # Timeline docks share a zoom/pan window that can change while the
            # dock is hidden; call redraw() to sync the view without re-running
            # the full (slow) plot build.
            if name in _TIMELINE_DOCKS:
                try:
                    w = self.docks[name].widget()
                    if w is not None and getattr(w, "data", None) is not None:
                        w.redraw()
                except RuntimeError:
                    pass
            return
        # toggleView() inside a refresh fn can fire visibilityChanged
        # re-entrantly and make ADS tear down / recreate other docks
        # mid-loop, leaving their widgets as dead C++ objects. Central
        # guard so a stale dock skips refresh instead of crashing the load.
        try:
            refresh_fn()
        except RuntimeError:
            return
        self._plot_sig[name] = sig

    def show_transfer_plot(self, dataset) -> None:
        if not getattr(dataset, "rsp_map", None):
            self._clear_layout(self.transfer_layout)
            return
        self._async_swap_epoch_plot(
            _DOCK_TRANSFER, self.transfer_layout, dataset,
            prefetch_fn=spQt.TransferPlotWidget.prefetch,
            widget_fn=lambda v, l, w, pre: spQt.TransferPlotWidget(
                v, l, workspace=w, _precomputed=pre,
            ),
        )

    def show_transfer_profile_plot(self, dataset) -> None:
        if not getattr(dataset, "rsp_map", None):
            self._clear_layout(self.transfer_profile_layout)
            return
        self._async_swap_epoch_plot(
            _DOCK_TRANSFER_PROFILE, self.transfer_profile_layout, dataset,
            prefetch_fn=spQt.TransferProfilePlotWidget.prefetch,
            widget_fn=lambda v, l, w, pre: spQt.TransferProfilePlotWidget(
                v, l, workspace=w, _precomputed=pre,
            ),
        )

    def show_profile_plot(self, dataset) -> None:
        self._async_swap_epoch_plot(
            _DOCK_PROFILES, self.profile_layout, dataset,
            prefetch_fn=spQt.ProfilePlotWidget.prefetch,
            widget_fn=lambda v, l, w, pre: spQt.ProfilePlotWidget(
                v, l, workspace=w, _precomputed=pre,
            ),
        )

    def show_parameters_plot(self, data) -> None:
        if data is None:
            return
        try:
            # Touching the table's C++ object raises if the dock was
            # closed/recreated during a file load; abort without submitting.
            self.parameters_plot_widget._start_loading()
        except RuntimeError:
            return
        workspace = self.workspace

        def compute():
            return spQt.ParametersPlotWidget.prefetch_table(data, workspace)

        def on_done(precomputed):
            try:
                self.parameters_plot_widget.display_parameters(
                    data, workspace, _precomputed=precomputed,
                )
            except RuntimeError:
                pass

        def on_error(exc):
            try:
                self.parameters_plot_widget.table_widget.clear()
                self.parameters_plot_widget.table_widget.setRowCount(1)
                self.parameters_plot_widget.table_widget.setColumnCount(1)
                self.parameters_plot_widget.table_widget.setItem(
                    0, 0, QTableWidgetItem(f"Error: {exc}"),
                )
                logger.warning("Parameters computation failed: %s", exc)
            except RuntimeError:
                pass

        self._scheduler.submit(_DOCK_PARAMETERS, compute, on_done, on_error)

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
        self._mark_data_edited()
        self.epoch_plot_widget.plotEpochs(self.dataset)


def _install_global_excepthook() -> None:
    """Stop an unhandled exception in a Qt slot from silently killing the app.

    Under PySide6 an exception that escapes a slot aborts the process with
    no message at all ("poof"). Routing it through our own hook logs the
    full traceback and shows a dialog, then lets the event loop carry on,
    so a single bad action (e.g. switching to a broken layout) is
    recoverable instead of fatal.
    """
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.error(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )
        try:
            QMessageBox.critical(
                None,
                "Unexpected error",
                f"{exc_type.__name__}: {exc_value}\n\n"
                "The action was aborted, but the program is still running.",
            )
        except Exception:
            # Never let the handler itself raise — that would re-trigger abort.
            pass

    sys.excepthook = _hook


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName(_ORG_NAME)
    app.setApplicationName(_APP_NAME)

    # Install before any window exists so even start-up slot errors surface.
    _install_global_excepthook()

    default_font = QFont("Segoe UI", 10)
    default_font.setBold(False)
    app.setStyle("WindowsVista")
    app.setFont(default_font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
