import sys

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class EventCodeWindow(QDialog):
    # Define a signal to emit the selected start and stop codes
    codes_selected = Signal(list, list)

    def __init__(self, event_codes, ignore=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Event Code Selection")
        self.setGeometry(100, 100, 600, 400)
        self.event_codes = event_codes
        unique_event_codes = set(event_codes)
        unique_event_codes.remove(ignore)
        self.unique_event_codes = list(unique_event_codes)

        self.init_ui()

    def init_ui(self):
        # Create widgets
        self.all_codes_list = QListWidget()
        self.start_codes_list = QListWidget()
        self.stop_codes_list = QListWidget()

        self.to_start_button = QPushButton("toStart")
        self.to_stop_button = QPushButton("toStop")
        self.FullEpochButton = QPushButton("Full Epoch")
        self.ok_button = QPushButton("OK")
        self.ok_button.setEnabled(False)

        # Set up layouts
        main_layout = QHBoxLayout()

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("All Codes"))
        left_layout.addWidget(self.all_codes_list)

        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Start Codes"))
        right_layout.addWidget(self.start_codes_list)
        right_layout.addWidget(QLabel("Stop Codes"))
        right_layout.addWidget(self.stop_codes_list)

        button_layout = QVBoxLayout()
        button_layout.addWidget(self.to_start_button)
        button_layout.addWidget(self.to_stop_button)
        button_layout.addWidget(self.FullEpochButton)
        button_layout.addWidget(self.ok_button)

        main_layout.addLayout(left_layout)
        main_layout.addLayout(right_layout)
        main_layout.addLayout(button_layout)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setLayout(main_layout)

        # Populate the all codes list with unique event codes
        self.populate_all_codes()

        # Connect signals
        self.to_start_button.clicked.connect(self.move_to_start)
        self.to_stop_button.clicked.connect(self.move_to_stop)
        self.ok_button.clicked.connect(self.on_ok)
        self.FullEpochButton.clicked.connect(self.on_fullepoch)

        # Connect item changes to update OK button state
        self.start_codes_list.itemChanged.connect(self.update_ok_button_state)
        self.stop_codes_list.itemChanged.connect(self.update_ok_button_state)

    def populate_all_codes(self):
        """Populate the all codes list with unique event codes."""
        for code in self.unique_event_codes:
            n = len(self.event_codes[self.event_codes == code])
            self.all_codes_list.addItem(str(f'{code} ({n})'))

    def move_to_start(self):
        """Move selected items from all codes list to start codes list."""
        for item in self.all_codes_list.selectedItems():
            self.all_codes_list.takeItem(self.all_codes_list.row(item))
            self.start_codes_list.addItem(item.text())
        self.update_ok_button_state()

    def move_to_stop(self):
        """Move selected items from all codes list to stop codes list."""
        for item in self.all_codes_list.selectedItems():
            self.all_codes_list.takeItem(self.all_codes_list.row(item))
            self.stop_codes_list.addItem(item.text())
        self.update_ok_button_state()

    def update_ok_button_state(self):
        """Enable the OK button if the number of start and stop codes are equal."""
        self.ok_button.setEnabled(
            self.start_codes_list.count() == self.stop_codes_list.count())

    def on_fullepoch(self):
        self.codes_selected.emit([], [])
        self.accept()

    def on_ok(self):
        """Handle the OK button click event."""
        start_codes = [int(self.start_codes_list.item(i).text().split(' ', 1)[0])
                       for i in range(self.start_codes_list.count())]
        stop_codes = [int(self.stop_codes_list.item(i).text().split(' ', 1)[0])
                      for i in range(self.stop_codes_list.count())]

        # Emit the selected start and stop codes
        self.codes_selected.emit(start_codes, stop_codes)
        self.accept()
