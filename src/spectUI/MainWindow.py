# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import pickle
import sys
import os
import logging

# Force Matplotlib to use the Qt backend inside a PySide6 app (macOS-safe)
os.environ.setdefault("MPLBACKEND", "QtAgg")
import matplotlib

matplotlib.use("QtAgg", force=True)
import webbrowser

from PySide6.QtCore import QFile, Qt
from PySide6.QtGui import QAction, QFont, QTextCursor
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMenu,
    QVBoxLayout,
    QToolButton,
    QTreeWidgetItem,
)


class _QtLogHandler(logging.Handler):
    """Logging handler that appends records to a QPlainTextEdit widget."""

    def __init__(self, widget):
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

from pathlib import Path

from spectHR._version import __version__
from spectHR.DataSet.Epoch import Epoch
from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.Series import CardioSeries
import spectUI as spQt

from spectHR.Tools.Logger import logger


class MainWindow(QMainWindow):
    """
    Main application window for the spectQt ECG pre-processing GUI.

    The workspace dict has two top-level chapters:
        workspace["Directories"]      - DataDirectory, CacheDirectory, OutputDirectory
        workspace["FrequencyAnalysis"] - HRV frequency band configuration
        workspace["CardioParameters"] - IBI classification and ECG preprocessing

    All directory accesses use workspace["Directories"][key].
    """

    def __init__(self):
        super(MainWindow, self).__init__()
        logging.getLogger('matplotlib.font_manager').disabled = True

        # Load the UI file
        base_dir = Path(__file__).parent
        ui_path = base_dir / "resources" / "form.ui"
        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.ReadOnly):
            logger.error("Cannot open UI file:", ui_file.errorString())
            sys.exit(-1)
        loader = QUiLoader()
        self.ui = loader.load(ui_file)
        ui_file.close()

        self.setCentralWidget(self.ui)

        # Route all spectHR log output to the Log tab as well as the console.
        self._log_handler = _QtLogHandler(self.ui.logView)
        logging.getLogger("spectHR").addHandler(self._log_handler)

        self.ui.actionAdd_Epoch.triggered.connect(self.add_epoch)
        self.ui.actionAdd_Epoch.setStatusTip("Add a new epoch spanning the full recording")
        self.ui.actionAdd_Epoch.setToolTip("Add a new epoch spanning the full recording")   
        self.ui.actionAdd_Epoch.setShortcut("Ctrl+N")
        self.setWindowTitle(f"spectHR (v{__version__}) - ECG / HRV Analysis")
        self.resize(1920, 1080)
        self.ui.Splitter.setSizes([200, 1700])

        # Initialize workspace (also applies FrequencyAnalysis bands)
        # Store the path so EditParameters can save back to the same file
        from platformdirs import user_documents_path

        self.workspace_file = user_documents_path() / "DefaultWorkSpace.json"
        self.workspace = spQt.LoadWorkspace(self.workspace_file)
        spQt.PopulateTree(self.ui.treeWidget, self.workspace)

        # Menu wiring - Workspace / Directories
        self.ui.actionOpen_Workspace.triggered.connect(self.OpenWorkSpace)
        self.ui.actionOpen_Workspace.setShortcut("Ctrl+O")
        self.ui.actionOpen_Workspace.setStatusTip("Open a workspace file")
        self.ui.actionOpen_Workspace.setToolTip("Open a workspace file")

        self.ui.actionEdit_Workspace.triggered.connect(self.EditWorkSpace)
        self.ui.actionEdit_Workspace.setShortcut("Ctrl+E")
        self.ui.actionEdit_Workspace.setStatusTip("Edit workspace directories")
        self.ui.actionEdit_Workspace.setToolTip("Edit workspace directories")

        self.ui.actionSettings.triggered.connect(self.EditParameters)
        self.ui.actionSettings.setStatusTip("Edit parameters")
        self.ui.actionSettings.setToolTip("Edit parameters")

        self.ui.actionSave_Workspace.triggered.connect(self.SaveWorkSpace)
        self.ui.actionSave_Workspace.setShortcut("Ctrl+S")
        self.ui.actionSave_Workspace.setStatusTip("Save the current workspace")
        self.ui.actionSave_Workspace.setToolTip("Save the current workspace")

        self.ui.actionDocumentation.triggered.connect(
            lambda: webbrowser.open(
                "https://github.com/markspan/spectHR/blob/V2/readme.MD"
            )
        )
        self.ui.actionDocumentation.setShortcut("Ctrl+D")
        self.ui.actionDocumentation.setStatusTip("Open the spectHR documentation")
        self.ui.actionDocumentation.setToolTip("Open the spectHR documentation")

        self.ui.treeWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.treeWidget.customContextMenuRequested.connect(self.show_context_menu)

        # Embed plot widgets
        self.prep_plot_widget = spQt.PrepPlotWidget()
        layout1 = QVBoxLayout()
        layout1.addWidget(self.prep_plot_widget)
        self.ui.mplPreProcessing.setLayout(layout1)

        self.hr_plot_widget = spQt.HRPlotWidget()
        layout2 = QVBoxLayout()
        layout2.addWidget(self.hr_plot_widget)
        self.ui.mplHRSeries.setLayout(layout2)

        self.poincare_plot_widget = spQt.PoincarePlotWidget()
        layout3 = QVBoxLayout()
        layout3.addWidget(self.poincare_plot_widget)
        self.ui.mplPoincare.setLayout(layout3)

        self.epoch_plot_widget = spQt.EpochPlotWidget()
        layout4 = QVBoxLayout()
        layout4.addWidget(self.epoch_plot_widget)
        self.ui.mplEpochs.setLayout(layout4)

        self.welch_psd_layout = QVBoxLayout()
        self.ui.scrollAreaWidgetContents.setLayout(self.welch_psd_layout)

        # Profile tab uses the same scroll-area-with-content-widget
        # nesting as the PSD tab (defined in form.ui). The layout itself
        # is created here and attached to the content widget so
        # show_profile_plot can swap children in / out the same way
        # show_psd_plot does.
        self.profile_layout = QVBoxLayout()
        self.ui.scrollAreaWidgetContentsProfile.setLayout(self.profile_layout)

        self.parameters_plot_widget = spQt.ParametersPlotWidget()
        layout5 = QVBoxLayout()
        layout5.addWidget(self.parameters_plot_widget)
        self.ui.mplParameters.setLayout(layout5)

        self.ui.treeWidget.itemSelectionChanged.connect(self.on_file_selection)
        self.ui.Views.currentChanged.connect(self.on_tab_changed)

        # Hide the Log tab from the tab strip and pin a toggle button to the
        # top-right corner of the tab bar so it is always visually at the right.
        self._log_tab_index = 7
        self._pre_log_index = 0
        self.ui.Views.tabBar().setTabVisible(self._log_tab_index, False)

        self._log_btn = QToolButton(self.ui.Views)
        self._log_btn.setText("Log")
        self._log_btn.setCheckable(True)
        self._log_btn.setAutoRaise(True)
        self._log_btn.toggled.connect(self._on_log_btn_toggled)
        self.ui.Views.setCornerWidget(self._log_btn, Qt.TopRightCorner)

        self.dataset = None


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
            spQt.PopulateTree(self.ui.treeWidget, self.workspace)

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
            spQt.PopulateTree(self.ui.treeWidget, self.workspace)

    def EditParameters(self):
        """
        Edit all non-directory parameters in the workspace via a dynamic form.

        On OK:
        1. The updated values are written back into self.workspace.
        2. The workspace JSON file is saved immediately so the changes persist.
        3. The CardioMetricsMixin module-level globals are re-applied in-process
           so any subsequent PSD computation uses the new settings without a restart.
        4. The PSD tab is refreshed if a dataset is currently loaded.
        """
        dialog = spQt.ParametersEditorDialog(self.workspace, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            self.workspace = dialog.get_parameters(self.workspace)

            # 1. Save to disk immediately
            try:
                spQt.SaveWorkspace(self.workspace, self.workspace_file)
            except Exception as e:
                logger.warning(f"Could not save workspace after parameter edit: {e}")

            # 2. Rebuild the PsdMethod from the updated workspace and
            #    push it onto every loaded series. The library reads
            #    nothing from globals; each series carries its own
            #    PsdMethod, which is what drives subsequent
            #    psd() / band_power() / band_powers() calls.
            if self.dataset is not None:
                try:
                    psd_method = spQt.psd_method_from_workspace(self.workspace)
                    self.dataset.set_psd_method(psd_method)
                except Exception as e:
                    logger.warning(f"Could not rebuild PsdMethod: {e}")

                # 3. Refresh the PSD and Profile plots immediately if a
                #    dataset is loaded - Profile Settings live in the
                #    same workspace dialog so any band-list / window /
                #    step change has to take effect right away too.
                self.show_psd_plot(self.dataset)
                self.show_profile_plot(self.dataset)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def show_context_menu(self, position):
        item = self.ui.treeWidget.itemAt(position)
        if not item:
            return
        if (
            not item.text(0).lower().endswith(".xdf")
            and not item.text(0).lower().endswith(".txt")
            and not item.text(0).lower().endswith(".evt")
        ):
            return

        context_menu = QMenu(self)
        reload_action = QAction("Reload Raw", self)
        invert_action = QAction("Invert ECG Polarity", self)
        retrigger_action = QAction("Retrigger ECG", self)

        reload_action.triggered.connect(lambda: self.reload(item))
        invert_action.triggered.connect(self.invert)
        retrigger_action.triggered.connect(self.retrigger)

        context_menu.addAction(reload_action)
        context_menu.addAction(invert_action)
        context_menu.addAction(retrigger_action)
        context_menu.exec_(self.ui.treeWidget.viewport().mapToGlobal(position))

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

        import numpy as np

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
        import os

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
    # Tab / file selection handlers
    # ------------------------------------------------------------------

    def _on_log_btn_toggled(self, checked):
        """Show the Log page when the corner button is pressed, restore on release."""
        if checked:
            self._pre_log_index = self.ui.Views.currentIndex()
            self.ui.Views.setCurrentIndex(self._log_tab_index)
        else:
            self.ui.Views.setCurrentIndex(self._pre_log_index)

    def on_tab_changed(self, index):
        # Tab order in form.ui (`Views` QTabWidget):
        #   0 - Preprocessing
        #   1 - IBI Series
        #   2 - Poincaré
        #   3 - Epochs
        #   4 - PSD
        #   5 - Profiles
        #   6 - Parameters
        #   7 - Log  (hidden from tab strip; driven by the corner-widget button)
        # Keep the Log button checked state in sync when a regular tab is clicked.
        self._log_btn.blockSignals(True)
        self._log_btn.setChecked(index == self._log_tab_index)
        self._log_btn.blockSignals(False)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        if self.dataset is not None:
            self.dataset.save(self.savename)
        if index == 1 and self.dataset is not None:
            self.show_hr_plot(self.dataset)
        if index == 2 and self.dataset is not None:
            self.show_poincare_plot(self.dataset)
        if index == 3 and self.dataset is not None:
            self.show_epoch_plot(self.dataset)
        if index == 4 and self.dataset is not None:
            self.show_psd_plot(self.dataset)
        if index == 5 and self.dataset is not None:
            self.show_profile_plot(self.dataset)
        if index == 6 and self.dataset is not None:
            self.show_parameters_plot(self.dataset)
        QApplication.restoreOverrideCursor()

    def on_file_selection(self):
        selected_items = self.ui.treeWidget.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        meta = item.data(0, Qt.UserRole)
        if meta is None:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        dirs = self.workspace["Directories"]

        # ── CASE 1: Dataset root node ─────────────────────────────────
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

                    # ----------------------------------------------------------
                    # Migration 1: locked R-tops saved without IBI classification
                    # ----------------------------------------------------------
                    # Cached datasets saved before the locked-branch classify_ibi()
                    # fix have all R-top labels at the default "N" - an impossible
                    # result for real ECG data of any length.  Re-classify in place;
                    # no ECG re-filtering needed.
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

                    # ----------------------------------------------------------
                    # Migration 2: CARSPAN epoch-start convention
                    # ----------------------------------------------------------
                    # Cached datasets saved before the epoch-start fix have epoch
                    # starts equal to the EVT marker time (e.g. 313.900 s) instead
                    # of the last R-peak before the marker (e.g. 313.096 s).
                    #
                    # Detection: if any non-experiment epoch's start time matches a
                    # "Start Epoch #N" time in the TaskSeries EventSeries, the old
                    # convention is still in use.
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
                                    # Only adjust epochs whose start still matches
                                    # a marker time (leaves manually-edited epochs
                                    # that don't match any marker time untouched).
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
            # Push the current PsdMethod onto every series in the dataset
            # so subsequent psd() / band_power() calls have a config to
            # read from. Library code never touches workspace JSON.
            try:
                psd_method = spQt.psd_method_from_workspace(self.workspace)
                self.dataset.set_psd_method(psd_method)
            except Exception as e:
                logger.warning(f"Could not attach PsdMethod to dataset: {e}")
            if hasattr(dataset, "has_ecg") and dataset.has_ecg:
                self.show_preprocessing_plot(self.dataset)
                self.ui.Views.setTabVisible(0, True)
            else:
                self.ui.Views.setTabVisible(0, False)
                self.show_hr_plot(self.dataset)

            self.show_poincare_plot(self.dataset)
            self.show_epoch_plot(self.dataset)
            self.show_psd_plot(self.dataset)
            self.show_profile_plot(self.dataset)
            self.show_parameters_plot(self.dataset)
            QApplication.restoreOverrideCursor()
            return

        # ── CASE 2: Band node ─────────────────────────────────────────
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
            try:
                psd_method = spQt.psd_method_from_workspace(self.workspace)
                self.dataset.set_psd_method(psd_method)
            except Exception as e:
                logger.warning(f"Could not attach PsdMethod to dataset: {e}")
            self.show_preprocessing_plot(self.dataset)
            self.show_hr_plot(self.dataset)
            self.show_poincare_plot(self.dataset)
            self.show_epoch_plot(self.dataset)
            self.show_psd_plot(self.dataset)
            self.show_profile_plot(self.dataset)
            self.show_parameters_plot(self.dataset)
            QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------------
    # Plot helpers
    # ------------------------------------------------------------------

    def show_preprocessing_plot(self, data):
        if data.has_ecg:
            self.ui.Views.setTabVisible(0, True)
            self.ui.Views.setCurrentIndex(0)
            self.prep_plot_widget.prepPlot(data)
        else:
            self.ui.Views.setTabVisible(0, False)
            self.ui.Views.setCurrentIndex(1)

    def show_hr_plot(self, data):
        if data is not None:
            self.hr_plot_widget.hrPlot(data)

    def show_epoch_plot(self, data):
        if data is not None:
            self.epoch_plot_widget.plotEpochs(data)

    def show_poincare_plot(self, data):
        if data is not None:
            self.poincare_plot_widget.poincarePlot(data)

    def show_psd_plot(self, dataset):
        # Clear existing widgets
        while self.welch_psd_layout.count():
            item = self.welch_psd_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        # Collect active epochs
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

        # Create container widget with all plots and uniform scaling.
        # ``workspace`` is forwarded so PrintScreen knows where to save.
        psd_widget = spQt.PSDPlotWidget(views, labels, workspace=self.workspace)
        self.welch_psd_layout.addWidget(psd_widget)

    def show_profile_plot(self, dataset):
        """Same epoch-collection contract as :meth:`show_psd_plot`, but
        builds a :class:`ProfilePlotWidget` instead - one sliding-window
        band-power profile per epoch, drawn into the Profiles tab.
        """
        # Clear existing widgets - same swap-out pattern as the PSD tab.
        while self.profile_layout.count():
            item = self.profile_layout.takeAt(0)
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
        profile_widget = spQt.ProfilePlotWidget(
            views, labels, workspace=self.workspace,
        )
        self.profile_layout.addWidget(profile_widget)

    def show_parameters_plot(self, data):
        if data is not None:
            self.parameters_plot_widget.display_parameters(data, self.workspace)

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
        self.dataset.epochs[epoch_label] = Epoch(
            active=True, start=start_time, end=end_time
        )
        self.epoch_plot_widget.plotEpochs(self.dataset)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    default_font = QFont("Segoe UI", 12)
    default_font.setBold(False)
    app.setStyle("WindowsVista")
    app.setFont(default_font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
