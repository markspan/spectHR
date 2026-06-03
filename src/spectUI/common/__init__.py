# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectUI.common, small utility modules shared by the plot widgets.

Submodules,

    plot_export   Shift+Ctrl+P figure export mixin and the
                  filesystem-safe filename sanitiser.
    plot_zoom     Up / Down arrow shared y-axis zoom mixin.
    uitools       Assorted GUI helpers (post-export message box,
                  draggable overview rectangle, navigation-bar icon
                  button factory, axis-styling helper, canvas swap,
                  2-column epoch grid, y-zoom shortcuts).
    LineHandler   Draggable vertical-line controller used by the
                  preprocessing widget for R-peak editing.

Callers can import either through this package,

    from spectUI.common import PlotExportMixin, LineHandler

or directly from a submodule when they want only one symbol,

    from spectUI.common.plot_export import sanitize_filename
"""
from __future__ import annotations

from spectUI.common.LineHandler import LineHandler
from spectUI.common.plot_export import PlotExportMixin, sanitize_filename
from spectUI.common.plot_zoom import (
    YZoomMixin,
    Y_TOP_FLOOR,
    Y_ZOOM_STEP_DOWN,
    Y_ZOOM_STEP_UP,
)
from spectUI.common.uitools import (
    OverviewWindow,
    build_epoch_grid,
    make_nav_button,
    show_export_summary,
    style_axis_clean,
    swap_canvas,
    wire_y_zoom_shortcuts,
)
from spectUI.common.timeline import (
    AxisYState,
    EpochName,
    TimeSeconds,
    TimelinePlotWidget,
    ViewState,
    draw_interval_arrows,
)

__all__ = [
    "AxisYState",
    "EpochName",
    "LineHandler",
    "OverviewWindow",
    "PlotExportMixin",
    "TimeSeconds",
    "TimelinePlotWidget",
    "ViewState",
    "YZoomMixin",
    "Y_TOP_FLOOR",
    "Y_ZOOM_STEP_DOWN",
    "Y_ZOOM_STEP_UP",
    "build_epoch_grid",
    "draw_interval_arrows",
    "make_nav_button",
    "sanitize_filename",
    "show_export_summary",
    "style_axis_clean",
    "swap_canvas",
    "wire_y_zoom_shortcuts",
]
