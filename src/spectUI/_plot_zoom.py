# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared y-axis zoom behaviour for band-power plot widgets.

Provides
--------
Y_ZOOM_STEP_UP, Y_ZOOM_STEP_DOWN, Y_TOP_FLOOR
    Module-level constants used by both the widget classes and the
    per-subplot constructors that clamp the initial y-top.

YZoomMixin
    Mixin that adds Up/Down arrow zoom to any ``QWidget`` subclass
    that exposes:

    * ``self._y_top``         -- current shared y-max (float)
    * ``self._subplots``      -- list of subplot objects with
                                  ``.ax`` (Axes) and ``.canvas``
                                  (FigureCanvas)
    * ``self._show_spectrogram`` (optional bool) -- when True,
                                  zoom is silently disabled because
                                  the y-axis carries frequency, not
                                  band power.
"""

from __future__ import annotations

Y_ZOOM_STEP_UP:   float = 0.80   # Up arrow   -> y-max * 0.80  (zoom in)
Y_ZOOM_STEP_DOWN: float = 1.25   # Down arrow -> y-max * 1.25  (zoom out)
Y_TOP_FLOOR:      float = 1e-12  # Minimum y-max; prevents axis collapsing to zero


class YZoomMixin:
    """Up/Down arrow shared y-axis zoom, ready to mix into any plot widget."""

    def _zoom_in(self) -> None:
        """Up arrow: shrink the shared y-max (zoom in)."""
        self._set_y_top(self._y_top * Y_ZOOM_STEP_UP)

    def _zoom_out(self) -> None:
        """Down arrow: grow the shared y-max (zoom out)."""
        self._set_y_top(self._y_top * Y_ZOOM_STEP_DOWN)

    def _set_y_top(self, new_y_top: float) -> None:
        """Apply *new_y_top* to every linked subplot and redraw.

        Skipped silently when ``self._show_spectrogram`` is True,
        because spectrogram tiles use a frequency y-axis and the
        band-power zoom scale does not apply to them.

        Clipped to ``Y_TOP_FLOOR`` so repeated Up presses cannot
        collapse the axis to a zero-height range.
        """
        if getattr(self, "_show_spectrogram", False):
            return
        new_y_top = max(float(new_y_top), Y_TOP_FLOOR)
        self._y_top = new_y_top
        for subplot in self._subplots:
            subplot.ax.set_ylim(bottom=0.0, top=new_y_top)
            subplot.canvas.draw_idle()
