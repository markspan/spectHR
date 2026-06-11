# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
``spectUI.widgets`` — docked plot widgets and utility dialogs.

``MainWindow`` imports widgets from this package only; it never reaches
into the sub-modules directly.

Plot widgets
------------
PrepPlotWidget
    Interactive ECG pre-processing and R-peak annotation (see the
    :mod:`spectUI.widgets.prep` package).

Utility widgets
---------------
DirectorySelectorDialog, ParametersEditorDialog
    Workspace and directory configuration dialogs.
EventCodeWindow
    Code-selection dialog used by the CARSPAN ``.evt`` loader.
LogWidget
    Scrollable log output dock.
"""
from spectUI.widgets.EventCodeWindow import EventCodeWindow
from spectUI.widgets.WorkSpaceEditor import DirectorySelectorDialog, ParametersEditorDialog
from spectUI.widgets.log_widget import LogWidget
from spectUI.widgets.prep import PrepPlotWidget, RTopController

__all__ = [
    # plot widgets
    "PrepPlotWidget",
    "RTopController",
    # utility widgets
    "DirectorySelectorDialog",
    "EventCodeWindow",
    "LogWidget",
    "ParametersEditorDialog",
]
