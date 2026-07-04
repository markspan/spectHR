# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The generic, workspace-driven parameters editor.

:class:`ParametersEditorDialog` reads every non-directory section of the
workspace dict and presents it as editable panels grouped into tabs.  Leaf
widgets come from :mod:`spectUI.widgets.workspace_editor.field_widgets`.
"""
import copy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from spectUI.widgets.workspace_editor.field_widgets import (
    _AdaptiveBandWidget,
    _BandMultiSelectWidget,
    _ColorButton,
    _label,
    _make_bool_checkbox,
)

# Keys whose sections are handled by other dialogs or are not editable here
_EXCLUDED_SECTIONS = {"Directories"}

# Top-level workspace sections grouped into tabs, in display order. Each
# entry is ``(tab_label, (section_key_1, section_key_2, ...))``. Sections
# that aren't listed here fall into the first ("General") tab so that
# future workspace additions stay editable even before they're explicitly
# routed.
_TAB_LAYOUT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("General Settings",     ("CardioParameters", "RespirationAnalysis",
                              "Calibration", "IcgAnalysis", "PrsaAnalysis",
                              "Logging")),
    ("PSD Settings",         ("FrequencyAnalysis",)),
    ("Profile Settings",     ("Profiles",)),
    ("Spectrogram Settings", ("Spectrogram",)),
    ("Transfer Settings",    ("TransferAnalysis",)),
)

# Known enumeration choices for specific leaf keys
_ENUM_CHOICES: dict[str, list[str]] = {
    # Leaf-key enumerations (apply wherever the key appears)
    "method": ["carspan", "carspan_strict", "welch", "lombscargle", "autoregressive"],
    "window": ["hamming", "hann", "blackman", "bartlett", "boxcar", "quadratic"],
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
    "FrequencyAnalysis.plot_units": ["mMI²/Hz", "ms²/Hz"],
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
    # impedance (ICG) signal, what VU-AMS scores RSA from, or the
    # accelerometer chest-wall surrogate.
    "RespirationAnalysis.rsp_source": ["icg", "accelerometer"],
    # Breath rejection guards for the Grossman peak-to-valley RSA algorithm:
    #   none   - no extra rejection (default; legacy spectHR behaviour).
    #   strict - VU-AMS-style irregular-IBI + irregular-rate guards; brings
    #            RSA0 closer to VU-AMS output on noisy/sitting recordings.
    "RespirationAnalysis.rsa_rejection_mode": ["none", "strict"],
}


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
        # General Settings, keep each box compact (one row, except IBI
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
        # PSD - detrending
        "FrequencyAnalysis.detrend": ["detrend_lambda"],
        # PSD - CARSPAN
        "FrequencyAnalysis.carspan.freq_resolution":    ["signal"],
        "FrequencyAnalysis.carspan.window":             ["smooth_for_display"],
        "FrequencyAnalysis.carspan.smooth_for_display": ["dc_removal"],
        # PSD - Welch
        "FrequencyAnalysis.welch.fs":     ["nperseg", "noverlap", "nfft"],
        # PSD - Lomb-Scargle (both on one line)
        "FrequencyAnalysis.lombscargle.nfreqs": ["fmin_floor"],
    }

    # Per-path display-label overrides. Workspace key stays untouched
    # (so the saved JSON keeps "units"); only the editor label is
    # remapped. Useful when the editor reads better with a different
    # phrasing than the underlying field name.
    _LABEL_ALIASES: dict[str, str] = {
        "FrequencyAnalysis.detrend":           "smoothness-priors detrend",
        "FrequencyAnalysis.detrend_lambda":    "detrend λ (Tarvainen 2002)",
        "FrequencyAnalysis.plot_units":        "plot units (all PSD methods)",
        "FrequencyAnalysis.log_band_power":    "log band power (ln, CARSPAN acLn)",
        "CardioParameters.EcgPreprocessing.display_filtered": "show filtered ECG in plot",
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
