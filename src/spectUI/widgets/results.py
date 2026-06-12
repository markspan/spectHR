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

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from spectHR.session import AnalysisConfig, Session


class ResultsTableWidget(QWidget):
    """Per-epoch metrics table driven by :meth:`Session.epochs_table`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: Session | None = None
        self._config = None

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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
        """Recompute the metrics table and repopulate.

        Heavy (it evaluates every metric per epoch); the coordinator only
        calls this for the visible dock, lazily for hidden ones.
        """
        if self._session is None:
            return
        try:
            table = self._session.epochs_table(self._analysis_config())
        except Exception:  # noqa: BLE001 — never crash the UI over a metric
            from spectHR.Tools.Logger import logger
            logger.exception("epochs_table failed")
            return
        self._populate(table.labels, table.columns, table.values)

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
