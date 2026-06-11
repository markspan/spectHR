# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
``spectUI.widgets.prep`` — interactive ECG pre-processing and R-peak editing.

This package is the development-branch re-imagining of the V2
``prepPlotWidget``.  Where V2 hung all of its state on a mutable
``PhysioData`` object, the development branch keeps the data model
(:class:`~spectHR.session.Session`) pure and immutable and pushes every
piece of *interaction* state into small, single-purpose, Qt-free objects
that can be unit-tested without a display:

``state``
    :class:`~spectUI.widgets.prep.state.WindowState` and
    :class:`~spectUI.widgets.prep.state.YAxisState` — the visible time
    window, the drag gesture in progress, and per-axis y-zoom state.
``navigation``
    :class:`~spectUI.widgets.prep.navigation.TimelineNavigator` — pure
    zoom / pan / goto arithmetic over a ``WindowState`` and a signal extent.
``rtop_controller``
    :class:`~spectUI.widgets.prep.rtop_controller.RTopController` — the
    mutable R-peak editing API that commits each edit back into
    ``session.events["hrv"]`` as a fresh immutable ``Events``.
``model``
    :class:`~spectUI.widgets.prep.model.PrepModel` — the per-load bundle
    (session + window + navigator + controller + channels) the widget holds
    as a single ``PrepModel | None``.
``widget``
    :class:`~spectUI.widgets.prep.widget.PrepPlotWidget` — the docked Qt
    widget that wires it all onto a matplotlib canvas.

Only :class:`PrepPlotWidget` and :class:`RTopController` are part of the
public surface; the rest are implementation detail re-exported here for
tests.
"""
from spectUI.widgets.prep.model import PrepModel
from spectUI.widgets.prep.navigation import TimelineNavigator
from spectUI.widgets.prep.rtop_controller import RTopController, RTopView
from spectUI.widgets.prep.state import WindowState, YAxisState
from spectUI.widgets.prep.widget import PrepPlotWidget

__all__ = [
    "PrepModel",
    "PrepPlotWidget",
    "RTopController",
    "RTopView",
    "TimelineNavigator",
    "WindowState",
    "YAxisState",
]
