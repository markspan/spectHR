# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blood-pressure timeseries widget.

Plots the continuous blood-pressure waveform carried by a PhysioData
instance as ``data["bp"]`` (the ``BP`` channel of a CARSPAN ``.nff``
file). It is a thin :class:`~spectUI.common.TimelinePlotWidget`: the
shared base owns the main/overview axes, the draggable window and the
navigation bar, while this subclass only says which series to plot and
draws the epoch arrows above it.

The widget shares the ``data.view`` :class:`ViewState` with the other
timeline widgets so panning here keeps the same visible window as the
Preprocessing and IBI views.
"""
from __future__ import annotations

from matplotlib.figure import Figure

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectUI.common import (
    TimelinePlotWidget,
    draw_interval_arrows,
    style_axis_clean,
)

# Timeseries key under which loaders store the blood-pressure waveform
# (nff_loader lowercases the NFF "BP" channel label).
_BP_KEY = "bp"


class BPPlotWidget(TimelinePlotWidget):
    """
    Blood-pressure timeseries viewer.

    Operates on a PhysioData instance exposing ``data["bp"]`` -> a
    :class:`TimeSeries` (times in seconds, values in the recording's
    native blood-pressure units). When no such channel exists
    ``_primary_series`` returns None and the base class draws nothing;
    the MainWindow disables its View-menu entry so it is never shown for
    those recordings.
    """

    overview_color = "blue"

    # ==============================================================
    # Convenience properties
    # ==============================================================

    @property
    def has_bp(self) -> bool:
        """True iff a blood-pressure timeseries is present."""
        return self.data is not None and _BP_KEY in self.data.timeseries

    @property
    def bp_series(self) -> TimeSeries | None:
        """Return the blood-pressure TimeSeries, or None when absent."""
        if not self.has_bp:
            return None
        assert self.data is not None
        return self.data[_BP_KEY].timeseries

    # ==============================================================
    # TimelinePlotWidget hooks
    # ==============================================================

    def _primary_series(self) -> TimeSeries | None:
        return self.bp_series

    def _draw_main(self) -> None:
        """Draw the blood-pressure signal in the main axis."""
        assert self.ax_main is not None
        assert self.data is not None and self.data.view is not None
        bp = self.bp_series
        if bp is None:
            return

        self.ax_main.clear()
        self.ax_main.plot(
            bp.times, bp.values, color="darkblue", linewidth=1.0, alpha=1.0
        )
        #self.ax_main.set_title("Blood Pressure Timeseries")
        self.ax_main.set_ylabel("Blood pressure [mmHg]")
        style_axis_clean(self.ax_main, show_y=True)
        self._set_time_axis(
            self.ax_main,
            self.data.view.x_min,
            self.data.view.x_max,
            show_xlabel=False,
        )

    def _draw_extras(self) -> None:
        self._draw_epochs()

    # ==============================================================
    # Public API
    # ==============================================================

    def bpPlot(
        self,
        data: PhysioData,
        fig: Figure | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
    ) -> Figure:
        """Initialise and display the blood-pressure plot for *data*."""
        return self._plot(data, fig, x_min, x_max)

    # ==============================================================
    # BP-specific overlays
    # ==============================================================

    def _draw_epochs(self) -> None:
        """Draw dataset epochs as stacked horizontal arrows above the BP plot.

        Mirrors PrepPlotWidget: active, valid epochs are clipped to the
        visible window and rendered as labelled interval arrows in the
        annotation layer above the signal axis.
        """
        assert self.ax_main is not None
        assert self.data is not None and self.data.view is not None

        if not hasattr(self.data, "epochs"):
            return

        x_view_min, x_view_max = self.data.view.x_min, self.data.view.x_max

        visible: list[tuple[str, float, float]] = []
        for name, ep in self.data.epochs.items():
            if not getattr(ep, "active", False):
                continue
            if hasattr(ep, "is_valid") and not getattr(ep, "is_valid", True):
                continue
            x0 = max(float(ep.start), x_view_min)
            x1 = min(float(ep.end), x_view_max)
            if x1 <= x0:
                continue
            visible.append((name, x0, x1 ))

        if not visible:
            return

        draw_interval_arrows(
            ax=self.ax_main,
            intervals=visible,
            base_y=1.04,
            lane_step=0.03,
            color="green",
            mutation_scale=18.0,
            linewidth=0.5,
            fontsize=8.0,
        )
