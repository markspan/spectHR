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


class ParametersPlotWidget(QWidget):
    """
    A QWidget that displays calculated parameters in a spreadsheet-like manner,
    without using pandas.
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

        # Storage for saving
        self.headers: list[str] = []
        self.data: np.ndarray | None = None  # object array (rows x cols)
        self.csvfile: Path | None = None

    def display_parameters(self, dataset, workspace):
        self.dataset = dataset
        self.csvfile = Path(workspace["OutputDirectory"]) / f"{dataset.basename}.csv"
        self.setFocus()

        # ---- Get NumPy "table" from your HRV object ----
        # Expected:
        #   labels: (n,) epoch labels
        #   cols:   list[str] metric names
        #   values: (n, m) float64 metric values (NaN ok)
        labels, cols, values = self.dataset.hrv.hrv_epoch_table(self.dataset)

        # ---- Build table with Subject + epoch + metrics ----
        subject = getattr(dataset, "basename", None)

        n_rows = int(labels.shape[0])
        n_metrics = int(values.shape[1]) if values.size else 0

        self.headers = ["Subject", "epoch"] + list(cols)

        self.data = np.empty((n_rows, 2 + n_metrics), dtype=object)
        self.data[:, 0] = subject
        self.data[:, 1] = labels
        if n_metrics:
            # store floats into object array
            self.data[:, 2:] = values

        # ---- Populate QTableWidget ----
        self.table_widget.clear()
        self.table_widget.setRowCount(n_rows)
        self.table_widget.setColumnCount(len(self.headers))
        self.table_widget.setHorizontalHeaderLabels(self.headers)

        for i in range(n_rows):
            for j in range(len(self.headers)):
                v = self.data[i, j]

                # Blank out missing numeric values
                if isinstance(v, (float, np.floating)) and np.isnan(v):
                    txt = ""
                elif isinstance(v, str):
                    txt = v
                elif isinstance(v, (int, np.integer)):
                    txt = str(int(v))
                elif isinstance(v, (float, np.floating)):
                    txt = f"{float(v):.5f}"
                else:
                    # fallback for None / objects
                    txt = "" if v is None else str(v)

                self.table_widget.setItem(i, j, QTableWidgetItem(txt))

        self.table_widget.resizeColumnsToContents()

    def save_data(self):
        """
        Save the current table to CSV without pandas.
        """
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

    def get_table_headers(self):
        """
        Get the headers from the QTableWidget.

        Returns
        -------
        list[str]
            A list of headers exactly as shown in the table widget.
        """
        headers = []
        for col in range(self.table_widget.columnCount()):
            header_item = self.table_widget.horizontalHeaderItem(col)
            headers.append(
                header_item.text() if header_item is not None else f"Column {col + 1}"
            )
        return headers
