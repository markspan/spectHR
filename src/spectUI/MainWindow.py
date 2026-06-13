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

import pickle
import sys
import time
from pathlib import Path

import numpy as np
import qtawesome as qta
from PySide6.QtCore import Qt, QObject, QSize, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6QtAds import CDockManager, CDockWidget, DockWidgetArea

from spectHR._version import __version__
from spectHR.DataSet.loaders import load as _load_session
from spectHR.Tools.Logger import logger
from spectHR.session import Session
from spectHR.DataSet.preprocessing import (
    apply_beat_detection,
    apply_bp_calibration,
    apply_breath_phases,
    apply_canonical_channels,
    apply_ecg_polarity,
    apply_rsp_source,
    invert_ecg,
    recompute_breath_phases,
    retrigger_beats,
)

from spectUI.perspectives import (
    BUILTIN_COMPARE,
    BUILTIN_DEFAULT,
    BUILTIN_PSDFOCUS,
    PerspectiveMenu,
)
from spectUI.plot_worker import DockScheduler
from spectUI.settings import AppSettings
from spectUI.coordinator import DataChange, DataCoordinator
from spectUI.widgets import (
    BPSeriesWidget,
    EpochEditorWidget,
    HRSeriesWidget,
    PoincareWidget,
    PrepPlotWidget,
    ProfilePlotWidget,
    PSDPlotWidget,
    ResultsTableWidget,
    Spectrogram3DPlotWidget,
    SpectrogramPlotWidget,
    TransferPlotWidget,
    TransferProfilePlotWidget,
)
from spectUI.widgets.WorkSpaceEditor import DirectorySelectorDialog, ParametersEditorDialog
from spectUI.widgets.log_widget import LogWidget
from spectUI.widgets.timeline.base import TimelineView
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

# Docks that need a particular source channel to be meaningful.  When the
# predicate is False for the loaded session the dock is hidden and its
# View-menu entry greyed out.  Docks not listed here are always available
# (they derive from the R-peaks, which every loaded session has).
_DOCK_REQUIRES: dict[str, "Callable[[Session], bool]"] = {
    _DOCK_BP:              lambda s: s.bp is not None,
    _DOCK_TRANSFER:        lambda s: s.resp is not None or s.bp is not None,
    _DOCK_TRANSFERPROFILE: lambda s: s.resp is not None or s.bp is not None,
}


# ---------------------------------------------------------------------------
# Background file loader
# ---------------------------------------------------------------------------

class _LoadWorker(QObject):
    """Loads a recording file on a worker thread.

    Emits ``finished`` with the ready ``Session`` on success, or
    ``failed`` with a human-readable error string on failure.
    The caller is responsible for moving this object to a ``QThread``
    before calling ``run()``.
    """

    finished = Signal(object, float)   # (Session, elapsed_seconds)
    failed   = Signal(str,   str)      # (path_str, error_message)

    def __init__(self, path: Path, params: "Parameters") -> None:
        super().__init__()
        self._path   = path
        self._params = params

    def run(self) -> None:
        t0 = time.monotonic()
        try:
            session = _load_session(self._path)
            # A cached ``.pkl`` is an already-processed Session (it may carry
            # the user's R-peak edits) — re-running the pipeline would, e.g.,
            # flip an already-corrected ECG a second time, and recomputing
            # breath phases on every cache load would defeat the cache.  Only
            # raw files get the conditioning pipeline; the ``.pkl`` is trusted
            # to already hold the derived data (breath phases included).
            if self._path.suffix.lower() != ".pkl":
                session = apply_canonical_channels(session)            # alias keys first
                session = apply_ecg_polarity(session,   self._params)  # before detection
                session = apply_rsp_source(session,     self._params)
                session = apply_bp_calibration(session, self._params)
                session = apply_beat_detection(session, self._params)
                session = apply_breath_phases(session,  self._params)  # needs beats
            self.finished.emit(session, time.monotonic() - t0)
        except Exception as exc:
            self.failed.emit(str(self._path), str(exc))


def _session_summary(session: Session) -> str:
    """Return a multi-line human-readable summary of *session*."""
    lines: list[str] = []

    # Duration — prefer the experiment epoch, fall back to sample axes
    exp   = session.epochs.get("experiment")
    dur_s = (exp.end - exp.start) if exp else max(
        (s.times[-1] for s in session.samples.values() if len(s.times)),
        default=0.0,
    )
    h, rem  = divmod(int(dur_s), 3600)
    m, s    = divmod(rem, 60)
    dur_str = (f"{h} h {m:02d} min" if h else
               f"{m} min {s:02d} s"  if m else
               f"{s} s")
    lines.append(f"  Duration : {int(dur_s):,} s  ({dur_str})")

    # Sample channels with sampling rate
    if session.samples:
        ch_parts = []
        for name, sig in sorted(session.samples.items()):
            rate = getattr(sig, "srate", None)
            ch_parts.append(f"{name} ({rate:.0f} Hz)" if rate else name)
        lines.append(f"  Samples  : {', '.join(ch_parts)}")

    # R-peaks / mean HR
    hrv = session.hrv
    if hrv is not None and len(hrv.times):
        ibi  = hrv.ibi
        fin  = ibi[np.isfinite(ibi)]
        hr   = f"  |  mean HR {60.0 / fin.mean():.1f} bpm" if len(fin) else ""
        lines.append(f"  R-peaks  : {len(hrv.times):,}{hr}")

    # Epochs
    if session.epochs:
        names = ", ".join(session.epochs)
        lines.append(f"  Epochs   : {names}  ({len(session.epochs)} total)")

    return "\n".join(lines)


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
        self._coordinator     = DataCoordinator(self)
        self._settings        = AppSettings()
        self._parameters       = Parameters.default()
        self._parameters_path: Path | None = None
        # Respiration settings last applied to the loaded Session's breath
        # phases; a change triggers a re-detection in _on_workspace_changed.
        self._resp_key: tuple | None = None
        self._session:         Session | None = None
        self._load_thread:     QThread | None = None
        self._prep_widget:     PrepPlotWidget | None = None
        self._loaded_raw_path: Path | None = None  # the raw file behind the cache

        self._docks: dict[str, CDockWidget] = {}
        # Live data docks (those that take a Session), keyed by object name.
        self._data_docks: dict[str, QWidget] = {}

        # Debounced "data changed → save edited Session to the cache" timer.
        self._cache_timer = QTimer(self)
        self._cache_timer.setSingleShot(True)
        self._cache_timer.setInterval(1500)
        self._cache_timer.timeout.connect(self._save_cache)

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
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_menu)
        self._add_dock(_DOCK_WORKSPACE, "Workspace", self._tree,
                       DockWidgetArea.LeftDockWidgetArea)

        # Which centre docks are live (take a Session) and what each derives
        # from — the coordinator refreshes a dock when its dependencies change.
        # Docks not listed here are still placeholders.
        # Heavy spectral docks all derive from the R-peaks, the epoch table
        # and the analysis parameters.
        _HEAVY = DataChange.HRV | DataChange.EPOCHS | DataChange.PARAMS
        data_specs = {
            _DOCK_PREPROCESSING: (PrepPlotWidget, DataChange.HRV | DataChange.EPOCHS),
            _DOCK_HR:            (HRSeriesWidget, DataChange.HRV | DataChange.EPOCHS),
            _DOCK_BP:            (BPSeriesWidget, DataChange.BP | DataChange.EPOCHS),
            _DOCK_POINCARE:      (PoincareWidget, DataChange.HRV | DataChange.EPOCHS),
            _DOCK_EPOCHS:        (EpochEditorWidget, DataChange.HRV | DataChange.EPOCHS),
            _DOCK_PSD:           (PSDPlotWidget, _HEAVY),
            _DOCK_PROFILES:      (ProfilePlotWidget, _HEAVY),
            _DOCK_SPECTROGRAM:   (SpectrogramPlotWidget, _HEAVY | DataChange.RESP),
            _DOCK_SPECTROGRAM3D: (Spectrogram3DPlotWidget, _HEAVY | DataChange.RESP),
            _DOCK_TRANSFER:      (TransferPlotWidget, _HEAVY | DataChange.BP | DataChange.RESP),
            _DOCK_TRANSFERPROFILE: (TransferProfilePlotWidget,
                                    _HEAVY | DataChange.BP | DataChange.RESP),
            _DOCK_RESULTS:       (ResultsTableWidget, DataChange.ALL),
        }

        # Centre: tabified plot docks.
        reference_area = None
        for obj_name, title in _CENTRE_DOCKS:
            spec = data_specs.get(obj_name)
            if spec is not None:
                factory, depends = spec
                widget = factory()
                self._register_data_dock(obj_name, widget, depends)
            else:
                widget = _Placeholder(title)
            dock = self._add_dock(obj_name, title, widget)
            if spec is not None:
                dock.visibilityChanged.connect(
                    lambda vis, w=widget: vis and self._coordinator.widget_shown(w)
                )
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

    def _register_data_dock(
        self, obj_name: str, widget: QWidget, depends: DataChange
    ) -> None:
        """Track a live data dock and wire it into the coordinator.

        Timeline docks also join the shared scrolling window.  The
        pre-processing dock additionally drives the ``HRV`` change channel via
        its ``dataEdited`` signal.
        """
        self._data_docks[obj_name] = widget
        self._coordinator.register(widget, depends)
        if isinstance(widget, TimelineView):
            self._coordinator.register_timeline(widget)
        if obj_name == _DOCK_PREPROCESSING:
            self._prep_widget = widget
            widget.dataEdited.connect(self._on_data_edited)
        # Optional cross-dock signals (Poincaré and future editors).
        if hasattr(widget, "epochsChanged"):
            widget.epochsChanged.connect(
                lambda w=widget: self._on_epochs_changed(w)
            )
        if hasattr(widget, "annotationActivated"):
            widget.annotationActivated.connect(self._jump_to_prep_at)

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
        self._view_actions: dict[str, object] = {}
        for obj_name, label in _VIEW_LABELS.items():
            dock = self._docks.get(obj_name)
            if dock:
                act = dock.toggleViewAction()
                act.setText(label)
                view_menu.addAction(act)
                self._view_actions[obj_name] = act
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
            self, "Open workspace", str(self._parameters.data_dir),
            "Workspace (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            self._parameters      = Parameters.load(path)
            self._parameters_path = Path(path)
        except Exception as exc:
            QMessageBox.critical(self, "Workspace error", str(exc))
            return
        populate_tree(self._tree, self._parameters.data_dir)
        self._on_workspace_changed()

    def save_workspace(self) -> None:
        """Persist the current settings to the workspace file (default ~/workspace.json)."""
        target = self._parameters_path or self._workspace_file
        try:
            self._parameters.save(target)
            self._parameters_path = target
            logger.info("Saved workspace → %s", target)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Workspace error", f"Could not save:\n{exc}")

    def edit_workspace(self) -> None:
        dlg = ParametersEditorDialog(self._parameters.to_dict(), self)
        if dlg.exec():
            self._parameters = Parameters.from_dict(
                dlg.get_parameters(self._parameters.to_dict())
            )
            self._on_workspace_changed()

    def open_directory_settings(self) -> None:
        # Directories live in the workspace now; edits stay in memory until the
        # user saves the workspace.
        dlg = DirectorySelectorDialog(self._parameters.directories, self)
        if dlg.exec():
            self._parameters.directories = dlg.get_directories()
            populate_tree(self._tree, self._parameters.data_dir)

    def _on_workspace_changed(self) -> None:
        """Apply edited analysis parameters: re-broadcast and recompute.

        Every dock keeps a reference to the workspace; refresh the references
        and ask the coordinator to refresh the parameter-dependent docks
        (PSD / profile / transfer / spectrogram / results) so the new bands,
        PSD method, RSA and transfer settings take effect immediately.
        """
        import logging
        logging.getLogger("spectHR").setLevel(self._parameters.log_level)
        for widget in self._data_docks.values():
            widget._config = self._parameters   # host owns these docks

        # A respiration-source / per-epoch change means the INH/EXH phases must
        # be recomputed (e.g. switch to the accelerometer PCA); that rebuilds
        # the Session, so re-broadcast it to every dock.  Otherwise just refresh
        # the parameter-dependent docks.
        new_resp_key = self._current_resp_key()
        if self._session is not None and new_resp_key != self._resp_key:
            self._resp_key = new_resp_key
            self._session = recompute_breath_phases(self._session, self._parameters)
            self._scheduler.invalidate()
            for widget in self._data_docks.values():
                widget.set_session(self._session, self._parameters)
        else:
            self._scheduler.invalidate()
            self._coordinator.notify(DataChange.PARAMS)
        # Settings are *not* auto-saved — the user persists them explicitly with
        # Save workspace (Settings menu).  See _restore / save_workspace.

    def _current_resp_key(self) -> tuple:
        """The respiration settings that, when changed, require re-detecting phases."""
        p = self._parameters
        return (p.rsp_source, p.rsp_per_epoch)

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
        self._load_file(Path(data["filename"]))

    def _on_tree_menu(self, position) -> None:
        """Right-click menu on a dataset: reload raw, invert ECG, retrigger."""
        item = self._tree.itemAt(position)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data or data.get("type") != "dataset":
            return

        menu = QMenu(self)
        act_reload = menu.addAction("Reload raw")        # discard cache, re-parse
        act_invert = menu.addAction("Invert ECG polarity")
        act_retrig = menu.addAction("Retrigger R-tops")  # re-detect from scratch
        chosen = menu.exec(self._tree.viewport().mapToGlobal(position))

        if chosen is act_reload:
            self._load_file(Path(data["filename"]), ignore_cache=True)
        elif chosen is act_invert:
            self._reprocess(invert_ecg)
        elif chosen is act_retrig:
            self._reprocess(retrigger_beats)

    def _reprocess(self, transform) -> None:
        """Apply a headless ``Session → Session`` *transform* to the loaded data.

        Used by the tree menu's invert / retrigger actions: run the transform,
        re-broadcast the new session to every dock, invalidate caches and save.
        """
        if self._session is None:
            return
        self.setCursor(Qt.WaitCursor)
        try:
            self._session = transform(self._session, self._parameters)
        except Exception:  # noqa: BLE001 — surface, never crash
            logger.exception("Re-processing failed")
            self.unsetCursor()
            return
        self.unsetCursor()
        for widget in self._data_docks.values():
            widget.set_session(self._session, self._parameters)
        self._scheduler.invalidate()
        self._save_cache()

    def _load_file(self, path: Path, *, ignore_cache: bool = False) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            logger.warning(f"Still loading — ignoring {path.name}")
            return

        self._loaded_raw_path = path
        self._cache_timer.stop()
        cache = self._cache_path(path)
        if ignore_cache and cache.exists():
            cache.unlink()
        actual = cache if (cache.exists() and not ignore_cache) else path
        logger.info(
            f"Loading {path.name} …"
            + (" (from cache)" if actual is cache else "")
        )
        self.setCursor(Qt.WaitCursor)

        self._load_worker = _LoadWorker(actual, self._parameters)
        self._load_thread = QThread(self)
        self._load_worker.moveToThread(self._load_thread)

        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.finished.connect(self._on_session_loaded)
        self._load_worker.failed.connect(self._on_load_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._on_load_thread_finished)

        self._load_thread.start()

    def _on_load_thread_finished(self) -> None:
        """Release the finished loader thread.

        ``deleteLater`` destroys the underlying C++ QThread, so the Python
        references must be dropped here as well — otherwise the next
        ``_load_file`` call would touch a dead wrapper and raise
        ``RuntimeError: Internal C++ object already deleted``.
        """
        if self._load_thread is not None:
            self._load_thread.deleteLater()
        self._load_thread = None
        self._load_worker = None

    def _on_session_loaded(self, session: Session, elapsed: float) -> None:
        self.unsetCursor()
        self._session = session
        logger.info(
            f"Loaded {session.name}  ({elapsed:.2f} s)\n"
            + _session_summary(session)
        )
        self._resp_key = self._current_resp_key()  # baseline for change detection
        self._scheduler.invalidate()  # discard any stale background results
        for widget in self._data_docks.values():
            widget.set_session(session, self._parameters)
        self._apply_dock_availability(session)
        self._add_epoch_act.setEnabled(True)

    def _apply_dock_availability(self, session: Session) -> None:
        """Hide + grey docks whose source channel is absent for *session*.

        E.g. with no blood-pressure channel the BP dock is closed and its
        View-menu entry is disabled; the entry re-enables when a later
        recording carries the channel.  Docks not in ``_DOCK_REQUIRES`` are
        always available.
        """
        for obj_name, available in _DOCK_REQUIRES.items():
            ok = bool(available(session))
            act = self._view_actions.get(obj_name)
            if act is not None:
                act.setEnabled(ok)
            dock = self._docks.get(obj_name)
            if dock is not None and not ok:
                dock.toggleView(False)   # deselect: close the unavailable dock

    def _cache_path(self, raw_path: Path) -> Path:
        """Cache pickle path for a raw recording: ``<cache_dir>/<name>.pkl``."""
        return self._parameters.cache_dir / (raw_path.name + ".pkl")

    def _save_cache(self) -> None:
        """Persist the current (edited) Session to the cache as a pickle.

        Called debounced after a data change.  On the next load of the same
        raw file the cached Session — with the user's edits — is loaded
        instead of re-parsing and re-detecting the raw recording.
        """
        if self._session is None or self._loaded_raw_path is None:
            return
        cache = self._cache_path(self._loaded_raw_path)
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            with open(cache, "wb") as f:
                pickle.dump(self._session, f, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info("Cached edited dataset → %s", cache.name)
        except Exception:  # noqa: BLE001 — caching is best-effort
            logger.exception("Failed to write cache pickle %s", cache)

    def _on_epochs_changed(self, source) -> None:
        """An epoch's active state changed in *source* (e.g. Poincaré checkbox)."""
        self._scheduler.invalidate()
        self._coordinator.notify(DataChange.EPOCHS, source=source)
        self._cache_timer.start()

    def _jump_to_prep_at(self, t: float) -> None:
        """Raise the pre-processing dock and zoom it onto the IBI at time *t*.

        Wired to a dock's ``annotationActivated`` signal — double-clicking a
        Poincaré point jumps to that beat in the editor.
        """
        dock = self._docks.get(_DOCK_PREPROCESSING)
        if dock is not None:
            dock.toggleView(True)
            dock.setAsCurrentTab()
        if self._prep_widget is not None:
            half = 2.0  # a ~4 s window around the beat
            self._prep_widget.apply_window(t - half, t + half)

    def _on_data_edited(self) -> None:
        """React to a committed R-peak edit from the preprocessing dock.

        The edit is already written into ``session.events["hrv"]`` (every dock
        holds the same session reference).  Invalidate the background scheduler
        so heavy derived docks recompute, and ask the coordinator to refresh
        the docks that derive from the R-peaks — skipping the prep dock, which
        has already repainted itself.
        """
        self._scheduler.invalidate()
        self._coordinator.notify(DataChange.HRV, source=self._prep_widget)
        self._cache_timer.start()  # debounced: save edited dataset to cache

    def _on_load_failed(self, path: str, error: str) -> None:
        self.unsetCursor()
        logger.error(f"Failed to load {Path(path).name}: {error}")
        QMessageBox.critical(self, "Load error", f"{Path(path).name}\n\n{error}")

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

    @property
    def _workspace_file(self) -> Path:
        """The single default settings file: ``~/workspace.json``."""
        return Path.home() / "workspace.json"

    def _restore(self) -> None:
        # All settings (analysis parameters + working directories) come from one
        # workspace file in the home directory.  Create it from the built-in
        # defaults on first run so the user has something to edit and save.
        wf = self._workspace_file
        if wf.exists():
            try:
                self._parameters = Parameters.load(wf)
            except Exception as exc:   # noqa: BLE001 — fall back to defaults
                logger.warning("Could not read %s (%s); using defaults.", wf, exc)
        else:
            try:
                self._parameters.save(wf)   # seed with the current defaults
                logger.info("Created default settings file %s", wf)
            except Exception as exc:   # noqa: BLE001 — non-fatal
                logger.warning("Could not create %s: %s", wf, exc)
        self._parameters_path = wf

        self._settings.restore_window(self, self._dock_manager)
        populate_tree(self._tree, self._parameters.data_dir)
        self._on_workspace_changed()   # apply restored parameters

    def closeEvent(self, event) -> None:
        # Only window geometry is persisted automatically; settings changes are
        # kept until the user saves the workspace.
        self._settings.save_window(self, self._dock_manager)
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
