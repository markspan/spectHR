# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`BandSelectorMixin`, a row of band checkboxes for grid docks.

Shared by the Profile and Transfer-Profile docks: a horizontal strip of
coloured checkboxes (one per frequency band) that selects which bands are
drawn.  Toggling re-renders from the cached results (no recompute), the same
way the Poincaré epoch selector works.

A host (an :class:`~spectUI.widgets.grid.base.EpochGridView` subclass) wires it
in three lines:

* ``_build_toolbar`` → call :meth:`_build_band_selector`.
* ``_resolve``       → call :meth:`_refresh_band_selector(bands)`.
* ``_render_tile``   → skip a band when :meth:`_band_selected` is False.
"""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget

from spectUI.common.spectral_plots import band_color


class BandSelectorMixin:
    """Toolbar band checkboxes + selection state for a grid dock."""

    def _build_band_selector(self) -> None:
        self._band_row = QWidget()
        self._band_layout = QHBoxLayout(self._band_row)
        self._band_layout.setContentsMargins(0, 0, 0, 0)
        self._band_layout.setSpacing(8)
        self._band_checks: dict[str, QCheckBox] = {}
        self._selected_bands: set[str] | None = None   # None → not built yet
        self._band_color_table: dict = {}
        # Sits between the base Equal-y checkbox and the trailing stretch.
        self._toolbar.insertWidget(self._toolbar.count() - 1, self._band_row)

    def _toolbar_has_extras(self) -> bool:
        return True   # the band row is always shown

    def _refresh_band_selector(self, bands: dict, names: list[str] | None = None) -> None:
        """(Re)build the checkbox row for *bands* (colours) / *names* (order).

        Selection is preserved across rebuilds; bands added later default on.
        """
        self._band_color_table = bands or {}
        if names is None:
            names = [n for n, s in (bands or {}).items()
                     if isinstance(s, dict) and "low" in s and "high" in s]
        if self._selected_bands is None:
            self._selected_bands = set(names)
        else:
            self._selected_bands |= {n for n in names if n not in self._band_checks}

        while self._band_layout.count():
            item = self._band_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._band_checks = {}
        if names:
            self._band_layout.addWidget(QLabel("Bands:"))
        for n in names:
            cb = QCheckBox(n)
            cb.setChecked(n in self._selected_bands)
            cb.setStyleSheet(f"color:{band_color(self._band_color_table, n)};")
            cb.toggled.connect(lambda on, name=n: self._on_band_toggled(name, on))
            self._band_layout.addWidget(cb)
            self._band_checks[n] = cb

    def _on_band_toggled(self, name: str, on: bool) -> None:
        if on:
            self._selected_bands.add(name)
        else:
            self._selected_bands.discard(name)
        self._rebuild()        # re-render from cached results (no recompute)

    def _band_selected(self, name: str) -> bool:
        return self._selected_bands is None or name in self._selected_bands
