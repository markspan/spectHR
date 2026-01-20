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
    A QWidget that displays calculated parameters in a spreadsheet-like manner.

    Attributes:
    ----------
    table_widget : QTableWidget
        The table widget to display the parameters.
    main_layout : QVBoxLayout
        The main layout of the widget.
    button_layout : QHBoxLayout
        The layout for buttons.
    save_button : QPushButton
        The button to save the table data.
    """

    def __init__(self, parent=None):
        """
        Initialize the ParametersPlotWidget and its layout components.

        Args:
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowTitle("Parameters Plot")

        # Create a QTableWidget
        self.table_widget = QTableWidget()

        # Set up main layout
        self.main_layout = QVBoxLayout(self)
        self.setLayout(self.main_layout)

        # Add the table widget to the layout
        self.main_layout.addWidget(self.table_widget)

        # Create a horizontal layout for buttons
        self.button_layout = QHBoxLayout()

        # Add a "Save" button
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_data)
        self.button_layout.addWidget(self.save_button)

        # Add the button layout to the main layout
        self.main_layout.addLayout(self.button_layout)

    def display_parameters(self, dataset, workspace):
        self.dataset = dataset
        self.csvfile = Path(workspace["OutputDirectory"]) / f"{dataset.basename}.csv"
        self.setFocus()

        # Get epoch → metrics table (no pandas)
        table = self.dataset.hrv.hrv_epoch_table(self.dataset)
        # table: dict[str, dict[str, Any]]

        subject = getattr(dataset, "basename", None)

        # Determine column order
        # Start with Subject + Epoch, then metric names
        metric_names = []
        for metrics in table.values():
            for k in metrics.keys():
                if k not in metric_names:
                    metric_names.append(k)

        headers = ["Subject", "Epoch", *metric_names]

        # Build row-oriented data
        rows = []
        for epoch, metrics in table.items():
            row = {
                "Subject": subject,
                "Epoch": epoch,
            }
            for k in metric_names:
                row[k] = metrics.get(k)
            rows.append(row)

        self.headers = headers
        self.rows = rows  # store for saving later

        # -----------------------------
        # Populate QTableWidget
        # -----------------------------
        self.table_widget.clear()
        self.table_widget.setRowCount(len(rows))
        self.table_widget.setColumnCount(len(headers))
        self.table_widget.setHorizontalHeaderLabels(headers)

        for i, row in enumerate(rows):
            for j, key in enumerate(headers):
                val = row.get(key)

                if val is None:
                    text = ""
                elif isinstance(val, str):
                    text = val
                elif isinstance(val, (int, np.integer)):
                    text = str(int(val))
                elif isinstance(val, (float, np.floating)):
                    if not np.isfinite(val):
                        text = ""
                    elif float(val).is_integer():
                        text = str(int(val))
                    else:
                        text = f"{val:.5f}"
                else:
                    text = str(val)

                self.table_widget.setItem(i, j, QTableWidgetItem(text))

        self.table_widget.resizeColumnsToContents()

    def save_data(self):
        # self.data already has correct columns & order
        with open(self.csvfile, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writeheader()
            for row in self.rows:
                writer.writerow(row)

    def get_table_headers(self):
        """
        Get the headers from the QTableWidget.

        Returns:
            list: A list of headers including 'Subject' as the first header.
        """
        headers = ["Subject"]
        for col in range(self.table_widget.columnCount()):
            header_item = self.table_widget.horizontalHeaderItem(col)
            if header_item is not None:
                headers.append(header_item.text())
            else:
                headers.append(f"Column {col + 1}")
        return headers
