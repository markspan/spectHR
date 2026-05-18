from pathlib import Path
import csv
import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spectHR.Tools.Logger import logger


class ParametersPlotWidget(QWidget):
    """
    A QWidget that displays calculated HRV parameters in a spreadsheet-like table.

    The output CSV path is read from workspace["Directories"]["OutputDirectory"].

    Saving emits three CSV files, all wide / one-row-per-epoch so they
    drop straight into R / JASP / SPSS without any list-column parsing:

    - ``{basename}.csv`` — time-domain HRV metrics per epoch.
    - ``{basename}_psd.csv`` — frequency-domain band powers per epoch
      (one column per configured band).
    - ``{basename}_profiles.csv`` — sliding-window band-power profile
      collapsed to per-band summary statistics per epoch
      (``<band>_mean / _std / _min / _max / _t_max``). The full
      time-resolved curve is *not* exported by design — keeping every
      file at one-row-per-epoch is what makes them importable to the
      statistics packages above without bespoke pre-processing.

    The two extra files only carry the columns that make sense for the
    epoch's configuration; if an epoch's PSD or profile fails to compute
    (too few R-peaks, no PSD method set, etc.) the failure is logged and
    that row's per-band cells stay empty so the rest of the table still
    saves.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowTitle("Parameters Plot")

        self.table_widget = QTableWidget()
        self.main_layout = QVBoxLayout(self)
        self.setLayout(self.main_layout)
        self.main_layout.addWidget(self.table_widget)

        self.button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_data)
        self.button_layout.addWidget(self.save_button)
        self.main_layout.addLayout(self.button_layout)

        self.headers: list[str] = []
        self.data: np.ndarray | None = None
        self.csvfile: Path | None = None
        self.psd_csvfile: Path | None = None
        self.profile_csvfile: Path | None = None
        self.workspace: dict | None = None

    def display_parameters(self, dataset, workspace):
        self.dataset = dataset
        self.workspace = workspace
        output_dir = workspace["Directories"]["OutputDirectory"]
        self.csvfile = Path(output_dir) / f"{dataset.basename}.csv"
        self.psd_csvfile = Path(output_dir) / f"{dataset.basename}_psd.csv"
        self.profile_csvfile = (
            Path(output_dir) / f"{dataset.basename}_profiles.csv"
        )
        self.setFocus()

        labels, cols, values = self.dataset.hrv.hrv_epoch_table(self.dataset)

        subject = getattr(dataset, "basename", None)
        n_rows = int(labels.shape[0])
        n_metrics = int(values.shape[1]) if values.size else 0

        self.headers = ["Subject", "epoch"] + list(cols)
        self.data = np.empty((n_rows, 2 + n_metrics), dtype=object)
        self.data[:, 0] = subject
        self.data[:, 1] = labels
        if n_metrics:
            self.data[:, 2:] = values

        self.table_widget.clear()
        self.table_widget.setRowCount(n_rows)
        self.table_widget.setColumnCount(len(self.headers))
        self.table_widget.setHorizontalHeaderLabels(self.headers)

        for i in range(n_rows):
            for j in range(len(self.headers)):
                v = self.data[i, j]
                if isinstance(v, (float, np.floating)) and np.isnan(v):
                    txt = ""
                elif isinstance(v, str):
                    txt = v
                elif isinstance(v, (int, np.integer)):
                    txt = str(int(v))
                elif isinstance(v, (float, np.floating)):
                    txt = f"{float(v):.5f}"
                else:
                    txt = "" if v is None else str(v)
                self.table_widget.setItem(i, j, QTableWidgetItem(txt))

        self.table_widget.resizeColumnsToContents()

    def save_data(self):
        if self.csvfile is None or self.data is None:
            return
        with self.csvfile.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self.headers)
            for row in self.data:
                out = []
                for v in row:
                    if isinstance(v, (float, np.floating)) and np.isnan(v):
                        out.append("")
                    elif isinstance(v, (float, np.floating)):
                        out.append(f"{float(v):.5f}")
                    else:
                        out.append("" if v is None else str(v))
                w.writerow(out)

        # Spectral companion files — best-effort. A failure to compute
        # band powers or a profile for any single epoch is logged and
        # leaves that epoch's per-band cells empty; a wholesale failure
        # of the whole pass (e.g. no PSD method set on the series) is
        # logged and skipped without affecting the time-domain CSV that
        # was already written.
        try:
            self._save_psd_csv()
        except Exception as exc:                  # pragma: no cover
            logger.warning(f"PSD CSV export failed: {exc}")
        try:
            self._save_profile_csv()
        except Exception as exc:                  # pragma: no cover
            logger.warning(f"Profile CSV export failed: {exc}")

    # ------------------------------------------------------------------
    # Spectral companion CSVs — one row per epoch, wide layout
    # ------------------------------------------------------------------

    def _iter_active_epochs(self):
        """Yield ``(label, epoch)`` pairs for every active epoch, in
        the same order the time-domain table uses.

        Mirrors the iteration inside ``CardioSeries.hrv_epoch_table`` so
        the row order of the three CSVs lines up — joining them in R or
        SPSS on ``epoch`` then becomes a simple one-to-one merge.
        """
        for label, epoch in self.dataset.epochs.items():
            if getattr(epoch, "active", False):
                yield label, epoch

    def _resolve_psd_bands(self) -> list[str]:
        """Bands to include as columns, in the workspace's display order.

        Reads ``FrequencyAnalysis.bands`` from the workspace. Falls back
        to whatever ``series.band_powers()`` returns the first time it
        succeeds — handy when the workspace lookup failed but the series
        still has a default :class:`PsdMethod` attached.
        """
        if self.workspace is None:
            return []
        bands = (
            (self.workspace.get("FrequencyAnalysis", {}) or {})
            .get("bands", {}) or {}
        )
        return list(bands.keys())

    def _save_psd_csv(self) -> None:
        """Write ``{basename}_psd.csv`` — one row per epoch, one column per band.

        Columns: ``Subject, epoch, method, <band1>_power, <band2>_power, ...``.
        Units match the active PSD method's band-power unit (typically
        ``mMI²``); the unit string is recorded once per row in the
        ``unit`` column so downstream readers don't have to guess.
        """
        if self.psd_csvfile is None:
            return
        hrv = getattr(self.dataset, "hrv", None)
        if hrv is None:
            logger.warning(
                "PSD CSV: dataset has no .hrv series; skipping export."
            )
            return

        bands = self._resolve_psd_bands()
        subject = getattr(self.dataset, "basename", "")

        rows: list[dict] = []
        for label, _ep in self._iter_active_epochs():
            row: dict[str, object] = {
                "Subject": subject,
                "epoch": label,
                "method": "",
                "unit": "",
            }
            for name in bands:
                row[f"{name}_power"] = None
            try:
                view = hrv[label]
                powers = view.band_powers()
                # ``view.psd()`` would re-compute the full PSD just to
                # get the method name; pull it off the resolved method
                # instead to avoid that cost.
                method = getattr(view, "psd_method", None) or getattr(
                    hrv, "psd_method", None
                )
                if method is not None:
                    row["method"] = getattr(method, "algorithm", "")
                    # Band-power unit comes from a single ``psd()`` call;
                    # cheap compared to the band-powers loop above and
                    # guarantees the recorded unit matches the values.
                    try:
                        psd_res = view.psd(with_ci=False)
                        row["unit"] = (psd_res.unit or "").replace("/Hz", "")
                    except Exception:
                        pass
                for name in bands:
                    if name in powers:
                        row[f"{name}_power"] = float(powers[name])
                # If the workspace had no bands but the series produced
                # some, fall back to the series' own band names so the
                # row isn't empty.
                if not bands:
                    for name, value in powers.items():
                        row[f"{name}_power"] = float(value)
            except Exception as exc:
                logger.warning(
                    f"PSD CSV: epoch {label!r} failed: {exc}"
                )
            rows.append(row)

        # Collect the full column set from every row so a late-arriving
        # band (the fallback path above) doesn't get dropped.
        header_set: list[str] = ["Subject", "epoch", "method", "unit"]
        for row in rows:
            for key in row:
                if key not in header_set:
                    header_set.append(key)

        with self.psd_csvfile.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header_set)
            for row in rows:
                w.writerow(
                    [self._format_cell(row.get(key)) for key in header_set]
                )

    def _save_profile_csv(self) -> None:
        """Write ``{basename}_profiles.csv`` — per-band summary stats per epoch.

        Each profile is a 2-D ``(n_bands × n_windows)`` array; to fit
        one row per epoch the time axis is collapsed to five scalars
        per band: ``mean`` / ``std`` / ``min`` / ``max`` / ``t_max``
        (epoch-relative time of the maximum, in seconds). The
        ``n_windows`` column records how many sliding windows fitted
        inside the epoch so a downstream reader can spot epochs that
        were too short for the configured window length.

        The window / step lengths used for the compute are recorded in
        every row as ``window_sec`` / ``step_sec`` — they normally do
        not vary across epochs in a single export but recording them
        per-row keeps each row self-describing.
        """
        if self.profile_csvfile is None or self.workspace is None:
            return
        hrv = getattr(self.dataset, "hrv", None)
        if hrv is None:
            logger.warning(
                "Profile CSV: dataset has no .hrv series; skipping export."
            )
            return

        profs = self.workspace.get("Profiles", {}) or {}
        window_s = float(
            profs.get("window (sec)", profs.get("window_s", 30.0))
        )
        step_s = float(
            profs.get("step (sec)", profs.get("step_s", 5.0))
        )

        bands = self._resolve_psd_bands()
        subject = getattr(self.dataset, "basename", "")

        # Per-band sub-headers — kept tight on purpose so the CSV opens
        # nicely in spreadsheets without horizontal scrolling explosion.
        stat_keys = ("mean", "std", "min", "max", "t_max")

        rows: list[dict] = []
        for label, _ep in self._iter_active_epochs():
            row: dict[str, object] = {
                "Subject": subject,
                "epoch": label,
                "method": "",
                "unit": "",
                "window_sec": window_s,
                "step_sec": step_s,
                "n_windows": 0,
            }
            for name in bands:
                for stat in stat_keys:
                    row[f"{name}_{stat}"] = None

            try:
                view = hrv[label]
                result = view.band_power_profile(
                    window_s=window_s, step_s=step_s,
                )
                row["method"] = result.method or ""
                row["unit"] = result.unit or ""
                row["n_windows"] = int(result.timestamps.size)

                # Epoch-relative time axis — the same convention the
                # profile plot uses, so a ``t_max`` of 42.5 s in the CSV
                # matches the plot's x-axis tick the user sees.
                t_rel = (
                    result.timestamps - (result.timestamps[0] - window_s / 2.0)
                    if result.timestamps.size else result.timestamps
                )

                names_in_result = list(result.band_names)
                # Use the workspace order when available; otherwise emit
                # whatever bands the compute returned.
                emit_bands = bands or names_in_result
                for name in emit_bands:
                    if name not in names_in_result:
                        continue
                    row_band = result.band_power[names_in_result.index(name)]
                    finite_mask = np.isfinite(row_band)
                    if not np.any(finite_mask):
                        continue
                    finite = row_band[finite_mask]
                    row[f"{name}_mean"] = float(np.mean(finite))
                    row[f"{name}_std"] = float(np.std(finite, ddof=0))
                    row[f"{name}_min"] = float(np.min(finite))
                    row[f"{name}_max"] = float(np.max(finite))
                    # argmax indexes into the *finite-only* subarray, so
                    # remap it back to the original time axis position.
                    finite_indices = np.where(finite_mask)[0]
                    arg_max_in_full = int(finite_indices[int(np.argmax(finite))])
                    row[f"{name}_t_max"] = float(t_rel[arg_max_in_full])
            except Exception as exc:
                logger.warning(
                    f"Profile CSV: epoch {label!r} failed: {exc}"
                )
            rows.append(row)

        header_set: list[str] = [
            "Subject", "epoch", "method", "unit",
            "window_sec", "step_sec", "n_windows",
        ]
        for row in rows:
            for key in row:
                if key not in header_set:
                    header_set.append(key)

        with self.profile_csvfile.open(
            "w", newline="", encoding="utf-8"
        ) as f:
            w = csv.writer(f)
            w.writerow(header_set)
            for row in rows:
                w.writerow(
                    [self._format_cell(row.get(key)) for key in header_set]
                )

    @staticmethod
    def _format_cell(v) -> str:
        """Render *v* the same way the main parameters CSV does."""
        if v is None:
            return ""
        if isinstance(v, (float, np.floating)):
            if np.isnan(v):
                return ""
            return f"{float(v):.5f}"
        if isinstance(v, (int, np.integer)):
            return str(int(v))
        return str(v)

    def get_table_headers(self) -> list[str]:
        headers = []
        for col in range(self.table_widget.columnCount()):
            item = self.table_widget.horizontalHeaderItem(col)
            headers.append(item.text() if item is not None else f"Column {col + 1}")
        return headers
