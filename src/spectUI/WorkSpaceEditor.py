import sys
from typing import Any

from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGridLayout,
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
from PySide6.QtGui import QColor


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
    # Leaf-key enumerations (apply wherever the key appears)
    "method": ["carspan", "carspan_strict", "welch", "lombscargle"],
    "window": ["hamming", "hann", "blackman", "bartlett", "boxcar"],
    "filter_type": ["highpass", "lowpass", "bandpass"],
    # Path-specific enumerations (override the leaf entry above for that
    # one path; needed when the same key name takes different values in
    # different sections, e.g. CARSPAN supports cosine-bell presets that
    # Welch does not)
    "FrequencyAnalysis.carspan.window": [
        "5% cosine bell",
        "10% cosine bell",
        "20% cosine bell",
        "25% cosine bell",
        "hann",
        "hamming",
        "boxcar",
    ],
    "FrequencyAnalysis.carspan.plot_units": ["mMI²/Hz", "ms²/Hz"],
    "FrequencyAnalysis.welch.units": ["mMI²", "ms²"],
    "FrequencyAnalysis.lombscargle.units": ["mMI²", "ms²"],
}


def _label(key: str) -> str:
    """Turn a snake_case or camelCase key into a human-readable label."""
    import re

    # camelCase → words
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", key)
    # underscores → spaces
    s = s.replace("_", " ")
    return s.title()


# ----------------------------------------------------------------------
# Colour-picker button used by the bands matrix
# ----------------------------------------------------------------------


class _ColorButton(QPushButton):
    """
    Push button that doubles as a colour swatch and a colour picker.

    The button's *text* is the colour string itself (e.g. ``"darkgreen"``
    or ``"#aa3322"``) — that way the surrounding ``ParametersEditorDialog``
    can read the value via ``widget.text()`` exactly like a ``QLineEdit``,
    no special-casing required.

    Clicking the button opens a ``QColorDialog`` seeded with the current
    colour. On accept the new colour is stored as ``#rrggbb`` (the format
    Qt returns) and the swatch is repainted via the stylesheet.
    """

    def __init__(self, initial: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color: str = str(initial) if initial is not None else ""
        self.setMinimumWidth(110)
        self._refresh()
        self.clicked.connect(self._pick)

    # --- internal -----------------------------------------------------

    def _refresh(self) -> None:
        """Re-paint the button so its background reflects ``self._color``."""
        qc = QColor(self._color) if self._color else QColor()
        self.setText(self._color)
        if qc.isValid():
            # Pick a foreground colour with enough contrast so the colour
            # name stays readable on top of the swatch. Standard ITU-R
            # BT.601 luma; the 128 threshold is the usual midpoint.
            r, g, b, _ = qc.getRgb()
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            fg = "black" if luma > 128 else "white"
            self.setStyleSheet(
                "QPushButton {"
                f" background-color: {self._color};"
                f" color: {fg};"
                " border: 1px solid #888;"
                " padding: 4px;"
                "}"
            )
        else:
            # Invalid / empty value — keep the system look so the user
            # notices the field is unset.
            self.setStyleSheet("")

    def _pick(self) -> None:
        """Open ``QColorDialog`` and store whatever the user picks."""
        seed = QColor(self._color) if QColor(self._color).isValid() else QColor("white")
        chosen = QColorDialog.getColor(seed, self, "Pick a band colour")
        if chosen.isValid():
            # ``name()`` returns ``#rrggbb`` — universally accepted by
            # both matplotlib and Qt, even though the original workspace
            # may have used SVG colour names like ``"darkgreen"``.
            self._color = chosen.name()
            self._refresh()


# ----------------------------------------------------------------------
# Bool dropdown — used wherever a workspace value is a Python bool
# ----------------------------------------------------------------------


def _make_bool_combo(value: bool) -> QComboBox:
    """
    Build a ``True`` / ``False`` dropdown pre-selected to *value*.

    Item text is the literal Python repr (``"True"`` / ``"False"``) so
    that ``ParametersEditorDialog._coerce`` round-trips it back to a
    Python ``bool`` via its existing ``isinstance(original, bool)``
    branch — no special-cased read path needed.
    """
    combo = QComboBox()
    combo.addItem("True")
    combo.addItem("False")
    combo.setCurrentIndex(0 if bool(value) else 1)
    combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return combo


# ----------------------------------------------------------------------
# Generic parameters editor
# ----------------------------------------------------------------------


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
        # Render as a matrix only when this dict-of-dicts is *actually*
        # shaped like a band table — every inner dict must carry
        # numeric ``low`` / ``high`` and a non-empty string ``color``.
        # Plain ``key in v`` is too loose: an earlier loose check could
        # have written ``low: None / high: None / color: None`` into
        # unrelated sections (e.g. CardioParameters.IbiClassification)
        # on save, and we must not pick those back up as bands.
        if data and all(self._looks_like_band_spec(v) for v in data.values()):
            return self._make_table_group(title, data, prefix)

        group = QGroupBox(_label(title))
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(group)
        layout.setSpacing(4)

        # Render each item in iteration order: scalars become a label+widget
        # row, dicts become nested group boxes. Order is preserved exactly.
        for key, value in data.items():
            path = "{}.{}".format(prefix, key)

            if isinstance(value, dict):
                sub_group = self._make_group(key, value, prefix=path)
                layout.addWidget(sub_group)
            else:
                widget = self._make_widget(key, value, path=path)
                self._widgets[path] = (widget, value)

                row = QHBoxLayout()
                label = QLabel(_label(key) + ":")
                label.setMinimumWidth(160)
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                row.addWidget(label)
                row.addWidget(widget, 1)
                layout.addLayout(row)

        return group

    # ------------------------------------------------------------------
    # Matrix renderer for dict-of-dicts sections (bands)
    # ------------------------------------------------------------------

    # Columns rendered in the band matrix, in display order. Each entry
    # is ``(inner_key, header)``. Any inner keys NOT listed here (e.g.
    # ``alpha`` on the FullRange band) are silently preserved by the
    # deep-copy in ``get_parameters`` — they survive the round-trip
    # without showing up in the editor.
    _TABLE_COLUMNS: tuple[tuple[str, str], ...] = (
        ("low", "Start"),
        ("high", "End"),
        ("color", "Color"),
    )

    @staticmethod
    def _looks_like_band_spec(v: Any) -> bool:
        """True iff *v* is a dict that genuinely describes a frequency band.

        Requires numeric ``low`` and ``high`` and a non-empty string
        ``color``. Bare presence of the keys is not enough — a bug in an
        earlier version could leave ``low / high / color`` set to
        ``None`` in unrelated dicts and we must not promote those to
        a matrix.
        """
        if not isinstance(v, dict):
            return False
        low, high, color = v.get("low"), v.get("high"), v.get("color")
        if not isinstance(low, (int, float)) or isinstance(low, bool):
            return False
        if not isinstance(high, (int, float)) or isinstance(high, bool):
            return False
        if not isinstance(color, str) or not color.strip():
            return False
        return True

    def _make_table_group(self, title: str, data: dict, prefix: str) -> QGroupBox:
        """Render *data* as a matrix: row per outer key, columns per inner key.

        Used for the FrequencyAnalysis bands section. The outer key (band
        name) is shown as a read-only label — renaming a band would
        change its semantic meaning, so renames belong in the JSON
        directly. ``low`` / ``high`` get plain line edits; ``color``
        gets a swatch button that opens ``QColorDialog``.
        """
        group = QGroupBox(_label(title))
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        grid = QGridLayout(group)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        # ---- header row ----
        header_name = QLabel("<b>Name</b>")
        grid.addWidget(header_name, 0, 0)
        for col_idx, (_, header) in enumerate(self._TABLE_COLUMNS, start=1):
            grid.addWidget(QLabel(f"<b>{header}</b>"), 0, col_idx)

        # ---- data rows ----
        for row_idx, (row_key, row_value) in enumerate(data.items(), start=1):
            # Name cell — read-only.
            name_label = QLabel(row_key)
            name_label.setMinimumWidth(120)
            grid.addWidget(name_label, row_idx, 0)

            for col_idx, (inner_key, _) in enumerate(self._TABLE_COLUMNS, start=1):
                cell_value = row_value.get(inner_key)
                cell_path = "{}.{}.{}".format(prefix, row_key, inner_key)
                widget = self._make_cell_widget(inner_key, cell_value)
                self._widgets[cell_path] = (widget, cell_value)
                grid.addWidget(widget, row_idx, col_idx)

        return group

    def _make_cell_widget(self, inner_key: str, value: Any) -> QWidget:
        """Pick the widget for one cell of the band matrix.

        ``color`` cells get a ``_ColorButton`` so the user can pick
        visually; bools get the True / False dropdown so the matrix
        stays consistent with the scalar editor; everything else falls
        back to ``QLineEdit`` (the round-trip coercion in ``_coerce``
        preserves the original Python type).
        """
        if inner_key == "color":
            return _ColorButton("" if value is None else str(value))
        if isinstance(value, bool):
            return _make_bool_combo(value)
        edit = QLineEdit("" if value is None else str(value))
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return edit

    def _make_widget(self, key: str, value: Any, path: str = "") -> QWidget:
        """Return a QComboBox for known enumerations, QLineEdit otherwise.

        Path-specific entries in ``_ENUM_CHOICES`` (e.g. the dotted key
        ``"FrequencyAnalysis.carspan.window"``) win over leaf-key entries
        (e.g. ``"window"``). This lets the same key name offer different
        choice sets in different sections.

        Booleans always render as a True / False dropdown regardless of
        the enum tables — typing "True" / "False" into a free-text field
        is awkward and easy to mistype. ``_coerce`` already converts the
        dropdown's text back to a Python bool on read, so the round-trip
        is invisible to the rest of the dialog.
        """
        # Bool check must precede any int check (and ``isinstance(True, int)``
        # would match an int-typed ``_ENUM_CHOICES`` lookup), so do it first.
        if isinstance(value, bool):
            return _make_bool_combo(value)

        choices = _ENUM_CHOICES.get(path) or _ENUM_CHOICES.get(key)
        if choices is not None:
            combo = QComboBox()
            for choice in choices:
                combo.addItem(choice)
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
