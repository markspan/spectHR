# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectUI main window.

A thin orchestrator that wires the collaborators together; the bulky pieces
live in sibling modules:

* :mod:`spectUI.docks` - dock layout constants, specs and the placeholder.
* :mod:`spectUI.menu_bar` - menu bar + toolbar construction.
* :mod:`spectUI.session_loader` - background file loading (worker + thread).
* :mod:`spectUI.session_cache` - the edited-session pickle cache.
* :mod:`spectUI.plot_export` - export the open dock figures.
* :mod:`spectUI.coordinator` - dependency-aware dock refresh + window sync.

Dock layout
-----------
Left:   workspace file browser (QTreeWidget).
Centre: tabified plot docks (some still placeholders).
Bottom: log output (hidden by default).
"""
from __future__ import annotations

import sys
from pathlib import Path

from platformdirs import user_config_dir
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QWidget,
)
from PySide6QtAds import CDockManager, CDockWidget, DockWidgetArea

from spectHR._version import __version__
from spectHR.dataset.preprocessing import (
    invert_ecg,
    recompute_breath_phases,
    retrigger_beats,
    retrigger_beats_per_epoch,
)
from spectHR.logger import logger
from spectHR.session import Session
from spectUI import menu_bar, plot_export, session_cache
from spectUI.coordinator import DataChange, DataCoordinator
from spectUI.docks import (
    CENTRE_DOCKS,
    DOCK_BP,
    DOCK_EPOCHS,
    DOCK_HR,
    DOCK_LOG,
    DOCK_POINCARE,
    DOCK_PREPROCESSING,
    DOCK_PROFILES,
    DOCK_PSD,
    DOCK_REQUIRES,
    DOCK_RESULTS,
    DOCK_SPECTROGRAM,
    DOCK_SPECTROGRAM3D,
    DOCK_TRANSFER,
    DOCK_TRANSFERPROFILE,
    DOCK_WORKSPACE,
    VIEW_LABELS,
    Placeholder,
    build_data_specs,
)
from spectUI.parameters import Parameters, populate_tree
from spectUI.perspectives import (
    BUILTIN_COMPARE,
    BUILTIN_DEFAULT,
    BUILTIN_PSDFOCUS,
)
from spectUI.plot_worker import DockScheduler
from spectUI.session_loader import SessionLoader, session_summary
from spectUI.settings import AppSettings
from spectUI.widgets.log_widget import LogWidget
from spectUI.widgets.timeline.base import TimelineView
from spectUI.widgets.workspace_editor import DirectorySelectorDialog, ParametersEditorDialog


# ---------------------------------------------------------------------------
# Backward-compatible aliases
#
# The dock object-name constants moved to :mod:`spectUI.docks`; keep the old
# ``_DOCK_*`` / ``_VIEW_LABELS`` names bound here so existing tests and scripts
# that reference e.g. ``spectUI.main_window._DOCK_BP`` keep working.
# ---------------------------------------------------------------------------

_DOCK_WORKSPACE       = DOCK_WORKSPACE
_DOCK_PREPROCESSING   = DOCK_PREPROCESSING
_DOCK_HR              = DOCK_HR
_DOCK_BP              = DOCK_BP
_DOCK_POINCARE        = DOCK_POINCARE
_DOCK_EPOCHS          = DOCK_EPOCHS
_DOCK_PSD             = DOCK_PSD
_DOCK_SPECTROGRAM     = DOCK_SPECTROGRAM
_DOCK_SPECTROGRAM3D   = DOCK_SPECTROGRAM3D
_DOCK_TRANSFER        = DOCK_TRANSFER
_DOCK_TRANSFERPROFILE = DOCK_TRANSFERPROFILE
_DOCK_PROFILES        = DOCK_PROFILES
_DOCK_RESULTS         = DOCK_RESULTS
_DOCK_LOG             = DOCK_LOG
_VIEW_LABELS          = VIEW_LABELS


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
        self._parameters      = Parameters.default()
        self._parameters_path: Path | None = None
        # Respiration settings last applied to the loaded Session's breath
        # phases; a change triggers a re-detection in _on_workspace_changed.
        self._resp_key: tuple | None = None
        self._session:         Session | None = None
        self._prep_widget:     QWidget | None = None
        self._loaded_raw_path: Path | None = None  # the raw file behind the cache

        self._docks: dict[str, CDockWidget] = {}
        # Live data docks (those that take a Session), keyed by object name.
        self._data_docks: dict[str, QWidget] = {}

        # Background loader (owns its worker + thread lifecycle).
        self._loader = SessionLoader(self)
        self._loader.loaded.connect(self._on_session_loaded)
        self._loader.failed.connect(self._on_load_failed)

        # Debounced "data changed → save edited Session to the cache" timer.
        self._cache_timer = QTimer(self)
        self._cache_timer.setSingleShot(True)
        self._cache_timer.setInterval(1500)
        self._cache_timer.timeout.connect(self._save_cache)

        self._build_docks()
        menu_bar.build_menu_and_toolbar(self)
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
        self._add_dock(DOCK_WORKSPACE, "Workspace", self._tree,
                       DockWidgetArea.LeftDockWidgetArea)

        # Which centre docks are live (take a Session) and what each derives
        # from; the coordinator refreshes a dock when its dependencies change.
        # Docks not listed here are still placeholders.
        data_specs = build_data_specs()

        # Centre: tabified plot docks.
        reference_area = None
        for obj_name, title in CENTRE_DOCKS:
            spec = data_specs.get(obj_name)
            if spec is not None:
                factory, depends = spec
                widget = factory()
                self._register_data_dock(obj_name, widget, depends)
            else:
                widget = Placeholder(title)
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
        log_dock = self._add_dock(DOCK_LOG, "Log", self._log_widget,
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
        if obj_name == DOCK_PREPROCESSING:
            self._prep_widget = widget
            widget.dataEdited.connect(self._on_data_edited)
        # Optional cross-dock signals (Poincaré and future editors).
        if hasattr(widget, "epochsChanged"):
            widget.epochsChanged.connect(
                lambda w=widget: self._on_epochs_changed(w)
            )
        if hasattr(widget, "annotationActivated"):
            widget.annotationActivated.connect(self._jump_to_prep_at)
        if hasattr(widget, "plotsExportRequested"):
            widget.plotsExportRequested.connect(self._export_plots)

    # ------------------------------------------------------------------
    # Built-in perspectives
    # ------------------------------------------------------------------

    def _capture_builtin_perspectives(self) -> None:
        self._dock_manager.addPerspective(BUILTIN_DEFAULT)

        epochs = self._docks.get(DOCK_EPOCHS)
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
            self._parameters.merge_from_file(path)
            self._parameters_path = Path(path)
        except Exception as exc:
            QMessageBox.critical(self, "Workspace error", str(exc))
            return
        populate_tree(self._tree, self._parameters.data_dir)
        self._on_workspace_changed()

    def save_workspace(self) -> None:
        """Persist the current settings to a chosen file (Save-As dialog).

        Defaults to the file the settings came from (``~/workspace.json`` on a
        fresh run); the user may save a named copy elsewhere instead.
        """
        default = str(self._parameters_path or self._workspace_file)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save settings", default,
            "Workspace (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            self._parameters.save(path)
            self._parameters_path = Path(path)
            logger.info("Saved workspace → %s", path)
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
            self._coordinator.set_session(self._session, self._parameters)
        else:
            self._scheduler.invalidate()
            # Keep the coordinator's params current so a dock opened later
            # applies its pending session with the new parameters.
            self._coordinator.set_config(self._parameters)
            self._coordinator.notify(DataChange.PARAMS)
        # Settings are *not* auto-saved, the user persists them explicitly with
        # Save workspace (Settings menu).  See _restore / save_workspace.

    def _current_resp_key(self) -> tuple:
        """The respiration settings that, when changed, require re-detecting phases."""
        p = self._parameters
        return (p.rsp_source, p.rsp_per_epoch)

    def _export_plots(self, directory: str) -> None:
        """Save the open dock plots as files into *directory* (via a dialog)."""
        plot_export.export_dock_plots(
            self,
            self._data_docks,
            VIEW_LABELS,
            getattr(self._session, "name", "") or "",
            directory,
        )

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
        act_retrig       = menu.addAction("Retrigger R-tops")              # whole recording
        act_retrig_epoch = menu.addAction("Retrigger R-tops (per epoch)")  # active epochs only
        chosen = menu.exec(self._tree.viewport().mapToGlobal(position))

        if chosen is act_reload:
            self._load_file(Path(data["filename"]), ignore_cache=True)
        elif chosen is act_invert:
            self._reprocess(invert_ecg)
        elif chosen is act_retrig:
            self._reprocess(retrigger_beats)
        elif chosen is act_retrig_epoch:
            self._reprocess(retrigger_beats_per_epoch)

    def _reprocess(self, transform) -> None:
        """Apply a headless ``Session → Session`` *transform* to the loaded data.

        Used by the tree menu's invert / retrigger actions: run the transform,
        re-broadcast the new session to every dock, invalidate caches and save.
        The prep dock's scroll window is preserved across the rebuild.
        """
        if self._session is None:
            return
        prep_window = (
            self._prep_widget.current_window() if self._prep_widget is not None else None
        )
        self.setCursor(Qt.WaitCursor)
        try:
            self._session = transform(self._session, self._parameters)
            # A fresh detection changes the R-top coverage, e.g. retriggering
            # over the whole recording on an EVT file that only annotated event
            # windows.  Re-evaluate the INH/EXH breath phases so they span the
            # new coverage instead of staying limited to the original R-tops.
            self._session = recompute_breath_phases(self._session, self._parameters)
        except Exception:  # noqa: BLE001, surface, never crash
            logger.exception("Re-processing failed")
            self.unsetCursor()
            return
        self.unsetCursor()
        self._scheduler.invalidate()
        self._coordinator.set_session(self._session, self._parameters)
        if prep_window is not None and self._prep_widget is not None:
            self._prep_widget.apply_window(*prep_window)
        self._save_cache()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_file(self, path: Path, *, ignore_cache: bool = False) -> None:
        if self._loader.is_running():
            logger.warning(f"Still loading, ignoring {path.name}")
            return

        self._loaded_raw_path = path
        self._cache_timer.stop()
        cache = session_cache.cache_path(self._parameters.cache_dir, path)
        if ignore_cache and cache.exists():
            cache.unlink()
        actual = cache if (cache.exists() and not ignore_cache) else path
        logger.info(
            f"Loading {path.name} …"
            + (" (from cache)" if actual is cache else "")
        )
        self.setCursor(Qt.WaitCursor)
        self._loader.start(actual, self._parameters)

    def _on_session_loaded(self, session: Session, elapsed: float) -> None:
        self.unsetCursor()
        self._session = session
        logger.info(
            f"Loaded {session.name}  ({elapsed:.2f} s)\n"
            + session_summary(session)
        )
        self._resp_key = self._current_resp_key()  # baseline for change detection
        self._scheduler.invalidate()  # discard any stale background results
        # Only the visible docks compute now; hidden ones apply the session when
        # first opened (see DataCoordinator.set_session / widget_shown).
        self._coordinator.set_session(session, self._parameters)
        self._apply_dock_availability(session)

    def _apply_dock_availability(self, session: Session) -> None:
        """Hide + grey docks whose source channel is absent for *session*.

        E.g. with no blood-pressure channel the BP dock is closed and its
        View-menu entry is disabled; the entry re-enables when a later
        recording carries the channel.  Docks not in ``DOCK_REQUIRES`` are
        always available.
        """
        for obj_name, available in DOCK_REQUIRES.items():
            ok = bool(available(session))
            act = self._view_actions.get(obj_name)
            if act is not None:
                act.setEnabled(ok)
            dock = self._docks.get(obj_name)
            if dock is not None and not ok:
                dock.toggleView(False)   # deselect: close the unavailable dock

    def _on_load_failed(self, path: str, error: str) -> None:
        self.unsetCursor()
        logger.error(f"Failed to load {Path(path).name}: {error}")
        QMessageBox.critical(self, "Load error", f"{Path(path).name}\n\n{error}")

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _save_cache(self) -> None:
        """Persist the current (edited) Session to the cache as a pickle.

        Called debounced after a data change.  On the next load of the same
        raw file the cached Session, with the user's edits, is loaded instead
        of re-parsing and re-detecting the raw recording.
        """
        if self._session is None or self._loaded_raw_path is None:
            return
        path = session_cache.cache_path(self._parameters.cache_dir, self._loaded_raw_path)
        session_cache.write_session_cache(self._session, path)

    # ------------------------------------------------------------------
    # Cross-dock events
    # ------------------------------------------------------------------

    def _on_epochs_changed(self, source) -> None:
        """An epoch's active state changed in *source* (e.g. Poincaré checkbox)."""
        self._scheduler.invalidate()
        self._coordinator.notify(DataChange.EPOCHS, source=source)
        self._cache_timer.start()

    def _jump_to_prep_at(self, t: float) -> None:
        """Raise the pre-processing dock and zoom it onto the IBI at time *t*.

        Wired to a dock's ``annotationActivated`` signal, double-clicking a
        Poincaré point jumps to that beat in the editor.
        """
        dock = self._docks.get(DOCK_PREPROCESSING)
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
        the docks that derive from the R-peaks, skipping the prep dock, which
        has already repainted itself.
        """
        self._scheduler.invalidate()
        self._coordinator.notify(DataChange.HRV, source=self._prep_widget)
        self._cache_timer.start()  # debounced: save edited dataset to cache

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
        """The single default settings file in the OS config directory."""
        cfg_dir = user_config_dir("spectHR")
        logger.info(f"Workspace file in: {cfg_dir}")
        return Path(cfg_dir) / "workspace.json"

    def _restore(self) -> None:
        # All settings (analysis parameters + working directories) come from one
        # workspace file in the home directory.  Create it from the built-in
        # defaults on first run so the user has something to edit and save.
        wf = self._workspace_file
        if wf.exists():
            try:
                self._parameters = Parameters.load(wf)
            except Exception as exc:   # noqa: BLE001, fall back to defaults
                logger.warning("Could not read %s (%s); using defaults.", wf, exc)
        else:
            try:
                self._parameters.save(wf)   # seed with the current defaults
                logger.info("Created default settings file %s", wf)
            except Exception as exc:   # noqa: BLE001, non-fatal
                logger.warning("Could not create %s: %s", wf, exc)
        self._parameters_path = wf

        self._settings.restore_window(self, self._dock_manager)
        # Restore the user's saved perspectives (named layouts); rebuild the
        # Layout menu so the restored entries appear.
        if self._settings.load_perspectives(self._dock_manager):
            self._perspective_menu.rebuild()
        populate_tree(self._tree, self._parameters.data_dir)
        self._on_workspace_changed()   # apply restored parameters

    def closeEvent(self, event) -> None:
        # Window geometry, the live dock layout and the saved perspectives are
        # persisted automatically; analysis settings are kept until the user
        # saves the workspace.
        self._settings.save_window(self, self._dock_manager)
        self._settings.save_perspectives(self._dock_manager)
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
