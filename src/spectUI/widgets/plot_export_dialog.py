# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`PlotExportDialog`, pick a destination, format, DPI and which docks to save.

Shown after a results export when the analyst opts to export the figures too.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# (label, file extension, matplotlib format string, fixed_dpi)
# fixed_dpi=True means the DPI spinner is relevant; SVG is vector-only so DPI
# only affects raster elements embedded inside the SVG (markers etc.) — we
# still allow the user to set it but note "vector" in the label.
_FORMATS: list[tuple[str, str, str]] = [
    ("SVG  (vector — recommended for journals)", ".svg", "svg"),
    ("PDF  (vector, fonts embedded)",            ".pdf", "pdf"),
    ("PNG  (raster)",                            ".png", "png"),
    ("EPS  (vector, legacy journals)",           ".eps", "eps"),
]


class PlotExportDialog(QDialog):
    """Destination, format, DPI and per-plot tickboxes."""

    def __init__(self, parent, plots: list[tuple[str, str]], default_dir: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export plots")
        self.setMinimumWidth(400)
        self._checks: dict[str, QCheckBox] = {}

        outer = QVBoxLayout(self)

        # ---- destination ----
        outer.addWidget(QLabel("Save figures to:"))
        row = QHBoxLayout()
        self._dir_edit = QLineEdit(default_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self._dir_edit)
        row.addWidget(browse)
        outer.addLayout(row)

        # ---- format ----
        fmt_box = QGroupBox("Format")
        fmt_layout = QVBoxLayout(fmt_box)
        self._fmt_group = QButtonGroup(self)
        self._fmt_radios: list[tuple[QRadioButton, str, str]] = []
        for i, (label, ext, fmt) in enumerate(_FORMATS):
            rb = QRadioButton(label)
            rb.setChecked(i == 0)   # SVG default
            self._fmt_group.addButton(rb, i)
            fmt_layout.addWidget(rb)
            self._fmt_radios.append((rb, ext, fmt))
        outer.addWidget(fmt_box)

        # ---- DPI ----
        dpi_row = QHBoxLayout()
        dpi_row.addWidget(QLabel("DPI (raster elements):"))
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(72, 1200)
        self._dpi_spin.setSingleStep(50)
        self._dpi_spin.setValue(300)
        self._dpi_spin.setFixedWidth(80)
        dpi_row.addWidget(self._dpi_spin)
        dpi_row.addStretch()
        outer.addLayout(dpi_row)

        # ---- plot tickboxes ----
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

    def export_format(self) -> tuple[str, str]:
        """Return ``(extension, matplotlib_format)`` for the chosen format."""
        idx = self._fmt_group.checkedId()
        _, ext, fmt = self._fmt_radios[idx]
        return ext, fmt

    def dpi(self) -> int:
        return self._dpi_spin.value()
