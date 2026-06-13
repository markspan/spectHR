# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`ResultsTableWidget` — the per-epoch metrics table.

One row per active epoch, one column per registered ``@epoch_metric`` —
time-domain HRV, frequency-domain band powers, blood-pressure, respiration,
RSA and ICG.  The whole table comes from :meth:`Session.epochs_table`, which
takes an :class:`~spectHR.session.AnalysisConfig` built from the *workspace*,
so every analysis setting (PSD method, bands, RSA rejection, BP calibration,
B-point guard) flows straight into the numbers — the widget computes nothing
itself.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spectHR.session import AnalysisConfig, Session
from spectUI.plot_worker import DockScheduler


class ResultsTableWidget(QWidget):
    """Per-epoch metrics table driven by :meth:`Session.epochs_table`."""

    #: Emitted after a results export, carrying the chosen directory, so the
    #: host can offer to export the plots into the same folder.
    plotsExportRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: Session | None = None
        self._config = None
        # The table is heavy (PEP ensemble + RSA + PSD per epoch), so it is
        # computed off the UI thread; a stale generation is discarded when a
        # newer edit supersedes it.
        self._scheduler = DockScheduler()

        self._export_btn = QPushButton("Export…")
        self._export_btn.setToolTip("Write the table (CSV) and all per-epoch data (HDF5)")
        self._export_btn.clicked.connect(self._export)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        bar.addStretch()
        bar.addWidget(self._export_btn)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.table)
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Dock contract
    # ------------------------------------------------------------------

    def set_session(self, session: Session, config=None) -> None:
        self._session = session
        self._config = config
        self.setVisible(True)
        self.refresh()

    def set_epoch(self, name: str) -> None:  # noqa: ARG002 — table shows all epochs
        """No-op: the table always shows every active epoch."""

    def refresh(self) -> None:
        """Recompute the metrics table off-thread, then repopulate.

        Evaluating every metric per epoch (PEP ensemble, RSA, PSD, …) can take
        many seconds for a long recording with many epochs, so it runs on a
        pool thread via :class:`DockScheduler`; the table fills in when the
        result arrives instead of freezing the UI.
        """
        session = self._session
        if session is None:
            return
        config = self._analysis_config()          # build on the UI thread

        def compute():
            return session.epochs_table(config)   # pool thread; pure / headless

        self._scheduler.submit("results", compute, self._on_table, self._on_error)

    def _on_table(self, table) -> None:
        self._populate(table.labels, table.columns, table.values)

    @staticmethod
    def _on_error(exc: Exception) -> None:
        from spectHR.Tools.Logger import logger
        logger.exception("epochs_table failed", exc_info=exc)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _workspace_dict(self):
        cfg = self._config
        if cfg is not None and hasattr(cfg, "to_dict"):
            return cfg.to_dict()
        return cfg if isinstance(cfg, dict) else None

    def _export(self) -> None:
        """Write the table as CSV and all per-epoch data as HDF5, then offer plots."""
        if self._session is None:
            return
        cfg = self._config
        out_default = (str(cfg.output_dir)
                       if cfg is not None and hasattr(cfg, "output_dir")
                       else str(Path.home()))
        directory = QFileDialog.getExistingDirectory(
            self, "Export results to…", out_default)
        if not directory:
            return

        from spectHR.analysis.exporter import (
            EpochExporter, write_results_csv, write_results_h5,
        )
        import re
        base = re.sub(r"[^\w.-]+", "_", self._session.name or "results") or "results"
        try:
            table = self._session.epochs_table(self._analysis_config())
            write_results_csv(Path(directory) / f"{base}.csv", table)
            data = EpochExporter(self._workspace_dict(), table.contexts).collect()
            write_results_h5(Path(directory) / f"{base}.h5", table, data)
        except Exception as exc:  # noqa: BLE001 — report, never crash the UI
            QMessageBox.critical(self, "Export error",
                                 f"Could not export results:\n{exc}")
            return

        if QMessageBox.question(
            self, "Export plots?",
            f"Saved {base}.csv and {base}.h5.\n\nExport the plots as well?",
        ) == QMessageBox.StandardButton.Yes:
            self.plotsExportRequested.emit(directory)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _analysis_config(self) -> AnalysisConfig:
        """Build an :class:`AnalysisConfig` from the workspace parameters."""
        cfg = self._config
        if cfg is None:
            return AnalysisConfig()
        workspace = cfg.to_dict() if hasattr(cfg, "to_dict") else (
            cfg if isinstance(cfg, dict) else None
        )
        return AnalysisConfig.from_workspace(workspace)

    @staticmethod
    def _metric_docs() -> dict[str, str]:
        """Map each registered metric name to its docstring (first paragraph).

        Used to restore the V2 behaviour of showing the calculation's
        docstring as the column-header tooltip.
        """
        from spectHR.analysis.registry import get_metric_groups, get_metrics

        docs: dict[str, str] = {}
        for src in (get_metrics(), get_metric_groups()):
            for name, fn in src.items():
                doc = (fn.__doc__ or "").strip()
                if doc:
                    docs[name] = doc.split("\n\n")[0].strip()
        return docs

    def _populate(self, labels, columns: list[str], values: np.ndarray) -> None:
        self.table.clear()
        self.table.setRowCount(len(labels))
        self.table.setColumnCount(1 + len(columns))
        self.table.setHorizontalHeaderLabels(["epoch", *columns])

        # Header tooltips: the docstring of each metric's calculation (V2).
        docs = self._metric_docs()
        for c, col in enumerate(columns):
            header = self.table.horizontalHeaderItem(c + 1)
            if header is not None and col in docs:
                header.setToolTip(docs[col])

        for r, label in enumerate(labels):
            name_item = QTableWidgetItem(str(label))
            self.table.setItem(r, 0, name_item)
            for c, _col in enumerate(columns):
                val = values[r, c] if values.size else np.nan
                text = "" if (val is None or np.isnan(val)) else f"{val:.4g}"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c + 1, item)

        self.table.resizeColumnsToContents()
