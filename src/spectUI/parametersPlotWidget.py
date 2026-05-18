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
from spectHR.Tools.PSD._band_power import band_power_rectangular
from spectUI._uitools import resolve_export_dir, show_export_summary


class ParametersPlotWidget(QWidget):
    """
    A QWidget that displays calculated HRV parameters in a spreadsheet-like table.

    The output CSV path is read from workspace["Directories"]["OutputDirectory"].

    Saving emits three CSV files, all wide / one-row-per-epoch so they
    drop into R / JASP / SPSS as a regular data frame; the scalar
    columns are immediately usable and the raw-array columns (described
    below) parse with one ``strsplit`` / ``split`` call:

    - ``{basename}.csv`` — time-domain HRV metrics per epoch.
    - ``{basename}_psd.csv`` — for every configured band, the
      integrated ``<band>_power`` (scalar) plus the raw PSD slice
      inside that band's frequency range. The raw slice is two cells
      per band, each a comma-separated list of equal length:
      ``<band>_freqs`` (Hz) and ``<band>_psd_raw`` (power values at
      those frequencies).
    - ``{basename}_profiles.csv`` — for every configured band, the
      five summary statistics (``mean / std / min / max / t_max``)
      plus the raw band-power-per-window time series in
      ``<band>_profile_raw`` (comma-separated). The window-centre
      times are shared across bands and emitted once per row as the
      ``profile_timestamps`` column.

    The list entries inside a raw-data cell are comma-separated, the
    same separator the CSV uses between fields. Python's ``csv.writer``
    quotes any field that contains commas, so the file stays a valid
    RFC 4180 CSV and a downstream reader treats each list as one
    field. To pull the list back into numbers a receiver does
    ``as.numeric(strsplit(cell, ',')[[1]])`` (R) or
    ``[float(v) for v in cell.split(',') if v]`` (Python). NaN
    windows / NaN PSD bins come through as empty positions
    (``...,1.23,,4.56,...``), which both parsers turn into ``NA`` /
    ``NaN`` of their own accord.

    Per-epoch failures (too few R-peaks, no PSD method set, etc.) are
    logged and leave that row's per-band cells empty; a wholesale
    failure of the export is logged and skipped without affecting the
    other two files.
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
            
        # Compose the same summary message the user sees in the log and the
        # message box, so the log file and the dialog stay in sync.  Writing
        # three CSVs in one click, so list them explicitly — that way the
        # user can paste the dialog text straight into a downstream script.
        export_dir = self._resolve_export_dir()
        files_written = []
        for path in (self.csvfile, self.psd_csvfile, self.profile_csvfile):
            if path is not None and path.exists():
                files_written.append(path.name)
        summary = (
            f"Parameters export: wrote {len(files_written)} file(s) "
            f"to {export_dir!s}"
        )
        if files_written:
            summary += "\n  - " + "\n  - ".join(files_written)
        logger.info(summary)

        show_export_summary(self, context="Parameters", summary=summary)

    def _resolve_export_dir(self) -> Path:
        """Delegated to ``_uitools.resolve_export_dir`` for cross-widget parity."""
        return resolve_export_dir(self.workspace, context="Parameters")
    
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
        """Band names in the workspace's display order (for column ordering)."""
        return [name for name, _, _ in self._resolve_psd_band_edges()]

    def _resolve_psd_band_edges(self) -> list[tuple[str, float, float]]:
        """Return ``[(name, low, high), ...]`` for every configured band.

        Reads ``FrequencyAnalysis.bands`` from the workspace. Returns
        ``[]`` when no workspace is attached or the section is empty —
        the caller is expected to fall back to whatever the active PSD
        method carries.
        """
        if self.workspace is None:
            return []
        bands = (
            (self.workspace.get("FrequencyAnalysis", {}) or {})
            .get("bands", {}) or {}
        )
        edges: list[tuple[str, float, float]] = []
        for name, spec in bands.items():
            if not isinstance(spec, dict):
                continue
            try:
                low = float(spec["low"])
                high = float(spec["high"])
            except (KeyError, TypeError, ValueError):
                continue
            edges.append((name, low, high))
        return edges

    def _save_psd_csv(self) -> None:
        """Write ``{basename}_psd.csv`` — one row per epoch, scalar + raw data.

        Per band, the row carries:

        * ``<band>_power`` — integrated band power (mMI² by default).
        * ``<band>_freqs`` — comma-separated list of the PSD's
          frequency bins (Hz) inside ``[low, high]``.
        * ``<band>_psd_raw`` — comma-separated list of the PSD values
          at exactly those frequencies (mMI²/Hz by default).

        ``<band>_freqs`` and ``<band>_psd_raw`` have equal length for a
        given band, so they can be zipped back into ``(freq, power)``
        pairs without any extra metadata.
        """
        if self.psd_csvfile is None:
            return
        hrv = getattr(self.dataset, "hrv", None)
        if hrv is None:
            logger.warning(
                "PSD CSV: dataset has no .hrv series; skipping export."
            )
            return

        bands = self._resolve_psd_band_edges()
        subject = getattr(self.dataset, "basename", "")

        rows: list[dict] = []
        for label, _ep in self._iter_active_epochs():
            row: dict[str, object] = {
                "Subject": subject,
                "epoch": label,
                "method": "",
                "unit": "",
            }
            for name, _, _ in bands:
                row[f"{name}_power"] = None
                row[f"{name}_freqs"] = ""
                row[f"{name}_psd_raw"] = ""

            try:
                view = hrv[label]
                # Single PSD call per epoch — band powers are then just
                # rectangular integrations of slices of this one array,
                # and the raw slices we expose to the CSV are pulled
                # straight off the same arrays. Costs one PSD per epoch
                # instead of two (one for the unit / spectrum + one
                # implicitly inside ``band_powers``).
                psd_res = view.psd(with_ci=False)
                freqs = np.asarray(psd_res.freqs)
                power = np.asarray(psd_res.power)
                row["method"] = (psd_res.method or "")
                # PSD result carries a per-Hz unit (e.g. ``mMI²/Hz``);
                # the integrated band-power columns use the same unit
                # without the ``/Hz`` suffix, so strip it once and
                # record the band-power unit. The raw PSD column keeps
                # the per-Hz interpretation — the same as what the PSD
                # plot draws.
                row["unit"] = (psd_res.unit or "").replace("/Hz", "")

                # Fall back to the active method's bands when the
                # workspace had none — keeps the file useful for ad-hoc
                # scripts that bypass the workspace dialog.
                if not bands:
                    method = getattr(view, "psd_method", None) or getattr(
                        hrv, "psd_method", None
                    )
                    if method is not None:
                        bands_iter = [
                            (name, b.low, b.high)
                            for name, b in method.bands.items()
                        ]
                    else:
                        bands_iter = []
                else:
                    bands_iter = bands

                for name, low, high in bands_iter:
                    mask = (freqs >= low) & (freqs <= high)
                    if not np.any(mask):
                        # Band entirely outside the PSD's frequency
                        # range — integrate to 0 and emit empty list
                        # cells so the column shapes stay rectangular.
                        row[f"{name}_power"] = 0.0
                        row[f"{name}_freqs"] = ""
                        row[f"{name}_psd_raw"] = ""
                        continue
                    band_freqs = freqs[mask]
                    band_power = power[mask]
                    row[f"{name}_power"] = band_power_rectangular(
                        freqs, power, low, high
                    )
                    row[f"{name}_freqs"] = self._format_list(band_freqs)
                    row[f"{name}_psd_raw"] = self._format_list(band_power)
            except Exception as exc:
                logger.warning(
                    f"PSD CSV: epoch {label!r} failed: {exc}"
                )
            rows.append(row)

        # Collect the full column set from every row so a fallback path
        # that introduced a new band name doesn't get dropped.
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
        """Write ``{basename}_profiles.csv`` — summary stats *and* raw data per epoch.

        Each profile is a 2-D ``(n_bands × n_windows)`` array. To fit
        one row per epoch the time axis is collapsed to five scalars
        per band (``mean / std / min / max / t_max``), and the raw
        time series is emitted in two layers:

        * ``profile_timestamps`` — one cell per row, comma-separated
          list of epoch-relative window-centre times (seconds, ``t = 0``
          at the epoch's first R-peak). Shared across bands, so it's
          recorded once per epoch.
        * ``<band>_profile_raw`` — one cell per row per band,
          comma-separated list of the band's integrated power at each
          window centre. NaN windows show up as empty positions inside
          the list. Same length as ``profile_timestamps``.

        ``n_windows`` records the list length so a downstream reader
        can sanity-check it without splitting first. The window / step
        lengths used for the compute are recorded in every row as
        ``window_sec`` / ``step_sec`` so each row is self-describing
        even when the export mixes datasets analysed with different
        profile settings.
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
                "profile_timestamps": "",
            }
            for name in bands:
                for stat in stat_keys:
                    row[f"{name}_{stat}"] = None
                row[f"{name}_profile_raw"] = ""

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
                row["profile_timestamps"] = self._format_list(t_rel)

                names_in_result = list(result.band_names)
                # Use the workspace order when available; otherwise emit
                # whatever bands the compute returned.
                emit_bands = bands or names_in_result
                for name in emit_bands:
                    if name not in names_in_result:
                        continue
                    row_band = result.band_power[names_in_result.index(name)]
                    # Raw time series always written, even when every
                    # window is NaN — keeps the column rectangular and
                    # makes ``n_windows`` the single source of truth for
                    # the list length.
                    row[f"{name}_profile_raw"] = self._format_list(row_band)

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
            "profile_timestamps",
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

    @staticmethod
    def _format_list(arr) -> str:
        """Render a 1-D array of floats as a comma-separated list.

        Used by both spectral companion CSVs to pack per-band raw data
        (PSD slices, profile time series, axes) into a single cell while
        keeping the file at one-row-per-epoch. The cell value is itself
        comma-separated; Python's ``csv.writer`` wraps any field that
        contains commas in double quotes, so the file stays a valid
        RFC 4180 CSV and a downstream reader treats the list as one
        field. Stats packages then parse the inner list with one
        ``strsplit(cell, ",")`` (R) or ``cell.split(",")`` (Python /
        pandas) call.

        Numbers use six significant digits via ``g``, which keeps both
        very small VLF powers (``1.23e-05``) and large peaks
        (``3.10e+04``) readable without padding either to the precision
        of the other. NaN entries become empty positions
        (``...,1.23,,4.56,...``) so a receiver can rely on its own
        numeric coercion turning empty slots into NA / NaN.
        """
        if arr is None:
            return ""
        a = np.asarray(arr).ravel()
        if a.size == 0:
            return ""
        parts: list[str] = []
        for v in a:
            fv = float(v)
            if not np.isfinite(fv):
                parts.append("")
            else:
                parts.append(f"{fv:.6g}")
        return ",".join(parts)

    def get_table_headers(self) -> list[str]:
        headers = []
        for col in range(self.table_widget.columnCount()):
            item = self.table_widget.horizontalHeaderItem(col)
            headers.append(item.text() if item is not None else f"Column {col + 1}")
        return headers
