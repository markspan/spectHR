# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Workspace editor dialogs.

Two public dialogs, split across focused modules:

* :class:`DirectorySelectorDialog` (:mod:`.directory_dialog`) edits the
  workspace ``Directories`` section.
* :class:`ParametersEditorDialog` (:mod:`.parameters_dialog`) edits every other
  section, using the leaf widgets in :mod:`.field_widgets`.

The public names are re-exported here so ``spectUI.widgets.workspace_editor``
stays the single import point it has always been.
"""
from spectUI.widgets.workspace_editor.directory_dialog import DirectorySelectorDialog
from spectUI.widgets.workspace_editor.parameters_dialog import ParametersEditorDialog

__all__ = [
    "DirectorySelectorDialog",
    "ParametersEditorDialog",
]
