# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Reusable leaf-value widgets for the parameters editor.

The generic :class:`~spectUI.widgets.workspace_editor.parameters_dialog.ParametersEditorDialog`
renders each workspace value with one of these: a colour swatch button, a bool
checkbox, the adaptive-band selector, or the band multi-select.  ``_label`` is
the shared snake/camelCase → human-readable key formatter.
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QWidget,
)


def _titlecase(s: str) -> str:
    """Capitalise the first letter of each word, leaving the rest untouched.

    Unlike ``str.title()`` this does **not** lowercase the remainder of a
    word, so acronyms and unit tokens survive: ``"log band power"`` becomes
    ``"Log Band Power"`` and ``"window (sec)"`` becomes ``"Window (sec)"``
    (the ``sec`` is not capitalised because ``(sec)`` starts with ``(``).
    """
    return " ".join(w[:1].upper() + w[1:] if w else w for w in s.split(" "))


def _label(key: str) -> str:
    """Turn a snake_case or camelCase key into a title-cased on-screen label.

    Keys that already contain a space or a parenthesis (e.g. ``"window
    (sec)"``) keep their internal spelling and are only title-cased; other
    keys are first split from snake_case / camelCase.
    """
    if " " in key or "(" in key or ")" in key:
        return _titlecase(key)

    # camelCase, words
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", key)
    # underscores, spaces
    s = s.replace("_", " ")
    return _titlecase(s)


# ----------------------------------------------------------------------
# Colour-picker button used by the bands matrix
# ----------------------------------------------------------------------


class _ColorButton(QPushButton):
    """
    Push button that doubles as a colour swatch and a colour picker.

    The button's *text* is the colour string itself (e.g. ``"darkgreen"``
    or ``"#aa3322"``) - that way the surrounding ``ParametersEditorDialog``
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
            # Invalid / empty value - keep the system look so the user
            # notices the field is unset.
            self.setStyleSheet("")

    def _pick(self) -> None:
        """Open ``QColorDialog`` and store whatever the user picks."""
        seed = QColor(self._color) if QColor(self._color).isValid() else QColor("white")
        chosen = QColorDialog.getColor(seed, self, "Pick a band colour")
        if chosen.isValid():
            # ``name()`` returns ``#rrggbb`` - universally accepted by
            # both matplotlib and Qt, even though the original workspace
            # may have used SVG colour names like ``"darkgreen"``.
            self._color = chosen.name()
            self._refresh()


# ----------------------------------------------------------------------
# Bool dropdown - used wherever a workspace value is a Python bool
# ----------------------------------------------------------------------


def _make_bool_checkbox(value: bool) -> QCheckBox:
    """Build a checkbox for a boolean workspace value.

    ``get_parameters`` reads ``.isChecked()`` directly, so no string
    coercion is needed on the read path.
    """
    cb = QCheckBox()
    cb.setChecked(bool(value))
    return cb


# ----------------------------------------------------------------------
# Multi-selector - used by Profile Settings to pick which bands to plot
# ----------------------------------------------------------------------


class _AdaptiveBandWidget(QWidget):
    """Single-band adaptive-tracking selector: dropdown + half-width fields.

    Renders as one row:

        [- none - v]   below rp (Hz): [0.04]   above rp (Hz): [0.04]

    The dropdown lists every band in the universe plus a "- none -"
    sentinel. Only one band can be adaptive at a time - physiologically,
    adaptive tracking makes sense only for the respiratory band (HF),
    not for multiple bands simultaneously.

    The half-width fields are disabled when "- none -" is selected.

    ``get_value()`` returns a dict with zero or one entry that round-trips
    directly into ``workspace["Profiles"]["adaptive_bands"]``:

        {}                                          # none selected
        {"HF": {"lower half-width (Hz)": 0.04,
                "upper half-width (Hz)": 0.04}}     # HF selected
    """

    _LOW_KEY   = "lower half-width (Hz)"
    _HIGH_KEY  = "upper half-width (Hz)"
    _DEFAULT   = 0.04
    _NONE_TEXT = "- none -"

    def __init__(
        self,
        current: dict,
        universe: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        # Resolve current single selection (take first entry if dict has
        # more than one - legacy multi-band workspaces are collapsed here).
        current_name  = next(iter(current), None)
        current_entry = current.get(current_name, {}) if current_name else {}
        low_val  = float(current_entry.get(self._LOW_KEY,  self._DEFAULT))
        high_val = float(current_entry.get(self._HIGH_KEY, self._DEFAULT))

        # Dropdown: "- none -" first, then band names in universe order.
        self._combo = QComboBox()
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.addItem(self._NONE_TEXT)
        for name in universe:
            self._combo.addItem(name)

        if current_name and current_name in universe:
            self._combo.setCurrentIndex(self._combo.findText(current_name))
        else:
            self._combo.setCurrentIndex(0)

        # Half-width fields - enabled only when a band is selected.
        active = current_name is not None and current_name in universe
        self._lbl_low  = QLabel("below rp (Hz):")
        self._low_edit = QLineEdit(str(low_val))
        self._low_edit.setMaximumWidth(60)

        self._lbl_high  = QLabel("above rp (Hz):")
        self._high_edit = QLineEdit(str(high_val))
        self._high_edit.setMaximumWidth(60)

        for w in (self._lbl_low, self._low_edit, self._lbl_high, self._high_edit):
            w.setEnabled(active)

        self._combo.currentIndexChanged.connect(self._on_selection_changed)

        for w in (self._combo, self._lbl_low, self._low_edit,
                  self._lbl_high, self._high_edit):
            layout.addWidget(w)
        layout.addStretch()

    def _on_selection_changed(self, index: int) -> None:
        enabled = index > 0   # index 0 is "- none -"
        for w in (self._lbl_low, self._low_edit, self._lbl_high, self._high_edit):
            w.setEnabled(enabled)

    def get_value(self) -> dict:
        """Return the workspace-ready dict for ``Profiles.adaptive_bands``."""
        if self._combo.currentIndex() == 0:
            return {}
        name = self._combo.currentText()
        try:
            low = float(self._low_edit.text())
        except ValueError:
            low = self._DEFAULT
        try:
            high = float(self._high_edit.text())
        except ValueError:
            high = self._DEFAULT
        return {name: {self._LOW_KEY: low, self._HIGH_KEY: high}}


class _BandMultiSelectWidget(QListWidget):
    """Tick-box list of band names; ticked items round-trip as a list.

    Each row carries a Qt check-box (``ItemIsUserCheckable``) so users
    pick bands by ticking them rather than by row-selecting them - the
    selection mode is explicitly disabled so the highlight bar doesn't
    fight with the check-state.

    Populated from the live set of band names (the keys of
    ``FrequencyAnalysis.bands``) so the user can only pick bands that
    actually exist. The initial list is whatever the workspace had
    saved, intersected with the universe - silently dropping any stale
    names left over after a band rename.

    ``ParametersEditorDialog`` recognises this widget type in its
    ``get_parameters`` value-extraction loop and reads the ticked rows
    as a Python ``list[str]``.
    """

    def __init__(
        self,
        selected: list[str],
        universe: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Tick-boxes carry the state; row selection would just confuse
        # the visual signal of which bands are picked.
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setMinimumHeight(55)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        selected_set = set(selected or [])
        for name in universe:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if name in selected_set else Qt.Unchecked
            )
            self.addItem(item)

    def selected_names(self) -> list[str]:
        """Return the currently-ticked band names in display order."""
        return [
            self.item(i).text()
            for i in range(self.count())
            if self.item(i).checkState() == Qt.Checked
        ]
