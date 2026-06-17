# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
``spectUI.widgets.prep``, interactive ECG pre-processing and R-peak editing.

The ECG-specific layer on top of :mod:`spectUI.widgets.timeline`.  The
generic scrolling-timeline machinery (window state, navigator, overview,
gesture dispatch) lives in ``timeline``; this package adds only what is
specific to ECG pre-processing:

``rtop_controller``
    :class:`~spectUI.widgets.prep.rtop_controller.RTopController`, the
    mutable R-peak editing facade that commits each edit back into
    ``session.events["hrv"]``.
``model``
    :class:`~spectUI.widgets.prep.model.PrepModel`, the per-load bundle
    (a :class:`~spectUI.widgets.timeline.model.TimelineModel` plus the ECG /
    respiration channels and the editing controller).
``widget``
    :class:`~spectUI.widgets.prep.widget.PrepPlotWidget`, the docked Qt
    widget (a :class:`~spectUI.widgets.timeline.base.TimelineView`).

Only :class:`PrepPlotWidget` and :class:`RTopController` are part of the
public surface; the rest are implementation detail re-exported for tests.
"""
from spectUI.widgets.prep.model import PrepModel
from spectUI.widgets.prep.rtop_controller import RTopController, RTopView
from spectUI.widgets.prep.widget import PrepPlotWidget

__all__ = [
    "PrepModel",
    "PrepPlotWidget",
    "RTopController",
    "RTopView",
]
