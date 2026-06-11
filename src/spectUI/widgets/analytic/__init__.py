# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
``spectUI.widgets.analytic`` — non-timeline plot docks.

Where :mod:`spectUI.widgets.timeline` covers scrolling signals, these docks
show a single computed figure (e.g. a Poincaré cloud).  They share
:class:`~spectUI.widgets.analytic.base.AnalyticView` — a thin figure/canvas
host with the dock contract (``set_session`` / ``set_epoch`` / ``refresh``) —
and supply only a ``_draw`` method that calls ``spectHR`` and plots.
"""
from spectUI.widgets.analytic.base import AnalyticView
from spectUI.widgets.analytic.poincare import PoincareWidget

__all__ = ["AnalyticView", "PoincareWidget"]
