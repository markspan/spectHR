import sys
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QStyle,
)


class DirectorySelectorDialog(QDialog):
    """
    Dialog for editing the Directories section of the workspace.

    Accepts workspace["Directories"] as input, returns a flat dict
    with the three directory keys that the caller merges back into
    workspace["Directories"].
    """

    def __init__(self, directories: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Directory Settings")
        self.setModal(True)
        self.resize(600, 300)
        self.setWindowIcon(
            QApplication.style().standardIcon(getattr(QStyle, "SP_DirIcon"))
        )

        self.data_dir_edit = QLineEdit(directories.get("DataDirectory", ""))
        self.cache_dir_edit = QLineEdit(directories.get("CacheDirectory", ""))
        self.output_dir_edit = QLineEdit(directories.get("OutputDirectory", ""))

        self.data_dir_button = QPushButton("...")
        self.cache_dir_button = QPushButton("...")
        self.output_dir_button = QPushButton("...")

        self.data_dir_button.clicked.connect(
            lambda: self.select_directory(self.data_dir_edit)
        )
        self.cache_dir_button.clicked.connect(
            lambda: self.select_directory(self.cache_dir_edit)
        )
        self.output_dir_button.clicked.connect(
            lambda: self.select_directory(self.output_dir_edit)
        )

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Data Directory:"))
        self.add_directory_row(layout, self.data_dir_edit, self.data_dir_button)
        layout.addWidget(QLabel("Cache Directory:"))
        self.add_directory_row(layout, self.cache_dir_edit, self.cache_dir_button)
        layout.addWidget(QLabel("Output Directory:"))
        self.add_directory_row(layout, self.output_dir_edit, self.output_dir_button)

        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def add_directory_row(self, layout, line_edit, button):
        row = QHBoxLayout()
        row.addWidget(line_edit)
        row.addWidget(button)
        layout.addLayout(row)

    def select_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            line_edit.setText(directory)

    def get_directories(self) -> dict:
        """Return the edited directory values as a flat dict."""
        return {
            "DataDirectory": self.data_dir_edit.text(),
            "CacheDirectory": self.cache_dir_edit.text(),
            "OutputDirectory": self.output_dir_edit.text(),
        }
