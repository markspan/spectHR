# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Dock perspective support, dialog + menu controller.

A *perspective* is a snapshot of the QtAds dock layout (which docks
are tabbed where, which are floating, which are hidden), captured via
``CDockManager.addPerspective`` and restored via ``openPerspective``.

This module holds the two pieces that have no business living in
MainWindow,

    PerspectiveManagerDialog
        Modal dialog with a list of saved perspectives, supporting
        Rename and Remove for user-defined entries. Built-ins are
        italicised and read-only.

    PerspectiveMenu
        Helper that owns the View > Layout submenu. MainWindow hands
        it a QMenu and a CDockManager, the helper handles Save /
        Reset / Manage entries and the dynamic list of named
        perspectives.

The capture of the three built-in perspectives stays in MainWindow
because it depends on the concrete dock identities and which one
seeds the centre area, but the names of those built-ins are
declared here so both sides agree.
"""
from __future__ import annotations

from typing import Callable, Optional

from spectHR.Tools.Logger import logger
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Built-in perspective names
#
# Used on both sides of the contract: MainWindow captures these names
# at startup, this module protects them from rename/remove in the UI.
# ---------------------------------------------------------------------------

BUILTIN_DEFAULT  = "Default"
BUILTIN_COMPARE  = "Compare"
BUILTIN_PSDFOCUS = "PSD focus"

BUILTINS: frozenset = frozenset({
    BUILTIN_DEFAULT,
    BUILTIN_COMPARE,
    BUILTIN_PSDFOCUS,
})


# ---------------------------------------------------------------------------
# Perspective manager dialog
# ---------------------------------------------------------------------------


class PerspectiveManagerDialog(QDialog):
    """
    Modal dialog for renaming and removing saved perspectives.

    Built-in perspectives (Default, Compare, PSD focus) appear with
    an italic font and a "read-only" tooltip, the Rename / Remove
    buttons stay disabled while one of them is selected.

    QtAds has no native rename API, so Rename uses a
    save-state / open-old / add-under-new-name / remove-old /
    restore-state sequence around the live dock layout. The
    user's currently displayed layout is preserved across the swap.
    """

    def __init__(
        self,
        dock_manager,
        on_changed: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._dock_manager = dock_manager
        self._on_changed = on_changed

        self.setWindowTitle("Saved perspectives")
        self.setModal(True)
        self.resize(420, 320)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Saved perspectives:"))

        self._list = QListWidget(self)
        self._list.itemSelectionChanged.connect(self._update_buttons)
        self._list.itemDoubleClicked.connect(self._rename_selected)
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._rename_btn = QPushButton("Rename...", self)
        self._remove_btn = QPushButton("Remove",    self)
        close_btn        = QPushButton("Close",     self)
        self._rename_btn.clicked.connect(self._rename_selected)
        self._remove_btn.clicked.connect(self._remove_selected)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._rename_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._populate()

    # ------------------------------------------------------------------
    # List maintenance
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        self._list.clear()
        for name in self._dock_manager.perspectiveNames():
            item = QListWidgetItem(name)
            if name in BUILTINS:
                font = item.font()
                font.setItalic(True)
                item.setFont(font)
                item.setToolTip("Built-in perspective, read-only")
            self._list.addItem(item)
        self._update_buttons()

    def _selected_name(self) -> Optional[str]:
        items = self._list.selectedItems()
        return items[0].text() if items else None

    def _update_buttons(self) -> None:
        name = self._selected_name()
        editable = name is not None and name not in BUILTINS
        self._rename_btn.setEnabled(editable)
        self._remove_btn.setEnabled(editable)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _rename_selected(self, *_args) -> None:
        old = self._selected_name()
        if old is None or old in BUILTINS:
            return
        new, ok = QInputDialog.getText(
            self, "Rename perspective", "New name:", QLineEdit.Normal, old,
        )
        if not ok:
            return
        new = new.strip()
        if not new or new == old:
            return
        if new in self._dock_manager.perspectiveNames():
            QMessageBox.warning(
                self,
                "Name already taken",
                f"A perspective named {new!r} already exists.",
            )
            return
        # The rename swaps layouts under the live dock state; guard it so a
        # mid-swap failure is reported rather than killing the app.
        try:
            live_state = self._dock_manager.saveState()
            self._dock_manager.openPerspective(old)
            self._dock_manager.addPerspective(new)
            self._dock_manager.removePerspective(old)
            self._dock_manager.restoreState(live_state)
        except Exception:
            logger.exception("Failed to rename perspective %r -> %r", old, new)
            QMessageBox.warning(
                self,
                "Rename failed",
                f"Could not rename {old!r} to {new!r}.",
            )
        self._populate()
        if self._on_changed is not None:
            self._on_changed()

    def _remove_selected(self) -> None:
        name = self._selected_name()
        if name is None or name in BUILTINS:
            return
        ans = QMessageBox.question(
            self,
            "Remove perspective",
            f"Remove perspective {name!r}? This cannot be undone.",
        )
        if ans != QMessageBox.Yes:
            return
        self._dock_manager.removePerspective(name)
        self._populate()
        if self._on_changed is not None:
            self._on_changed()


# ---------------------------------------------------------------------------
# Layout menu controller
# ---------------------------------------------------------------------------


class PerspectiveMenu:
    """
    Owns a Layout submenu and keeps it in sync with the dock manager.

    Lifecycle, MainWindow creates one and hands it (parent, dock
    manager, the QMenu to populate). After that the menu rebuilds
    itself on every perspective change. MainWindow only needs to
    call :meth:`rebuild` when an external action (e.g. loading
    perspectives from QSettings) changes the perspective list out
    from under the menu.
    """

    def __init__(
        self,
        parent: QWidget,
        dock_manager,
        menu: QMenu,
    ) -> None:
        self._parent = parent
        self._dock_manager = dock_manager
        self._menu = menu
        self.rebuild()

    def rebuild(self) -> None:
        """Repopulate the menu, fixed entries first, named perspectives after."""
        m = self._menu
        m.clear()

        save_action = QAction("Save current as perspective...", self._parent)
        save_action.triggered.connect(self._save_current)
        m.addAction(save_action)

        reset_action = QAction("Reset to default", self._parent)
        reset_action.triggered.connect(
            lambda: self._open(BUILTIN_DEFAULT)
        )
        m.addAction(reset_action)

        manage_action = QAction("Perspectives...", self._parent)
        manage_action.triggered.connect(self._manage)
        m.addAction(manage_action)

        m.addSeparator()

        for name in self._dock_manager.perspectiveNames():
            action = QAction(name, self._parent)
            action.triggered.connect(
                lambda _checked=False, n=name: self._open(n)
            )
            m.addAction(action)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _open(self, name: str) -> None:
        """Open a perspective via the parent's guarded path when available.

        MainWindow.open_perspective wraps the switch so a mid-switch failure
        is reported and falls back to Default instead of taking the whole
        app down. Fall back to a direct (still guarded) call if the parent
        does not provide it.
        """
        opener = getattr(self._parent, "open_perspective", None)
        if callable(opener):
            opener(name)
            return
        try:
            self._dock_manager.openPerspective(name)
        except Exception:
            logger.exception("Failed to open perspective %r", name)

    def _save_current(self) -> None:
        name, ok = QInputDialog.getText(
            self._parent, "Save perspective", "Perspective name:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        self._dock_manager.addPerspective(name)
        self.rebuild()
        logger.info("Saved layout as perspective %r", name)

    def _manage(self) -> None:
        dlg = PerspectiveManagerDialog(
            self._dock_manager,
            on_changed=self.rebuild,
            parent=self._parent,
        )
        dlg.exec()
