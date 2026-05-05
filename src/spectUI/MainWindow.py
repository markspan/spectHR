import json
import pickle
import sys
import os
import logging

# Force Matplotlib to use the Qt backend inside a PySide6 app (macOS-safe)
os.environ.setdefault("MPLBACKEND", "QtAgg")
import matplotlib

matplotlib.use("QtAgg", force=True)
import matplotlib.pyplot as plt
import webbrowser

from PySide6.QtCore import QFile, Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMenu,
    QVBoxLayout,
    QMessageBox,
    QTreeWidgetItem,
)

from pathlib import Path

from spectHR.DataSet.Epoch import Epoch
from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.Series import CardioSeries
import spectUI as spQt

# NOTE: cannot use "import ... as _mixin" here — the Series __init__.py re-exports
# the class CardioMetricsMixin under that name, so Python resolves the alias to the
# class instead of the module.  We import the module explicitly by full name and then
# retrieve it from sys.modules at call time to get the real module object.
import spectHR.DataSet.Series.CardioMetricsMixin  # ensure the module is loaded
import spectHR.DataSet.Series.CardioFrequencyMetricsMixin  # ensure the module is loaded

def _cm():
    """Return the CardioMetricsMixin *module* (never the class)."""
    return sys.modules["spectHR.DataSet.Series.CardioMetricsMixin"]


from spectHR.Tools.Logger import logger


class MainWindow(QMainWindow):
    """
    Main application window for the spectQt ECG pre-processing GUI.

    The workspace dict has two top-level chapters:
        workspace["Directories"]      — DataDirectory, CacheDirectory, OutputDirectory
        workspace["FrequencyAnalysis"] — HRV frequency band configuration
        workspace["CardioParameters"] — IBI classification and ECG preprocessing

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
        self.ui.actionAdd_Epoch.triggered.connect(self.add_epoch)
        self.ui.actionAdd_Epoch.setStatusTip("Add a new epoch spanning the full recording")
        self.ui.actionAdd_Epoch.setToolTip("Add a new epoch spanning the full recording")   
        self.ui.actionAdd_Epoch.setShortcut("Ctrl+N")
        self.setWindowTitle("spectHR (v1.1.11) - ECG / HRV Analysis")
        self.resize(1920, 1080)
        self.ui.Splitter.setSizes([200, 1700])

        # Initialize workspace (also applies FrequencyAnalysis bands)
        # Store the path so EditParameters can save back to the same file
        from platformdirs import user_documents_path

        self.workspace_file = user_documents_path() / "DefaultWorkSpace.json"
        self.workspace = spQt.LoadWorkspace(self.workspace_file)
        spQt.PopulateTree(self.ui.treeWidget, self.workspace)

        # Menu wiring — Workspace / Directories
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

        self.parameters_plot_widget = spQt.ParametersPlotWidget()
        layout5 = QVBoxLayout()
        layout5.addWidget(self.parameters_plot_widget)
        self.ui.mplParameters.setLayout(layout5)

        self.ui.treeWidget.itemSelectionChanged.connect(self.on_file_selection)
        self.ui.Views.currentChanged.connect(self.on_tab_changed)

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

            # 2. Re-apply FrequencyAnalysis globals in-process
            fa = self.workspace.get("FrequencyAnalysis", {})
            try:
                _cm().load_frequency_bands(fa["bands"])
            except Exception as e:
                logger.warning(f"Could not apply frequency bands: {e}")
            try:
                _cm().load_welch_params(fa["welch"])
            except Exception as e:
                logger.warning(f"Could not apply Welch params: {e}")
            try:
                _cm().load_lombscargle_params(fa["lombscargle"])
            except Exception as e:
                logger.warning(f"Could not apply Lomb-Scargle params: {e}")
            try:
                _cm().load_carspan_params(fa["carspan"])  # <-- was missing
            except Exception as e:
                logger.warning(f"Could not apply CARSPAN params: {e}")
            try:
                _cm().load_method(fa["method"])
            except Exception as e:
                logger.warning(f"Could not apply PSD method: {e}")
            try:
                _cm().load_ci_alpha(fa["confidence_interval_alpha"])
            except Exception as e:
                logger.warning(f"Could not apply CI alpha: {e}")

            # 3. Refresh the PSD plot immediately if a dataset is loaded
            if self.dataset is not None:
                self.show_psd_plot(self.dataset)

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
        self.dataset.preprocess_ecg()
        self.dataset.save(self.savename)
        self.show_preprocessing_plot(self.dataset)

    # ------------------------------------------------------------------
    # Tab / file selection handlers
    # ------------------------------------------------------------------

    def on_tab_changed(self, index):
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
                        dataset.preprocess_ecg()
                    if dataset.active_band is None and dataset.band_map:
                        dataset.active_band = next(iter(dataset.band_map))
                    dataset.save(self.savename)
                else:
                    _resaved = False

                    # ----------------------------------------------------------
                    # Migration 1: locked R-tops saved without IBI classification
                    # ----------------------------------------------------------
                    # Cached datasets saved before the locked-branch classify_ibi()
                    # fix have all R-top labels at the default "N" — an impossible
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
                    dataset.preprocess_ecg()
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
            if hasattr(dataset, "has_ecg") and dataset.has_ecg:
                self.show_preprocessing_plot(self.dataset)
                self.ui.Views.setTabVisible(0, True)
            else:
                self.ui.Views.setTabVisible(0, False)
                self.show_hr_plot(self.dataset)

            self.show_poincare_plot(self.dataset)
            self.show_epoch_plot(self.dataset)
            self.show_psd_plot(self.dataset)
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
            self.show_preprocessing_plot(self.dataset)
            self.show_hr_plot(self.dataset)
            self.show_poincare_plot(self.dataset)
            self.show_epoch_plot(self.dataset)
            self.show_psd_plot(self.dataset)
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
