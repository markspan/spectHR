# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Menu bar + toolbar construction for the main window.

Extracted from ``MainWindow`` as a builder that operates on the window: it
creates the actions, the Settings / View / Help menus and the toolbar, and
stores back onto the window the handful of attributes the rest of the class
needs (``_view_actions`` for dock availability, ``_perspective_menu`` for the
layout menu, and the individual ``_*_act`` actions).

Kept as a free function (not a method) purely to move ~90 lines of wiring out
of the window class; it still reads the window's action slots
(``open_workspace`` …) and docks, so it is intentionally window-coupled.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QToolButton, QVBoxLayout, QWidget

from spectUI.docks import VIEW_LABELS
from spectUI.perspectives import PerspectiveMenu

if TYPE_CHECKING:
    from spectUI.main_window import MainWindow


def _make_action(window, icon: str, text: str, slot, shortcut: str | None = None) -> QAction:
    act = QAction(qta.icon(icon), text, window)
    if shortcut:
        act.setShortcut(QKeySequence(shortcut))
    act.triggered.connect(slot)
    return act


def build_menu_and_toolbar(window: "MainWindow") -> None:
    """Build the menus + toolbar on *window* and store back its action handles."""
    window._edit_act     = _make_action(window, "fa5s.cog",              "&Edit settings…",       window.edit_workspace,          "Ctrl+E")
    window._load_act     = _make_action(window, "fa5s.file-import",      "&Load settings…",       window.open_workspace,          "Ctrl+O")
    window._save_act     = _make_action(window, "fa5s.save",             "&Save settings",        window.save_workspace,          "Ctrl+S")
    window._settings_act = _make_action(window, "fa5s.folder-open",      "Directory &settings…",  window.open_directory_settings, "Ctrl+Shift+S")
    window._doc_act      = _make_action(window, "fa5s.question-circle",  "&Documentation",        window._open_docs,              "Ctrl+D")

    # ---- Settings menu ----
    ws_menu = window.menuBar().addMenu("&Settings")
    ws_menu.addAction(window._load_act)
    ws_menu.addSeparator()
    ws_menu.addAction(window._edit_act)
    ws_menu.addAction(window._save_act)
    ws_menu.addSeparator()
    ws_menu.addAction(window._settings_act)
    ws_menu.addSeparator()
    quit_act = QAction("&Quit", window, shortcut=QKeySequence("Ctrl+Q"))
    quit_act.triggered.connect(QApplication.quit)
    ws_menu.addAction(quit_act)

    # ---- View menu ----
    view_menu = window.menuBar().addMenu("&View")
    window._view_actions = {}
    for obj_name, label in VIEW_LABELS.items():
        dock = window._docks.get(obj_name)
        if dock:
            act = dock.toggleViewAction()
            act.setText(label)
            view_menu.addAction(act)
            window._view_actions[obj_name] = act
    view_menu.addSeparator()
    window._perspective_menu = PerspectiveMenu(
        window, window._dock_manager, view_menu.addMenu("&Layout")
    )

    # ---- Help menu ----
    window.menuBar().addMenu("&Help").addAction(window._doc_act)

    # ---- Toolbar ----
    tb = window.addToolBar("Main")
    tb.setObjectName("toolbar.main")
    tb.setMovable(False)
    tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    tb.setIconSize(QSize(20, 20))

    tb.addAction(window._edit_act)

    # Load + Save stacked (half-height)
    pair = QWidget()
    pair.setStyleSheet("background: transparent;")
    vbox = QVBoxLayout(pair)
    vbox.setContentsMargins(2, 2, 2, 2)
    vbox.setSpacing(0)
    for act, label in ((window._load_act, "Load"), (window._save_act, "Save")):
        btn = QToolButton()
        btn.setDefaultAction(act)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setIconSize(QSize(16, 16))
        btn.setText(label)
        btn.setStyleSheet("QToolButton { background: transparent; }")
        vbox.addWidget(btn)
    tb.addWidget(pair)
    tb.addSeparator()

    tb.addAction(window._settings_act)
    tb.addSeparator()
    tb.addAction(window._doc_act)
