import pandas as pd
import os 
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import spectHR as cs

class ParametersPlotWidget(QWidget):
    """
    A QWidget that displays calculated parameters in a spreadsheet-like manner.

    Attributes:
        table_widget (QTableWidget): The table widget to display the parameters.
    """

    def __init__(self, parent=None):
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

    def display_parameters(self, dataset):
        """
        Calculate and display the parameters in the table widget.

        Args:
            dataset: A dataset object with `RTops`, `ibi`, and `unique_epochs` attributes.
        """
        self.dataset = dataset
        self.setFocus()  # Ensure the widget gets focus

        # Calculate descriptive statistics grouped by epoch
        dataset.descriptives_Values = cs.explode(dataset)\
            .groupby('epoch')['ibi']\
            .agg([
                ('N', len),
                ('mean', 'mean'),
                ('std', 'std'),
                ('min', 'min'),
                ('max', 'max'),
                ('rmssd', cs.Tools.Params.rmssd),
                ('sdnn', cs.Tools.Params.sdnn),
                ('sdsd', cs.Tools.Params.sdsd),
                ('sd1', cs.Tools.Params.sd1),
                ('sd2', cs.Tools.Params.sd2),
                ('sd_ratio', cs.Tools.Params.sd_ratio),
                ('ellipse_area', cs.ellipse_area)
            ]).reset_index()
                        # Merge PSD values if available
        if hasattr(dataset, 'psd_Values'):
            dataset.descriptives_Values = pd.merge(dataset.descriptives_Values, dataset.psd_Values, on='epoch', how='outer')
                
        # populate the table
        data = dataset.descriptives_Values
        # Ensure 'epoch' is the first column
        columns = ['epoch'] + [col for col in data.columns if col != 'epoch']
        data = data[columns]

        # Set the number of rows and columns
        self.table_widget.setRowCount(data.shape[0])
        self.table_widget.setColumnCount(data.shape[1])

        # Set the table headers
        self.table_widget.setHorizontalHeaderLabels(data.columns)

        # Populate the table with data
        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                self.table_widget.setItem(i, j, QTableWidgetItem(str(data.iloc[i, j])))

        # Resize columns to fit content
        self.table_widget.resizeColumnsToContents()

        # Redraw the table
        # self.table_widget.update()

    def save_data(self):
            """
            Save the contents of the QTableWidget to a CSV file.
            """
            # Collect data from the table widget
            data = []
            for row in range(self.table_widget.rowCount()):
                row_data = [os.path.splitext(self.dataset.filename)[0]] 
                for col in range(self.table_widget.columnCount()):
                    item = self.table_widget.item(row, col)
                    if item is not None:
                        row_data.append(item.text())
                    else:
                        row_data.append('')
                data.append(row_data)

            # Create a pandas DataFrame
            df = pd.DataFrame(data)

            # Save the DataFrame to a CSV file
            df.to_csv(os.path.splitext(self.dataset.filename)[0] + '.csv', index=False, header=self.get_table_headers())

    def get_table_headers(self):
        """
        Get the headers from the QTableWidget.
        """
        headers = ['Subject']
        for col in range(self.table_widget.columnCount()):
            header_item = self.table_widget.horizontalHeaderItem(col)
            if header_item is not None:
                headers.append(header_item.text())
            else:
                headers.append(f'Column {col+1}')
        return headers