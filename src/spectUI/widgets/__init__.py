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
HRSeriesWidget
    Instantaneous heart-rate (tachogram) timeline.

Both are :class:`~spectUI.widgets.timeline.base.TimelineView` docks sharing
the scrolling-window / overview / navigation machinery.

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
from spectUI.widgets.bp import BPSeriesWidget
from spectUI.widgets.grid import PSDPlotWidget
from spectUI.widgets.hr import HRSeriesWidget
from spectUI.widgets.log_widget import LogWidget
from spectUI.widgets.poincare import PoincareWidget
from spectUI.widgets.prep import PrepPlotWidget, RTopController
from spectUI.widgets.results import ResultsTableWidget

__all__ = [
    # plot widgets
    "PrepPlotWidget",
    "HRSeriesWidget",
    "BPSeriesWidget",
    "PoincareWidget",
    "PSDPlotWidget",
    "ResultsTableWidget",
    "RTopController",
    # utility widgets
    "DirectorySelectorDialog",
    "EventCodeWindow",
    "LogWidget",
    "ParametersEditorDialog",
]
