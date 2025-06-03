import sys

from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QPushButton, QVBoxLayout


class ChannelSelect(QDialog):
    def __init__(self, nchannels=4):
        super().__init__()

        self.setWindowTitle("Channel Selector")
        self.setGeometry(100, 100, 300, 200)

        # Create a layout
        layout = QVBoxLayout(self)

        # Create a label
        self.label = QLabel("Select a channel from the list:")
        layout.addWidget(self.label)

        # Create a QComboBox and populate it with items
        self.combo_box = QComboBox()
        for i in range(nchannels):
            self.combo_box.addItem(f"Channel {i + 1}")  

        # Connect the currentIndexChanged signal to a slot
        self.combo_box.currentIndexChanged.connect(self.on_channel_selected)

        # Add the QComboBox to the layout
        layout.addWidget(self.combo_box)

        # Add a button to close the dialog
        self.button = QPushButton("OK")
        self.button.clicked.connect(self.accept)
        layout.addWidget(self.button)

    def on_channel_selected(self, index):
        # Update the label to show the selected channel
        selected_channel = self.combo_box.itemText(index)
        self.label.setText(f"Selected: {selected_channel}")

    def get_selected_channel(self):
        # Return the currently selected channel
        return self.combo_box.currentIndex()-1