# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
``spectUI.widgets.grid`` — per-epoch computed-figure docks.

The heavy docks (PSD, profiles, transfer, spectrogram) all share one shape:
a scrollable grid with one tile per active epoch, each tile a figure of an
analysis result.  :class:`~spectUI.widgets.grid.base.EpochGridView` owns that
shape — the background compute (off the UI thread via ``DockScheduler``,
with stale-result cancellation) and the grid layout — and concrete docks
supply just two hooks: ``_compute_epoch`` (headless, what to compute per
epoch) and ``_render_tile`` (how to draw it).
"""
from spectUI.widgets.grid.base import EpochGridView
from spectUI.widgets.grid.psd import PSDPlotWidget

__all__ = ["EpochGridView", "PSDPlotWidget"]
