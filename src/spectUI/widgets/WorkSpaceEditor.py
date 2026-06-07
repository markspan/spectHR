# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
import re
from typing import Any

from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QCheckBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QFileDialog,
    QStyle,
    QGroupBox,
    QScrollArea,
    QTabWidget,
    QWidget,
    QDialogButtonBox,
    QSizePolicy,
    QComboBox,
    QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


# ======================================================================
# Existing dialog - directory editor (unchanged)
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
# New dialog - dynamic parameters editor
# ======================================================================

# Keys whose sections are handled by other dialogs or are not editable here
_EXCLUDED_SECTIONS = {"Directories"}

# Top-level workspace sections grouped into tabs, in display order. Each
# entry is ``(tab_label, (section_key_1, section_key_2, ...))``. Sections
# that aren't listed here fall into the first ("General") tab so that
# future workspace additions stay editable even before they're explicitly
# routed.
_TAB_LAYOUT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("General Settings",     ("CardioParameters", "RespirationAnalysis", "Calibration", "IcgAnalysis", "Logging")),
    ("PSD Settings",         ("FrequencyAnalysis",)),
    ("Profile Settings",     ("Profiles",)),
    ("Spectrogram Settings", ("Spectrogram",)),
    ("Transfer Settings",    ("TransferAnalysis",)),
)

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
    "Profiles.adaptive_source": ["respiration_channel", "psd_peak"],
    "FrequencyAnalysis.carspan.window": [
        "5% cosine bell",
        "10% cosine bell",
        "20% cosine bell",
        "25% cosine bell",
        "hann",
        "hamming",
        "boxcar",
    ],
    "FrequencyAnalysis.carspan.signal": ["events", "ibi_amplitude"],
    "FrequencyAnalysis.carspan.plot_units": ["mMI²/Hz", "ms²/Hz"],
    "FrequencyAnalysis.welch.units": ["mMI²", "ms²"],
    "FrequencyAnalysis.lombscargle.units": ["mMI²", "ms²"],
    # Spectrogram tile colormap. Diverging and sequential maps that
    # read well at the small tile sizes the Spectrogram dock uses.
    "Spectrogram.colormap": [
        "RdYlBu_r",
        "viridis",
        "magma",
        "inferno",
        "plasma",
        "cividis",
        "Greys",
        "Blues",
        "coolwarm",
        "turbo",
    ],
    # Transfer phase-axis convention. Wrapped is easier to read for
    # structure inside (-pi, pi]; unwrapped accumulates 2 pi jumps and
    # is mainly useful for reading off a constant delay.
    "TransferAnalysis.phase_view": ["wrapped", "unwrapped"],
    # Transfer-function input channel: respiration (RSA) or blood-pressure
    # systolic / diastolic (baroreflex sensitivity). The output is always
    # IBI/HR.
    "TransferAnalysis.input_signal": ["rsp", "bp_sys", "bp_dia"],
    # Minimum severity shown in the Log dock / console (most verbose first).
    "Logging.level": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    "RespirationAnalysis.rsa_overlay": ["rsa", "rsa0", "none"],
    # Respiration source for ICG-capable (VU-AMS) recordings: the thoracic
    # impedance (ICG) signal — what VU-AMS scores RSA from — or the
    # accelerometer chest-wall surrogate.
    "RespirationAnalysis.rsp_source": ["icg", "accelerometer"],
    # Breath rejection guards for the Grossman peak-to-valley RSA algorithm:
    #   none   - no extra rejection (default; legacy spectHR behaviour).
    #   strict - VU-AMS-style irregular-IBI + irregular-rate guards; brings
    #            RSA0 closer to VU-AMS output on noisy/sitting recordings.
    "RespirationAnalysis.rsa_rejection_mode": ["none", "strict"],
}

def _label(key: str) -> str:
    """Turn a snake_case or camelCase key into a human-readable label.

    Keys that already contain a space or a parenthesis are treated as
    *pre-formatted* - the workspace author chose that spelling for the
    dialog and we round-trip it untouched. Without that early return,
    ``.title()`` would mangle ``"window (sec)"`` into ``"Window (Sec)"``
    and re-title other unit-bearing keys in surprising ways.
    """
    # Pre-formatted key - already laid out the way the author wants it
    # shown. Bypass camelCase/snake_case splitting and title-casing.
    if " " in key or "(" in key or ")" in key:
        return key

    # camelCase, words
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", key)
    # underscores, spaces
    s = s.replace("_", " ")
    return s.title()


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


# ----------------------------------------------------------------------
# Generic parameters editor
# ----------------------------------------------------------------------


class ParametersEditorDialog(QDialog):
    """
    Generic dialog that reads *all* non-directory sections from the workspace
    dict and presents them as editable panels, one ``QGroupBox`` per section.

    Nested sub-sections (e.g. FrequencyAnalysis -> welch) each get their own
    nested group box inside the parent panel.

    Scalar leaf values are rendered as:
      - ``QComboBox``  for keys listed in ``_ENUM_CHOICES``
      - ``QLineEdit``  for everything else (int, float, str, None)

    When OK is pressed, ``get_parameters()`` returns a deep copy of the
    workspace with every edited value written back - ready to be merged by
    the caller via ``_deep_merge`` or written straight to disk.
    """

    def __init__(self, workspace: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Parameters")
        self.setModal(True)
        self.resize(800, 720)
        self.setWindowIcon(
            QApplication.style().standardIcon(
                getattr(QStyle, "SP_FileDialogDetailedView")
            )
        )

        # _widgets maps dotted key path -> (widget, original_python_value).
        # The widget type tells get_parameters how to harvest the value:
        # QLineEdit / QPushButton (.text()), QComboBox (.currentText()),
        # _BandMultiSelectWidget (.selected_names()).
        self._widgets: dict[str, tuple[QWidget, Any]] = {}

        # Universe of band names - looked up here so the editor's
        # widget-builder helpers can offer it to the band multiselect.
        self._all_band_names: list[str] = list(
            (workspace.get("FrequencyAnalysis", {}) or {})
            .get("bands", {}).keys()
        )

        # Resolve which top-level section goes into which tab. Sections
        # not mentioned in ``_TAB_LAYOUT`` fall into the first tab
        # ("General Settings"), keeping the editor usable when a new
        # workspace section appears without an explicit tab assignment.
        explicit_routes: dict[str, str] = {
            sec: tab_label
            for tab_label, sec_keys in _TAB_LAYOUT
            for sec in sec_keys
        }
        first_tab_label = _TAB_LAYOUT[0][0] if _TAB_LAYOUT else "General Settings"
        sections_per_tab: dict[str, list[str]] = {
            tab_label: [] for tab_label, _ in _TAB_LAYOUT
        }
        # Sections valid for editing (dict-valued, not excluded).
        present = [
            k for k in workspace
            if k not in _EXCLUDED_SECTIONS and isinstance(workspace[k], dict)
        ]
        present_set = set(present)
        # Order within each tab follows the declared ``_TAB_LAYOUT`` sequence
        # (not the workspace JSON key order), so the editor layout is stable
        # regardless of how a saved workspace happens to order its keys.
        for tab_label, sec_keys in _TAB_LAYOUT:
            for sec in sec_keys:
                if sec in present_set:
                    sections_per_tab[tab_label].append(sec)
        # Any section without an explicit route falls into the first tab, in
        # workspace order, so future additions stay editable before routing.
        for sec in present:
            if sec not in explicit_routes:
                sections_per_tab[first_tab_label].append(sec)

        # ---- one tab per group ------------------------------------------------
        tabs = QTabWidget()
        for tab_label, _ in _TAB_LAYOUT:
            section_keys = sections_per_tab.get(tab_label, [])
            if not section_keys:
                # Always show every declared tab - an empty tab is
                # better than silently dropping a settings category.
                section_keys = []
            tabs.addTab(
                self._build_tab(workspace, section_keys),
                tab_label,
            )

        # ---- OK / Cancel ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addWidget(tabs)
        outer.addWidget(buttons)

    def _build_tab(self, workspace: dict, section_keys: list[str]) -> QWidget:
        """Build one tab pane - a vertical scroll of section group boxes."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(10)

        for section_key in section_keys:
            section_value = workspace.get(section_key)
            if not isinstance(section_value, dict):
                continue
            group = self._make_group(section_key, section_value, prefix=section_key)
            inner_layout.addWidget(group)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    # Recursive group-box builder
    # ------------------------------------------------------------------

    def _make_group(self, title: str, data: dict, prefix: str) -> QGroupBox:
        # Render as a matrix only when this dict-of-dicts is *actually*
        # shaped like a band table - every inner dict must carry
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
        # row, dicts become nested group boxes. Pairs listed in
        # ``_HORIZONTAL_PAIRS`` are emitted side-by-side as one row.
        consumed: set[str] = set()
        items = list(data.items())
        for idx, (key, value) in enumerate(items):
            if key in consumed:
                continue
            path = "{}.{}".format(prefix, key)

            # Horizontal grouping: when (prefix, key) is the head of a
            # configured group AND every follower exists in ``data`` and
            # is a plain scalar (not band-list / adaptive dict / nested
            # dict), render the whole group on one QHBoxLayout row.
            group_followers = self._HORIZONTAL_GROUPS.get(path)
            if (
                group_followers is not None
                and not isinstance(value, dict)
                and all(k in data and not isinstance(data[k], dict)
                        for k in group_followers)
            ):
                # Reject if any member is band-list or adaptive (those
                # carry custom widgets that don't share a row cleanly).
                member_keys = [key] + list(group_followers)
                member_paths = [f"{prefix}.{k}" for k in member_keys]
                if not any(
                    self._is_band_list_path(mp)
                    or self._is_adaptive_bands_path(mp)
                    for mp in member_paths
                ):
                    row = QHBoxLayout()
                    for i, mk in enumerate(member_keys):
                        mp = member_paths[i]
                        mv = value if mk == key else data[mk]
                        w  = self._make_widget(mk, mv, path=mp)
                        self._widgets[mp] = (w, mv)
                        label_txt = self._LABEL_ALIASES.get(mp, _label(mk))
                        lbl = QLabel(label_txt + ":")
                        if i == 0:
                            lbl.setMinimumWidth(160)
                        else:
                            lbl.setMinimumWidth(60)
                        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        if i > 0:
                            row.addSpacing(12)
                        row.addWidget(lbl)
                        row.addWidget(w, 1)
                    layout.addLayout(row)
                    consumed.update(group_followers)
                    continue

            if self._is_adaptive_bands_path(path):
                # adaptive_bands is a dict, so it must be intercepted
                # before the generic isinstance(value, dict) branch.
                widget = _AdaptiveBandWidget(
                    current=dict(value) if isinstance(value, dict) else {},
                    universe=self._all_band_names,
                )
                self._widgets[path] = (widget, value)
                row = QHBoxLayout()
                label = QLabel(_label(key) + ":")
                label.setMinimumWidth(160)
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                row.addWidget(label)
                row.addWidget(widget, 1)
                layout.addLayout(row)
            elif isinstance(value, dict):
                sub_group = self._make_group(key, value, prefix=path)
                layout.addWidget(sub_group)
            elif self._is_band_list_path(path):
                # ``Profiles.bands`` is a list of band names the profile
                # plot should draw. Render it as a multi-select bound to
                # the live band universe so users can't pick names that
                # don't exist (and stale names from a band rename get
                # cleaned up next time the dialog is saved).
                widget = _BandMultiSelectWidget(
                    selected=list(value) if value else [],
                    universe=self._all_band_names,
                )
                self._widgets[path] = (widget, value)
                row = QHBoxLayout()
                label = QLabel(_label(key) + ":")
                label.setMinimumWidth(160)
                label.setAlignment(Qt.AlignRight | Qt.AlignTop)
                row.addWidget(label)
                row.addWidget(widget, 1)
                layout.addLayout(row)
            else:
                widget = self._make_widget(key, value, path=path)
                self._widgets[path] = (widget, value)

                row = QHBoxLayout()
                label_txt = self._LABEL_ALIASES.get(path, _label(key))
                label = QLabel(label_txt + ":")
                label.setMinimumWidth(160)
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                row.addWidget(label)
                row.addWidget(widget, 1)
                layout.addLayout(row)

        # ---- post-loop: wire adaptive_bands selection, grey out siblings
        # When the user picks a band in the adaptive-band dropdown:
        #   * the regular "bands" list is greyed, one adaptive band drives
        #     the profile, the static list is no longer the primary selector.
        #   * the adaptive_source combo is enabled (it becomes meaningful).
        #   * the smooth_breath_freq checkbox is enabled (only relevant when
        #     an adaptive band is active).
        # When "- none -" is selected, reverse all three.
        ab_path            = f"{prefix}.adaptive_bands"
        bands_path         = f"{prefix}.bands"
        source_path        = f"{prefix}.adaptive_source"
        smooth_breath_path = f"{prefix}.smooth_breath_freq"
        if ab_path in self._widgets:
            ab_widget, _ = self._widgets[ab_path]
            if isinstance(ab_widget, _AdaptiveBandWidget):
                has_sel = ab_widget._combo.currentIndex() > 0

                if bands_path in self._widgets:
                    bw, _ = self._widgets[bands_path]
                    bw.setEnabled(not has_sel)
                    ab_widget._combo.currentIndexChanged.connect(
                        lambda idx, w=bw: w.setEnabled(idx == 0)
                    )

                for dep_path in (source_path, smooth_breath_path):
                    if dep_path in self._widgets:
                        dw, _ = self._widgets[dep_path]
                        dw.setEnabled(has_sel)
                        ab_widget._combo.currentIndexChanged.connect(
                            lambda idx, w=dw: w.setEnabled(idx > 0)
                        )

        return group

    # Workspace paths whose value is a list of band names. Each gets
    # rendered as a tick-box band picker (``_BandMultiSelectWidget``)
    # bound to the live universe of band names from
    # ``FrequencyAnalysis.bands`` - so the user can only check bands
    # that actually exist, and stale names left over from a band rename
    # get silently dropped on save.
    _BAND_LIST_PATHS: frozenset[str] = frozenset({
        "Profiles.bands",
    })

    # Groups of leaf keys to render on a single horizontal row.
    # Key: full dotted path of the *first* key in the group (matching the
    # ``path`` variable already in scope inside ``_make_group``).
    # Value: list of sibling key names that follow on the same row.
    # All members must be scalars in the same section; dicts, band-lists,
    # and adaptive-band widgets are never grouped horizontally.
    _HORIZONTAL_GROUPS: dict[str, list[str]] = {
        # General Settings — keep each box compact (one row, except IBI
        # Classification which has four fields and reads better as two rows).
        "CardioParameters.IbiClassification.window_length": ["n_std"],
        "CardioParameters.IbiClassification.max_ibi_sec":   ["min_peak_distance_ms"],
        "CardioParameters.EcgPreprocessing.filter_type":    ["filter_cutoff"],
        "RespirationAnalysis.per_epoch":                    ["rsa_lag_s", "rsa_overlay"],
        "Calibration.bp_scale":                            ["bp_zero"],
        # Transfer
        "TransferAnalysis.f_min":                  ["f_max"],
        "TransferAnalysis.window (sec)":           ["step (sec)"],
        "TransferAnalysis.smooth":                 [
            "show_coherence_threshold", "coherence_mask_alpha",
        ],
        # Profiles
        "Profiles.window (sec)":                   ["step (sec)"],
        "Profiles.smooth_breath_freq":             ["smooth_for_display"],
        # Spectrogram
        "Spectrogram.window (sec)":                ["step (sec)"],
        "Spectrogram.show_respiration_overlay":    ["colormap"],
        # PSD - CARSPAN
        "FrequencyAnalysis.carspan.freq_resolution":    ["signal"],
        "FrequencyAnalysis.carspan.window":             ["plot_units"],
        "FrequencyAnalysis.carspan.smooth_for_display": ["dc_removal"],
        # PSD - Welch
        "FrequencyAnalysis.welch.fs":     ["nperseg", "noverlap", "nfft"],
        "FrequencyAnalysis.welch.window": ["units"],
        # PSD - Lomb-Scargle (all three on one line)
        "FrequencyAnalysis.lombscargle.nfreqs": ["fmin_floor", "units"],
    }

    # Per-path display-label overrides. Workspace key stays untouched
    # (so the saved JSON keeps "units"); only the editor label is
    # remapped. Useful when the editor reads better with a different
    # phrasing than the underlying field name.
    _LABEL_ALIASES: dict[str, str] = {
        "FrequencyAnalysis.welch.units":       "plot units",
        "FrequencyAnalysis.lombscargle.units": "plot units",
    }

    # Path whose value is the adaptive-bands dict. Rendered by
    # ``_AdaptiveBandWidget`` (checkbox + half-width fields per band),
    # not by ``_BandMultiSelectWidget``.
    _ADAPTIVE_BANDS_PATH: str = "Profiles.adaptive_bands"

    @classmethod
    def _is_band_list_path(cls, path: str) -> bool:
        """True for workspace paths whose value is a list of band names."""
        return path in cls._BAND_LIST_PATHS

    @classmethod
    def _is_adaptive_bands_path(cls, path: str) -> bool:
        """True for the adaptive-bands dict path."""
        return path == cls._ADAPTIVE_BANDS_PATH

    # ------------------------------------------------------------------
    # Matrix renderer for dict-of-dicts sections (bands)
    # ------------------------------------------------------------------

    # Columns rendered in the band matrix, in display order. Each entry
    # is ``(inner_key, header)``. Any inner keys NOT listed here (e.g.
    # ``alpha`` on the FullRange band) are silently preserved by the
    # deep-copy in ``get_parameters`` - they survive the round-trip
    # without showing up in the editor.
    #
    # The CARSPAN ``TAnaBand.RespirationBand`` flag intentionally lives
    # on the Profile Settings tab (rendered as a tick-box band list
    # bound to ``Profiles.adaptive_bands``), *not* in this matrix. The
    # flag only affects profile-time band integration; it is not a
    # property of the band itself, so the band matrix on the PSD tab
    # stays focused on Start / End / Color.
    _TABLE_COLUMNS: tuple[tuple[str, str], ...] = (
        ("low", "Start"),
        ("high", "End"),
        ("color", "Color"),
    )

    @staticmethod
    def _looks_like_band_spec(v: Any) -> bool:
        """True iff *v* is a dict that genuinely describes a frequency band.

        Requires numeric ``low`` and ``high`` and a non-empty string
        ``color``. Bare presence of the keys is not enough - a bug in an
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
        name) is shown as a read-only label - renaming a band would
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
            # Name cell - read-only.
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
            return _make_bool_checkbox(value)
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
        the enum tables - typing "True" / "False" into a free-text field
        is awkward and easy to mistype. ``_coerce`` already converts the
        dropdown's text back to a Python bool on read, so the round-trip
        is invisible to the rest of the dialog.
        """
        # Bool check must precede any int check (and ``isinstance(True, int)``
        # would match an int-typed ``_ENUM_CHOICES`` lookup), so do it first.
        if isinstance(value, bool):
            return _make_bool_checkbox(value)

        choices = _ENUM_CHOICES.get(path) or _ENUM_CHOICES.get(key)
        if choices is not None:
            combo = QComboBox()
            for choice in choices:
                # Display label has underscores replaced by spaces for
                # readability; the raw value (with underscores) is stored
                # as UserRole so get_parameters can round-trip it exactly.
                combo.addItem(choice.replace("_", " "), choice)
            current_str = str(value)
            idx = -1
            for i in range(combo.count()):
                if combo.itemData(i, Qt.UserRole) == current_str:
                    idx = i
                    break
            if idx < 0:
                # Fallback: match display text (handles values already
                # stored with spaces from older workspace files).
                display_val = current_str.replace("_", " ")
                idx = combo.findText(
                    display_val, Qt.MatchFixedString | Qt.MatchCaseSensitive
                )
            combo.setCurrentIndex(max(idx, 0))
            return combo

        edit = QLineEdit("" if value is None else str(value))
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return edit

    # ------------------------------------------------------------------
    # Value extraction - coerce back to the original Python type
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
            # Specialised widgets return structured values directly.
            if isinstance(widget, _AdaptiveBandWidget):
                coerced: Any = widget.get_value()
            elif isinstance(widget, _BandMultiSelectWidget):
                coerced = widget.selected_names()
            elif isinstance(widget, QCheckBox):
                # Checkboxes always represent Python bools - read directly,
                # no string coercion needed.
                coerced = widget.isChecked()
            else:
                if isinstance(widget, QComboBox):
                    # Prefer UserRole (raw value stored when enum items were
                    # added with prettified display text); fall back to the
                    # display text for plain True/False combos that carry no
                    # UserRole data.
                    user_data = widget.currentData(Qt.UserRole)
                    raw = user_data if user_data is not None else widget.currentText()
                else:
                    raw = widget.text()

                # Coerce to the type of the original value so floats
                # stay floats and ints stay ints. None and empty
                # strings round-trip back to None.
                if isinstance(original, bool):
                    s = str(raw).strip().lower()
                    coerced = s in ("true", "1", "yes", "on")
                elif isinstance(original, int) and not isinstance(original, bool):
                    try:
                        coerced = int(str(raw).strip())
                    except (TypeError, ValueError):
                        try:
                            coerced = int(float(str(raw).strip()))
                        except (TypeError, ValueError):
                            coerced = original
                elif isinstance(original, float):
                    try:
                        coerced = float(str(raw).strip())
                    except (TypeError, ValueError):
                        coerced = original
                elif original is None:
                    s = str(raw).strip()
                    if s == "" or s.lower() == "none":
                        coerced = None
                    else:
                        try:
                            coerced = int(s)
                        except ValueError:
                            try:
                                coerced = float(s)
                            except ValueError:
                                coerced = s
                else:
                    coerced = str(raw)

            # Walk the dotted path and set the leaf in the deep copy.
            keys = path.split(".")
            node = result
            for k in keys[:-1]:
                if not isinstance(node, dict):
                    node = None
                    break
                if k not in node or not isinstance(node[k], dict):
                    node[k] = {}
                node = node[k]
            if isinstance(node, dict):
                node[keys[-1]] = coerced

        return result
