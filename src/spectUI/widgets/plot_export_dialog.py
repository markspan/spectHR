# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`PlotExportDialog` — pick a destination and which dock plots to save.

Shown after a results export when the analyst opts to export the figures too:
a destination folder picker plus a tickbox per available plot (all ticked by
default).  The host saves the ticked docks' figures.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class PlotExportDialog(QDialog):
    """Destination + per-plot tickboxes; returns the chosen folder and keys."""

    def __init__(self, parent, plots: list[tuple[str, str]], default_dir: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export plots")
        self.setMinimumWidth(360)
        self._checks: dict[str, QCheckBox] = {}

        outer = QVBoxLayout(self)

        # Destination row.
        outer.addWidget(QLabel("Save figures to:"))
        row = QHBoxLayout()
        self._dir_edit = QLineEdit(default_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self._dir_edit)
        row.addWidget(browse)
        outer.addLayout(row)

        # Plot tickboxes (scrollable for many docks).
        outer.addWidget(QLabel("Plots to export:"))
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(4, 0, 4, 0)
        for key, label in plots:
            cb = QCheckBox(label)
            cb.setChecked(True)
            box.addWidget(cb)
            self._checks[key] = cb
        box.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        outer.addWidget(scroll, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Save figures to", self._dir_edit.text())
        if d:
            self._dir_edit.setText(d)

    def directory(self) -> str:
        return self._dir_edit.text().strip()

    def selected(self) -> set[str]:
        return {key for key, cb in self._checks.items() if cb.isChecked()}
