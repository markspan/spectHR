import sys
from typing import Any

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QStyle,
    QGroupBox,
    QScrollArea,
    QWidget,
    QDialogButtonBox,
    QSizePolicy,
    QComboBox,
)
from PySide6.QtCore import Qt


# ======================================================================
# Existing dialog — directory editor (unchanged)
# ======================================================================


class DirectorySelectorDialog(QDialog):
    """
    Dialog for editing the Directories section of the workspace.

    Accepts workspace["Directories"] as input, returns a flat dict with
    the three directory keys that the caller merges back into
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


# ======================================================================
# New dialog — dynamic parameters editor
# ======================================================================

# Keys whose sections are handled by other dialogs or are not editable here
_EXCLUDED_SECTIONS = {"Directories"}

# Known enumeration choices for specific leaf keys
_ENUM_CHOICES: dict[str, list[str]] = {
    "method": ["welch", "lombscargle", "carspan"],
    "window": ["hamming", "hann", "blackman", "bartlett", "boxcar"],
    "filter_type": ["highpass", "lowpass", "bandpass"],
}


def _label(key: str) -> str:
    """Turn a snake_case or camelCase key into a human-readable label."""
    import re

    # camelCase → words
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", key)
    # underscores → spaces
    s = s.replace("_", " ")
    return s.title()


class ParametersEditorDialog(QDialog):
    """
    Generic dialog that reads *all* non-directory sections from the workspace
    dict and presents them as editable panels, one ``QGroupBox`` per section.

    Nested sub-sections (e.g. FrequencyAnalysis → welch) each get their own
    nested group box inside the parent panel.

    Scalar leaf values are rendered as:
      - ``QComboBox``  for keys listed in ``_ENUM_CHOICES``
      - ``QLineEdit``  for everything else (int, float, str, None)

    When OK is pressed, ``get_parameters()`` returns a deep copy of the
    workspace with every edited value written back — ready to be merged by
    the caller via ``_deep_merge`` or written straight to disk.
    """

    def __init__(self, workspace: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Parameters")
        self.setModal(True)
        self.resize(560, 700)
        self.setWindowIcon(
            QApplication.style().standardIcon(
                getattr(QStyle, "SP_FileDialogDetailedView")
            )
        )

        # _widgets maps dotted key path → (widget, original_python_value)
        # e.g. "FrequencyAnalysis.welch.fs" → (QLineEdit, 4.0)
        self._widgets: dict[str, tuple[QWidget, Any]] = {}

        # ---- scroll area wrapping all group boxes ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(10)

        for section_key, section_value in workspace.items():
            if section_key in _EXCLUDED_SECTIONS:
                continue
            if not isinstance(section_value, dict):
                continue
            group = self._make_group(section_key, section_value, prefix=section_key)
            inner_layout.addWidget(group)

        inner_layout.addStretch()
        scroll.setWidget(inner)

        # ---- OK / Cancel ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addWidget(scroll)
        outer.addWidget(buttons)

    # ------------------------------------------------------------------
    # Recursive group-box builder
    # ------------------------------------------------------------------

    def _make_group(self, title: str, data: dict, prefix: str) -> QGroupBox:
        group = QGroupBox(_label(title))
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(group)
        layout.setSpacing(4)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        has_scalars = False

        for key, value in data.items():
            path = f"{prefix}.{key}"

            if isinstance(value, dict):
                # Nested sub-section → recurse into a nested group box
                sub_group = self._make_group(key, value, prefix=path)
                layout.addWidget(sub_group)

            else:
                # Scalar leaf → make a widget
                widget = self._make_widget(key, value)
                self._widgets[path] = (widget, value)
                form.addRow(_label(key) + ":", widget)
                has_scalars = True

        if has_scalars:
            layout.addLayout(form)

        return group

    def _make_widget(self, key: str, value: Any) -> QWidget:
        """Return a QComboBox for known enumerations, QLineEdit otherwise."""
        if key in _ENUM_CHOICES:
            combo = QComboBox()
            for choice in _ENUM_CHOICES[key]:
                combo.addItem(choice)
            # Select current value (case-insensitive)
            idx = combo.findText(
                str(value), Qt.MatchFixedString | Qt.MatchCaseSensitive
            )
            if idx < 0:
                idx = combo.findText(str(value).lower())
            combo.setCurrentIndex(max(idx, 0))
            return combo

        edit = QLineEdit("" if value is None else str(value))
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return edit

    # ------------------------------------------------------------------
    # Value extraction — coerce back to the original Python type
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce(raw_text: str, original: Any) -> Any:
        """
        Convert the string from the widget back to the type of the original value.
        ``None`` originals are kept as ``None`` when the field is empty, otherwise
        treated as a string.
        """
        if isinstance(original, bool):
            return raw_text.strip().lower() in ("true", "1", "yes")
        if isinstance(original, int):
            try:
                return int(raw_text)
            except ValueError:
                return original
        if isinstance(original, float):
            try:
                return float(raw_text)
            except ValueError:
                return original
        if original is None:
            stripped = raw_text.strip()
            if stripped == "":
                return None
            # Try numeric coercion for previously-null fields
            try:
                return int(stripped)
            except ValueError:
                pass
            try:
                return float(stripped)
            except ValueError:
                pass
            return stripped
        return raw_text  # str

    # ------------------------------------------------------------------
    # Public result accessor
    # ------------------------------------------------------------------

    def get_parameters(self, workspace: dict) -> dict:
        """
        Return a deep copy of *workspace* with all edited values written back.

        The caller can pass this straight to ``SaveWorkspace()`` or merge it
        into the live workspace with ``_deep_merge``.
        """
        import copy

        result = copy.deepcopy(workspace)

        for path, (widget, original) in self._widgets.items():
            # Read the raw string value from the widget
            if isinstance(widget, QComboBox):
                raw = widget.currentText()
            else:
                raw = widget.text()

            coerced = self._coerce(raw, original)

            # Walk the dotted path and set the leaf
            keys = path.split(".")
            node = result
            for k in keys[:-1]:
                node = node[k]
            node[keys[-1]] = coerced

        return result
