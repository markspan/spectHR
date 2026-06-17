# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
``spectUI.widgets.timeline``, shared scrolling-time-series scaffolding.

Every dock that shows a signal over a draggable time window, the ECG
pre-processor, the HR tachogram, the blood-pressure trace, needs the same
machinery: a visible-window model, zoom / pan / goto navigation, a
full-recording overview strip with a draggable zoom rectangle, epoch
arrows, and debounced repaints.  That machinery lives here once, in
:class:`~spectUI.widgets.timeline.base.TimelineView` and
:class:`~spectUI.widgets.timeline.model.TimelineModel`; concrete docks
supply only their data hooks (what to draw in the main panel, what the
overview trace is, and any extra gestures).
"""
from spectUI.widgets.timeline.base import TimelineView
from spectUI.widgets.timeline.model import TimelineModel
from spectUI.widgets.timeline.navigation import TimelineNavigator
from spectUI.widgets.timeline.state import WindowState, YAxisState

__all__ = [
    "TimelineView",
    "TimelineModel",
    "TimelineNavigator",
    "WindowState",
    "YAxisState",
]
