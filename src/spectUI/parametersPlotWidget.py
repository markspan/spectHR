from pathlib import Path

import numpy as np
import pandas as pd
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

    def __init__(self,  parent=None):
        """
        Initialize the ParametersPlotWidget and its layout components.

        Args:
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowTitle('Parameters Plot')

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

        # Base HRV table (index = epoch)
        df = self.dataset.hrv.hrv_epoch_table(self.dataset)

        # Ensure index is a column (epoch)
        df = df.reset_index()

        # Insert subject column FIRST
        subject = getattr(dataset, "basename", None)
        df.insert(0, "Subject", subject)

        self.data = df
        self.table_widget.clear()
        # Set the number of rows and columns
        self.table_widget.setRowCount(self.data.shape[0])
        self.table_widget.setColumnCount(self.data.shape[1])

        # Set the table headers
        self.table_widget.setHorizontalHeaderLabels(self.data.columns)

        # Populate the table with data
        for i in range(self.data.shape[0]):
            for j in range(self.data.shape[1]):
                if isinstance(self.data.iloc[i, j], str):
                    # If the data is a string, set it directly
                    self.table_widget.setItem(
                        i, j, QTableWidgetItem(self.data.iloc[i, j]))
                elif isinstance(self.data.iloc[i, j], (int, np.integer)):
                    # If the data is an integer, set it directly
                    self.table_widget.setItem(
                        i, j, QTableWidgetItem(str(self.data.iloc[i, j])))
                else:
                    self.table_widget.setItem(
                        i, j, QTableWidgetItem(str(format(self.data.iloc[i, j], '.5f'))))

        # Resize columns to fit content
        self.table_widget.resizeColumnsToContents()

    def save_data(self):
        # self.data already has correct columns & order
        self.data.to_csv(self.csvfile, index=False)


    def get_table_headers(self):
        """
        Get the headers from the QTableWidget.

        Returns:
            list: A list of headers including 'Subject' as the first header.
        """
        headers = ['Subject']
        for col in range(self.table_widget.columnCount()):
            header_item = self.table_widget.horizontalHeaderItem(col)
            if header_item is not None:
                headers.append(header_item.text())
            else:
                headers.append(f'Column {col+1}')
        return headers
