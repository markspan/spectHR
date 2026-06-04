# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared timeline-viewer scaffolding.

This module factors out the machinery common to every "scrolling
time-series" widget in spectUI: the visible-window state
(:class:`ViewState`), the stacked epoch-arrow renderer
(:func:`draw_interval_arrows`), and the :class:`TimelinePlotWidget`
base class that owns the figure/overview layout, the draggable
overview rectangle, and the zoom/pan/goto navigation bar.

Concrete widgets (HR, blood pressure, ...) subclass
:class:`TimelinePlotWidget` and supply only the data-specific hooks
(:meth:`~TimelinePlotWidget._primary_series`,
:meth:`~TimelinePlotWidget._draw_main`, and optionally
:meth:`~TimelinePlotWidget._draw_extras` / :meth:`~TimelinePlotWidget._prepare`).

The preprocessing widget predates this base class and keeps its own
richer rendering loop, but it imports :class:`ViewState`,
:class:`AxisYState` and :func:`draw_interval_arrows` from here so all
the timeline widgets share one window-state model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import MultipleLocator
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectUI.common.uitools import (
    OverviewWindow,
    make_nav_button,
    style_axis_clean,
    swap_canvas,
)

# ======================================================================
# Type aliases
# ======================================================================

TimeSeconds = float
EpochName = str

# ======================================================================
# View state
# ======================================================================


@dataclass
class AxisYState:
    """
    Stores y-axis state for a single logical axis.

    Attributes
    ----------
    auto:
        If True, y is autoscaled by Matplotlib or the default draw pass.
        If False, ymin/ymax are applied on redraw.
    ymin, ymax:
        Manual limits when auto is False.
    """

    auto: bool = True
    ymin: float | None = None
    ymax: float | None = None


@dataclass
class ViewState:
    """
    Holds the current x-range and drag state for a timeline widget.

    Attributes
    ----------
    x_min, x_max:
        Visible time window in seconds.
    drag_mode:
        Overview drag mode: 'left', 'right', 'center', or None.
    initial_xmin, initial_xmax:
        Window boundaries captured at drag start.
    y:
        Per-signal y axis state. Keys used here: 'ecg', 'br'
    """

    x_min: TimeSeconds
    x_max: TimeSeconds
    drag_mode: str | None = None
    initial_xmin: TimeSeconds | None = None
    initial_xmax: TimeSeconds | None = None
    y: dict[str, AxisYState] = field(
        default_factory=lambda: {
            "br": AxisYState(),
        }
    )

    def width(self) -> TimeSeconds:
        """Return width of the visible x window."""
        return self.x_max - self.x_min

    def center(self) -> TimeSeconds:
        """Return center time of the visible x window."""
        return 0.5 * (self.x_min + self.x_max)


# ======================================================================
# Epoch rendering helper (reusable)
# ======================================================================


def draw_interval_arrows(
    *,
    ax: Axes,
    intervals: Iterable[tuple[EpochName, TimeSeconds, TimeSeconds]],
    base_y: float = 1.04,
    lane_step: float = 0.03,
    color: str = "green",
    mutation_scale: float = 18.0,
    linewidth: float = 0.5,
    fontsize: float = 8.0,
) -> None:
    """
    Draw horizontally stacked interval arrows with centered labels.

    Overlapping intervals are assigned to separate "lanes" (rows) so that
    arrows do not share the same y-position.

    Parameters
    ----------
    ax:
        Target axis (e.g. the main signal axis).
    intervals:
        Iterable of (name, x0, x1) tuples in seconds. Caller is expected to
        have clipped intervals to view range if desired.
    base_y:
        First lane y position, in axis coordinates (fraction).
    lane_step:
        Vertical distance between lanes, in axis coordinates.
    color:
        Arrow and text color.
    mutation_scale:
        Arrow head size in display units (points). This is the Matplotlib
        control that most closely maps to "pixel-ish" sizing.
    linewidth:
        Arrow line width.
    fontsize:
        Label font size.
    """
    intervals_sorted = sorted(intervals, key=lambda it: it[1])
    if not intervals_sorted:
        return

    # lane_ends holds the last end-time assigned per lane (in data units)
    lane_ends: list[TimeSeconds] = []
    for name, x0, x1 in intervals_sorted:
        # Find first lane that does not overlap
        lane_idx = None
        for i, end_t in enumerate(lane_ends):
            if x0 >= end_t:
                lane_idx = i
                lane_ends[i] = x1
                break
        if lane_idx is None:
            lane_idx = len(lane_ends)
            lane_ends.append(x1)

        y = base_y + lane_idx * lane_step
        arrow = FancyArrowPatch(
            (x0, y),
            (x1, y),
            arrowstyle="<->",
            mutation_scale=mutation_scale,
            linewidth=linewidth,
            color=color,
            transform=ax.get_xaxis_transform(),  # x in data units, y in axes fraction
            clip_on=False,
        )
        ax.add_patch(arrow)
        ax.text(
            0.5 * (x0 + x1),
            y,
            name,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=color,
            transform=ax.get_xaxis_transform(),
            clip_on=False,
            bbox=dict(
                facecolor=ax.get_facecolor(),
                edgecolor="none",
                alpha=0.8,
                pad=1.5,
            ),
        )


# ======================================================================
# Base timeline widget
# ======================================================================


class TimelinePlotWidget(QWidget):
    """
    Base class for scrolling time-series viewers.

    Provides the parts every timeline widget shares: a main signal axis,
    a small overview axis carrying a draggable window rectangle, a
    zoom/pan/goto navigation bar, and the mouse-drag plumbing that keeps
    the visible window (stored on the shared ``data.view``
    :class:`ViewState`) in sync across widgets.

    Subclasses supply the data-specific behaviour through hooks:

    ``_primary_series()``
        The :class:`TimeSeries` that drives the window range and the
        overview trace. Return ``None`` to skip plotting entirely (e.g.
        the channel is absent on this recording).
    ``_draw_main()``
        Render the signal into ``self.ax_main``.
    ``_draw_extras()``
        Optional overlays drawn on every redraw (breathing twin axis,
        epoch arrows, ...). Default no-op.
    ``_prepare()``
        Optional one-shot step run as soon as ``self.data`` is set, before
        anything is drawn (e.g. deriving a heart-rate series). Default
        no-op.
    ``_nav_buttons()``
        The navigation-bar buttons. Default is the standard
        goto-start / pan-left / zoom-in / zoom-out / pan-right / goto-end
        set; subclasses can override to add more.
    """

    #: Colour of the overview trace; subclasses may override.
    overview_color: str = "green"

    #: Emitted whenever this widget commits a change to the shared view
    #: window (zoom / pan / goto / overview-drag release). MainWindow uses
    #: it to redraw the other linked timeline docks so they follow along
    #: automatically, without the user having to click in their overview.
    viewChanged = Signal()

    # --------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.fig: Figure = Figure()
        self.canvas: FigureCanvas = FigureCanvas(self.fig)

        self.ax_main: Axes | None = None
        self.ax_overview: Axes | None = None

        self.data: PhysioData | None = None
        self.overview_window: OverviewWindow | None = None

        self._mpl_cid_press: int | None = None
        self._mpl_cid_move: int | None = None
        self._mpl_cid_release: int | None = None

        self.navigation_bar = self._create_navigation_bar()

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.addWidget(self.navigation_bar)
        self.setLayout(layout)

        self.setVisible(False)

    # ==============================================================
    # Hooks for subclasses
    # ==============================================================

    def _primary_series(self) -> TimeSeries | None:
        """Return the series that drives the window range / overview."""
        raise NotImplementedError

    def _draw_main(self) -> None:
        """Draw the signal in ``self.ax_main``."""
        raise NotImplementedError

    def _draw_extras(self) -> None:
        """Draw optional overlays (default: nothing)."""

    def _prepare(self) -> None:
        """One-shot setup once ``self.data`` is assigned (default: nothing)."""

    def _nav_buttons(self) -> tuple[QWidget, ...]:
        """Return the navigation-bar buttons, left to right."""
        return (
            make_nav_button("fa6s.right-to-bracket", self.go_to_start, rotate=180, tooltip="Goto Start"),
            make_nav_button("fa6s.backward",          self.pan_left,               tooltip="Pan Left"),
            make_nav_button("ei.zoom-in",             self.zoom_in,                tooltip="Zoom In"),
            make_nav_button("ei.zoom-out",            self.zoom_out,               tooltip="Zoom Out"),
            make_nav_button("fa6s.forward",           self.pan_right,              tooltip="Pan Right"),
            make_nav_button("fa6s.right-to-bracket",  self.go_to_end,              tooltip="Goto End"),
        )

    # ==============================================================
    # UI construction
    # ==============================================================

    def _create_navigation_bar(self) -> QWidget:
        """Lay out the buttons from :meth:`_nav_buttons` in a fixed bar."""
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        for btn in self._nav_buttons():
            nav_layout.addWidget(btn)
        nav_widget = QWidget()
        nav_widget.setLayout(nav_layout)
        nav_widget.setFixedHeight(20)
        return nav_widget

    # ==============================================================
    # Public template
    # ==============================================================

    def _plot(
        self,
        data: PhysioData,
        fig: Figure | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
    ) -> Figure:
        """
        Initialise and display the plot for *data*.

        Shared template: subclasses expose this under their own name
        (``hrPlot``, ``bpPlot``) so existing call sites keep working.
        Returns early without drawing when ``_primary_series`` is None
        (the channel is absent); callers disable the dock in that case.
        """
        self.data = data
        self._prepare()
        self.setVisible(True)
        plt.ioff()  # No blocking windows

        series = self._primary_series()
        if series is None:
            return self.fig

        if series.times.size:
            default_min = float(series.times.min())
            default_max = float(series.times.max())
        else:
            default_min, default_max = 0.0, 100.0

        xmin = x_min if x_min is not None else default_min
        xmax = x_max if x_max is not None else default_max

        # Reuse the shared ViewState when one already exists so this view
        # stays aligned with the other timeline widgets.
        if getattr(data, "view", None) is None:
            self.data.view = ViewState(x_min=xmin, x_max=xmax)

        if fig is None:
            self._create_figure_and_axes()
        else:
            self.fig = fig
            self._reuse_axes_from_figure()

        self._setup_matplotlib_canvas()
        self._connect_mpl_events()

        self.redraw()
        return self.fig

    # ==============================================================
    # Figure / Axes setup
    # ==============================================================

    def _create_figure_and_axes(self) -> None:
        """Create a compact figure with a main axis and an overview axis."""
        self.fig, (ax_main, ax_overview) = plt.subplots(
            2,
            1,
            figsize=(15, 3),
            sharex=False,
            gridspec_kw={"height_ratios": [5, 1]},
        )
        plt.close(self.fig)  # prevent orphan figure window

        self.ax_main = ax_main
        self.ax_overview = ax_overview

    def _reuse_axes_from_figure(self) -> None:
        axes = self.fig.axes
        if len(axes) >= 2:
            self.ax_main = axes[0]
            self.ax_overview = axes[-1]
        else:
            self._create_figure_and_axes()

    def _setup_matplotlib_canvas(self) -> None:
        """Attach the Figure to the Qt canvas and insert it into the layout."""
        self.fig.canvas.toolbar_visible = False  # type: ignore[attr-defined]
        self.fig.canvas.header_visible = False  # type: ignore[attr-defined]
        self.fig.tight_layout()

        self.canvas = swap_canvas(
            self.layout(),   # type: ignore[arg-type]
            self.canvas,
            self.fig,
            index=0,
        )

    # ==============================================================
    # Matplotlib event wiring
    # ==============================================================

    def _connect_mpl_events(self) -> None:
        """Connect mouse events for overview dragging."""
        for cid in (self._mpl_cid_press, self._mpl_cid_move, self._mpl_cid_release):
            if cid is not None:
                self.fig.canvas.mpl_disconnect(cid)

        self._mpl_cid_press = self.fig.canvas.mpl_connect(
            "button_press_event", self._on_press
        )
        self._mpl_cid_move = self.fig.canvas.mpl_connect(
            "motion_notify_event", self._on_motion
        )
        self._mpl_cid_release = self.fig.canvas.mpl_connect(
            "button_release_event", self._on_release
        )

    # ==============================================================
    # Rendering pipeline
    # ==============================================================

    @staticmethod
    def _set_time_axis(
        ax: Axes, x_min: float, x_max: float, *, show_xlabel: bool
    ) -> None:
        """Set x-limits, ticks, and optionally the x-axis label."""
        ax.set_xlim(x_min, x_max)

        width = max(x_max - x_min, 1e-6)
        tdisp = round(math.log10(width), 0)
        major = math.pow(10, tdisp - 1)

        ax.xaxis.set_major_locator(MultipleLocator(major))
        ax.xaxis.set_minor_locator(MultipleLocator(major / 5.0))

        ax.set_xlabel("Time (seconds)" if show_xlabel else "")

    def redraw(self) -> None:
        assert self.data is not None and self.data.view is not None
        assert self.ax_main is not None
        assert self.ax_overview is not None

        self._draw_main()
        self._draw_extras()
        self._draw_overview()

        self.canvas.draw_idle()

    def _draw_overview(self) -> None:
        """Draw the overview trace and its draggable window rectangle."""
        assert self.ax_overview is not None and self.data is not None
        assert self.data.view is not None
        series = self._primary_series()
        if series is None or series.times.size == 0:
            return

        self.ax_overview.clear()
        self.ax_overview.plot(
            series.times, series.values, linewidth=0.25, alpha=1, color=self.overview_color
        )
        style_axis_clean(self.ax_overview)
        self._set_time_axis(
            self.ax_overview,
            float(series.times.min()),
            float(series.times.max()),
            show_xlabel=True,
        )

        # Recreate the rectangle every time - most robust behaviour.
        self.overview_window = OverviewWindow(
            self.ax_overview,
            self.data.view.x_min,
            self.data.view.x_max,
        )

    # ==============================================================
    # Navigation helpers
    # ==============================================================

    def _can_navigate(self) -> bool:
        """True when there is a non-empty series and an active view window."""
        if self.data is None or getattr(self.data, "view", None) is None:
            return False
        series = self._primary_series()
        return series is not None and series.times.size > 0

    def _set_window(self, x_min: float, x_max: float) -> None:
        """Update the current view window and redraw."""
        assert self.data is not None and self.data.view is not None
        self.data.view.x_min = float(x_min)
        self.data.view.x_max = float(x_max)
        self.redraw()
        self.viewChanged.emit()

    def _constrained_window(self, x_min: float, x_max: float) -> tuple[float, float]:
        """Clamp the window [x_min, x_max] to the primary-series data range."""
        series = self._primary_series()
        assert series is not None
        global_min = float(series.times.min())
        global_max = float(series.times.max())
        width = x_max - x_min

        x_min = max(global_min, x_min)
        x_max = min(global_max, x_min + width)
        return x_min, x_max

    # ==============================================================
    # Navigation actions (called by toolbar buttons)
    # ==============================================================

    def zoom_in(self) -> None:
        """Zoom in by reducing the window width to 1/3 of current."""
        if not self._can_navigate():
            return
        width = self.data.view.width() / 3.0
        mid = self.data.view.center()
        self._set_window(*self._constrained_window(mid - width, mid + width))

    def zoom_out(self) -> None:
        """Zoom out by increasing the window width by factor 1.5."""
        if not self._can_navigate():
            return
        width = self.data.view.width() * 1.5
        mid = self.data.view.center()
        self._set_window(*self._constrained_window(mid - width / 2.0, mid + width / 2.0))

    def pan_left(self) -> None:
        """Pan window left by one window width."""
        if not self._can_navigate():
            return
        width = self.data.view.width()
        self._set_window(
            *self._constrained_window(
                self.data.view.x_min - width, self.data.view.x_max - width
            )
        )

    def pan_right(self) -> None:
        """Pan window right by one window width."""
        if not self._can_navigate():
            return
        width = self.data.view.width()
        self._set_window(
            *self._constrained_window(
                self.data.view.x_min + width, self.data.view.x_max + width
            )
        )

    def go_to_start(self) -> None:
        """Move window to the very beginning of the series."""
        if not self._can_navigate():
            return
        series = self._primary_series()
        assert series is not None
        width = self.data.view.width()
        start = float(series.times.min())
        self._set_window(start, start + width)

    def go_to_end(self) -> None:
        """Move window to the very end of the series."""
        if not self._can_navigate():
            return
        series = self._primary_series()
        assert series is not None
        width = self.data.view.width()
        end = float(series.times.max())
        self._set_window(end - width, end)

    # ==============================================================
    # Event handlers (overview drag)
    # ==============================================================

    def _on_press(self, event) -> None:
        """Start dragging the overview window when the overview is clicked."""
        if event.inaxes is None or self.data is None or self.data.view is None:
            return

        if event.inaxes is self.ax_overview:
            if event.xdata is None:
                return
            self.data.view.initial_xmin = self.data.view.x_min
            self.data.view.initial_xmax = self.data.view.x_max
            width = self.data.view.width()

            if abs(event.xdata - self.data.view.x_min) < 0.3 * width:
                self.data.view.drag_mode = "left"
            elif abs(event.xdata - self.data.view.x_max) < 0.3 * width:
                self.data.view.drag_mode = "right"
            else:
                self.data.view.drag_mode = "center"

    def _on_motion(self, event) -> None:
        """Update the visible window while dragging."""
        if event.inaxes is None or self.data is None or self.data.view is None:
            return

        if event.inaxes is self.ax_overview and self.data.view.drag_mode is not None:
            if (
                event.xdata is None
                or self.data.view.initial_xmin is None
                or self.data.view.initial_xmax is None
            ):
                return

            if self.data.view.drag_mode == "left":
                x_min = min(event.xdata, self.data.view.x_max - 0.1)
                x_max = self.data.view.x_max
            elif self.data.view.drag_mode == "right":
                x_min = self.data.view.x_min
                x_max = max(event.xdata, self.data.view.x_min + 0.1)
            else:  # center
                dx = event.xdata - 0.5 * (
                    self.data.view.initial_xmin + self.data.view.initial_xmax
                )
                x_min = self.data.view.initial_xmin + dx
                x_max = self.data.view.initial_xmax + dx

            x_min, x_max = self._constrained_window(x_min, x_max)
            self.data.view.x_min = x_min
            self.data.view.x_max = x_max

            if self.overview_window is not None:
                self.overview_window.set_window(x_min, x_max)
            self.canvas.draw_idle()

    def _on_release(self, event) -> None:
        """Finish dragging the overview window."""
        if self.data is None or self.data.view is None:
            return
        was_dragging = self.data.view.drag_mode is not None
        self.data.view.drag_mode = None
        self.redraw()
        if was_dragging:
            self.viewChanged.emit()
