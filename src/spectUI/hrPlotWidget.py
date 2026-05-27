# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import qtawesome as qta
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import MultipleLocator
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QTransform
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.Series.TimeSeries import TimeSeries

# ======================================================================
# View state & helpers
# ======================================================================


@dataclass
class ViewState:
    """
    Holds the current x-range for the widget.
    """

    x_min: float
    x_max: float

    initial_xmin: Optional[float] = None
    initial_xmax: Optional[float] = None
    drag_mode: Optional[str] = None  # "left", "right", "center", or None

    def width(self) -> float:
        return self.x_max - self.x_min

    def center(self) -> float:
        return 0.5 * (self.x_min + self.x_max)


class OverviewWindow:
    """
    Manages the overview rectangle that indicates the current zoom
    window in the overview Axes.
    """

    def __init__(self, ax: Axes, x_min: float, x_max: float) -> None:
        self.ax = ax
        y0, y1 = ax.get_ylim()
        self.patch = patches.Rectangle(
            (x_min, y0),
            x_max - x_min,
            y1 - y0,
            color="blue",
            alpha=0.2,
            animated=False,
        )
        ax.add_patch(self.patch)

    def update_y(self) -> None:
        """
        Update the vertical span of the patch to match current y-limits.
        """
        y0, y1 = self.ax.get_ylim()
        self.patch.set_y(y0)
        self.patch.set_height(y1 - y0)

    def set_window(self, x_min: float, x_max: float) -> None:
        """
        Update rectangle position to new [x_min, x_max] window.
        """
        self.patch.set_x(x_min)
        self.patch.set_width(x_max - x_min)
        self.update_y()


# ======================================================================
# HRPlotWidget (UI + plotting)
# ======================================================================


class HRPlotWidget(QWidget):
    """
    Interactive Heartrate pre-processing widget.

    Responsibilities
    ----------------
    - Displays:
        * HR signal (main axis)
        * Optional breathing signal (if present)
        * Overview plot with draggable window
    - Provides:
        * Navigation: zoom, pan, goto start/end, jump to next/prev abnormal R-top

    It operates on a PhysioData instance with:
        - data["heartrate"] -> StreamAccessor -> TimeSeries (times, values)
        - data.hrv  -> CardioSeries
        - optionally a "breathing..." TimeSeries.
    """

    # --------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # Matplotlib figure and canvas
        self.hrfig: Figure = Figure()
        self.canvas: FigureCanvas = FigureCanvas(self.hrfig)

        # Plot axes
        self.ax_heartrate: Optional[Axes] = None
        self.ax_overview: Optional[Axes] = None
        self._ax_br_twin: Optional[Axes] = None  # breathing overlay axis (twinx)

        # State
        self.data: Optional[PhysioData] = None
        self.overview_window: Optional[OverviewWindow] = None

        # Mpl event ids
        self._mpl_cid_press: Optional[int] = None
        self._mpl_cid_move: Optional[int] = None
        self._mpl_cid_release: Optional[int] = None

        # R-top color mapping
        self.RTopColors = {
            "N": "blue",
            "L": "cyan",
            "S": "magenta",
            "TL": "orange",
            "SL": "turquoise",
            "SNS": "lightseagreen",
        }

        self.navigation_bar = self._create_navigation_bar()

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        layout.addWidget(self.navigation_bar)
        self.setLayout(layout)

        self.setVisible(False)

    def _has_resp_phases(self) -> bool:
        """
        True iff PhysioData carries Phase intervals for the active band.
        """
        if self.data is None:
            return False
        phases = getattr(self.data, "phases", None)
        band = getattr(self.data, "active_band", None)
        if not isinstance(phases, dict) or band is None:
            return False
        return (f"inh-{band}" in phases) or (f"exh-{band}" in phases)

    def _draw_phase_backgrounds(
        self,
        ax: Axes,
        *,
        phase_prefix: str,
        color: str = "#ADD8E6",
        alpha: float = 0.25,
    ) -> None:
        """
        Draw Phase interval backgrounds (axvspan) for the active band.

        Does nothing if:
        - no self.data
        - no self.data.phases
        - no self.data.active_band
        - phase missing or inactive
        """
        if self.data is None:
            return

        phases = getattr(self.data, "phases", None)
        band = getattr(self.data, "active_band", None)
        if not isinstance(phases, dict) or band is None:
            return

        key = f"{phase_prefix}-{band}"
        phase = phases.get(key)
        if phase is None or not getattr(phase, "active", False):
            return

        for start, end in getattr(phase, "intervals", []):
            ax.axvspan(
                float(start),
                float(end),
                color=color,
                alpha=alpha,
                zorder=0,  # behind line plots
                linewidth=0,
            )

    # ==============================================================
    # Convenience properties
    # ==============================================================

    @staticmethod
    def hr_from_hrvseries(hrv) -> TimeSeries:
        """
        Compute a heart-rate TimeSeries (bpm) from a CardioSeries or CardioSeriesView.

        Only beats labelled ``"N"`` (normal) carry a finite HR value.
        Every other label (``"L"``, ``"S"``, ``"TL"``, ``"SL"``,
        ``"SNS"`` ...) and every non-finite / non-positive IBI is
        replaced with ``NaN`` in the output series. ``matplotlib.plot``
        treats ``NaN`` in the y-array as a break in the line, so the
        rendered trace is **discontinuous across the gap** instead of
        bridging straight over the artefact. Drawing a continuous line
        through a dropped beat would suggest a smooth transition that
        didn't happen physiologically.

        Parameters
        ----------
        hrv : CardioSeries | CardioSeriesView
            R-peak times in seconds. Expected to expose ``.times``,
            ``.ibi`` and ``.labels``.

        Returns
        -------
        TimeSeries
            Irregularly sampled HR series the same length as the input,
            with ``NaN`` at every invalid / artefactual position.
        """

        times = np.asarray(hrv.times, dtype=float)
        ibi = np.asarray(hrv.ibi, dtype=float)

        if times.size < 2:
            return TimeSeries(np.array([]), np.array([]))

        # Per-IBI validity: finite, positive, and the beat is normal.
        valid = np.isfinite(ibi) & (ibi > 0)
        labels = getattr(hrv, "labels", None)
        if labels is not None:
            labels_arr = np.asarray(labels)
            if labels_arr.shape == ibi.shape:
                valid &= labels_arr == "N"

        # Same-length output: HR at valid positions, NaN elsewhere.
        # The NaN entries are what makes matplotlib break the line at
        # exactly the right place - there's no bridging across the
        # invalid stretch.
        hr = np.full_like(ibi, np.nan)
        hr[valid] = 60.0 / ibi[valid]

        # X-coordinates: midpoint of the IBI when valid (the standard
        # location for an HR estimate), the R-peak time itself when
        # not. The invalid x doesn't get drawn (its y is NaN), but we
        # keep it finite so neighbouring segments can still autoscale
        # cleanly.
        hr_times = times.copy()
        hr_times[valid] = times[valid] + ibi[valid] / 2.0

        return TimeSeries(hr_times, hr)

    @property
    def heartrate_series(self) -> TimeSeries:
        """Return the Heartrate TimeSeries from PhysioData."""
        assert self.data is not None
        return self.data["heartrate"].timeseries

    @property
    def has_breathing(self) -> bool:
        """Return True if a breathing timeseries exists (by name)."""
        assert self.data is not None
        return any(name.startswith("RSP") for name in self.data.timeseries.keys())

    @property
    def breathing_series(self) -> Optional[TimeSeries]:
        """
        Return the first breathing TimeSeries if present, otherwise None.
        """
        assert self.data is not None
        for name, ts in self.data.timeseries.items():
            if name.startswith("RSP"):
                return ts
        return None

    # ==============================================================
    # UI construction
    # ==============================================================

    def _create_navigation_bar(self) -> QWidget:
        """
        Create the navigation bar with zoom/pan/next/prev controls.
        """

        def make_btn(
            icon_name: Optional[str],
            callback,
            rotate: int | bool = False,
            tooltip: Optional[str] = None,
        ) -> QPushButton:
            btn = QPushButton()
            if icon_name:
                icon = qta.icon(icon_name)
                if rotate:
                    pixmap = icon.pixmap(QSize(48, 48))
                    transform = QTransform().rotate(
                        rotate if isinstance(rotate, int) else 0
                    )
                    rotated_pixmap = pixmap.transformed(transform)
                    icon = QIcon(rotated_pixmap)
                btn.setIcon(icon)
                btn.setIconSize(QSize(48, 48))
            btn.setFlat(True)
            btn.setStyleSheet(
                """
                QPushButton {
                    margin: 4px;
                    width: 56px;
                    height: 56px;
                    border: none;
                }
                """
            )
            btn.clicked.connect(callback)
            if tooltip:
                btn.setToolTip(tooltip)
            return btn

        begin = make_btn(
            "fa6s.right-to-bracket", self.go_to_start, rotate=180, tooltip="Goto Start"
        )
        left = make_btn("fa6s.backward", self.pan_left, tooltip="Pan Left")
        prev = make_btn(
            "fa6s.square-caret-left", self.prev, tooltip="Previous non-normal R-top"
        )
        zoom_in = make_btn("ei.zoom-in", self.zoom_in, tooltip="Zoom In")
        zoom_out = make_btn("ei.zoom-out", self.zoom_out, tooltip="Zoom Out")
        nxt = make_btn(
            "fa6s.square-caret-right", self.next, tooltip="Next non-normal R-top"
        )
        right = make_btn("fa6s.forward", self.pan_right, tooltip="Pan Right")
        end = make_btn(
            "fa6s.right-to-bracket", self.go_to_end, rotate=False, tooltip="Goto End"
        )

        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        for btn in (begin, left, prev, zoom_in, zoom_out, nxt, right, end):
            nav_layout.addWidget(btn)

        nav_widget = QWidget()
        nav_widget.setLayout(nav_layout)
        nav_widget.setFixedHeight(50)
        return nav_widget

    # ==============================================================
    # Public API
    # ==============================================================

    def hrPlot(
        self,
        data: PhysioData,
        fig: Optional[Figure] = None,
        x_min: Optional[float] = None,
        x_max: Optional[float] = None,
    ) -> Figure:
        """
        Initialize and display the pre-processing plot for a PhysioData object.

        Parameters
        ----------
        data : PhysioData
            Dataset with at least rtops.
        fig : Figure, optional
            An existing Matplotlib figure to reuse. If None, a new figure is created.
        x_min : float, optional
            Initial left bound of the visible time window. Defaults to start of series.
        x_max : float, optional
            Initial right bound of the visible time window. Defaults to end of series.

        Returns
        -------
        Figure
            The Matplotlib Figure used for plotting.
        """
        self.data = data
        hr_ts = self.hr_from_hrvseries(self.data.hrv)
        self.data.timeseries["heartrate"] = hr_ts

        self.setVisible(True)
        plt.ioff()  # No blocking windows

        # Determine initial window
        x_min_default = data.hrv.times.min() if data.hrv else 0.0
        x_max_default = data.hrv.times.max() if data.hrv else 100.0

        xmin = x_min if x_min is not None else x_min_default
        xmax = x_max if x_max is not None else x_max_default

        if not hasattr(data, "view"):
            self.data.view = ViewState(x_min=xmin, x_max=xmax)

        # Create or reuse figure/axes
        if fig is None:
            self._create_figure_and_axes()
        else:
            self.hrfig = fig
            self._reuse_axes_from_figure()

        self._setup_matplotlib_canvas()
        self._connect_mpl_events()

        # Draw everything once
        self.redraw()

        return self.hrfig

    # ==============================================================
    # Figure / Axes setup
    # ==============================================================

    def _create_figure_and_axes(self) -> None:
        """
        Create a compact figure with:
        - main heartrate axis
        - overview axis
        Breathing (if available) is rendered via twinx() on the main axis.
        """
        self.hrfig, (ax_hr, ax_overview) = plt.subplots(
            2,
            1,
            figsize=(15, 3),
            sharex=False,
            gridspec_kw={"height_ratios": [5, 1]},
        )

        self.ax_heartrate = ax_hr
        self.ax_overview = ax_overview

    def _reuse_axes_from_figure(self) -> None:
        axes = self.hrfig.axes
        if len(axes) >= 2:
            self.ax_heartrate = axes[0]
            self.ax_overview = axes[-1]
        else:
            self._create_figure_and_axes()

    def _setup_matplotlib_canvas(self) -> None:
        """
        Attach the Matplotlib Figure to the Qt canvas and insert into layout.
        """
        # Hide toolbar/header for embedded use
        self.hrfig.canvas.toolbar_visible = False  # type: ignore[attr-defined]
        self.hrfig.canvas.header_visible = False  # type: ignore[attr-defined]
        self.hrfig.tight_layout()

        # Rebuild Qt canvas. The old canvas must be hidden BEFORE
        # setParent(None), otherwise Qt promotes a previously-visible
        # widget to a top-level window the moment it loses its parent,
        # which surfaces as an orphaned IBI plot in its own window when
        # the IBI dock is the active tab during the swap. deleteLater
        # frees the C++ side on the next event-loop turn.
        old_canvas = self.canvas
        old_canvas.hide()
        old_canvas.setParent(None)
        old_canvas.deleteLater()

        self.canvas = FigureCanvas(self.hrfig)
        # Insert new canvas at index 0: at the top
        self.layout().insertWidget(0, self.canvas)  # type: ignore[arg-type]

    # ==============================================================
    # Matplotlib event wiring
    # ==============================================================

    def _connect_mpl_events(self) -> None:
        """
        Connect mouse events for overview dragging and add-mode clicks.
        """
        if self._mpl_cid_press is not None:
            self.hrfig.canvas.mpl_disconnect(self._mpl_cid_press)
        if self._mpl_cid_move is not None:
            self.hrfig.canvas.mpl_disconnect(self._mpl_cid_move)
        if self._mpl_cid_release is not None:
            self.hrfig.canvas.mpl_disconnect(self._mpl_cid_release)

        self._mpl_cid_press = self.hrfig.canvas.mpl_connect(
            "button_press_event", self._on_press
        )
        self._mpl_cid_move = self.hrfig.canvas.mpl_connect(
            "motion_notify_event", self._on_motion
        )
        self._mpl_cid_release = self.hrfig.canvas.mpl_connect(
            "button_release_event", self._on_release
        )

    # ==============================================================
    # Rendering pipeline
    # ==============================================================
    @staticmethod
    def _style_axis_clean(ax: Axes) -> None:
        """Hide y-axis and remove left/right/top spines (borders)."""
        ax.get_yaxis().set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["top"].set_visible(False)

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

        if show_xlabel:
            ax.set_xlabel("Time (seconds)")
        else:
            ax.set_xlabel("")

    def redraw(self) -> None:
        assert self.data is not None and self.data.view is not None
        assert self.ax_heartrate is not None
        assert self.ax_overview is not None

        self._draw_heartrate()
        self._draw_breathing()  # <-- always call; it will no-op if no breathing
        self._draw_overview()

        self.canvas.draw_idle()

    def _draw_heartrate(self) -> None:
        """
        Draw hartrate signal in the main axis.
        """
        assert self.ax_heartrate is not None and self.data.view is not None
        heartrate = self.data["heartrate"].timeseries

        self.ax_heartrate.clear()
        self.ax_heartrate.plot(
            heartrate.times, heartrate.values, color="red", linewidth=2, alpha=1.0
        )
        # title
        self.ax_heartrate.set_title("IBI Timeseries Signal")
        self._style_axis_clean(self.ax_heartrate)
        self._set_time_axis(
            self.ax_heartrate,
            self.data.view.x_min,
            self.data.view.x_max,
            show_xlabel=False,
        )

    def _draw_breathing(self) -> None:
        """
        Draw breathing signal as a twin y-axis overlay on the heartrate axis.

        Behavior
        --------
        - If no breathing series exists, remove any previous twin axis and return.
        - Otherwise, rebuild the twin axis on each redraw (robust).
        """
        assert self.ax_heartrate is not None
        assert self.data is not None and self.data.view is not None

        ts = self.breathing_series

        # Remove old twin axis to avoid stacking
        if self._ax_br_twin is not None:
            try:
                self._ax_br_twin.remove()
            except Exception:
                pass
            self._ax_br_twin = None

        if ts is None:
            return

        ax_hr = self.ax_heartrate
        self._ax_br_twin = ax_hr.twinx()

        # Optional: phase shading on the HR axis (or on ax_br; pick one)
        if self._has_resp_phases():
            self._draw_phase_backgrounds(
                ax_hr,
                phase_prefix="inh",
                color="#ADD8E6",
                alpha=0.25,
            )

        self._ax_br_twin.plot(
            ts.times,
            ts.values,
            color="green",
            linewidth=0.5,
            alpha=0.3,
            zorder=1,
        )

        self._ax_br_twin.set_xlim(self.data.view.x_min, self.data.view.x_max)

        # Make breathing subtle
        self._ax_br_twin.tick_params(axis="y", colors="green", labelsize=8)
        self._ax_br_twin.spines["right"].set_alpha(0.3)
        self._ax_br_twin.set_ylabel("Breathing", color="green", fontsize=8)

        # Keep behind the HR trace
        self._ax_br_twin.set_zorder(0)
        self._style_axis_clean(self._ax_br_twin)  # removes top/left/right spines too
        # and typically you do NOT want an x-label on the twin axis:
        self._ax_br_twin.set_xlabel("")

    def _draw_overview(self) -> None:
        """
        Draw the overview Heartrate plot and its draggable window rectangle.
        The x-axis of the overview never changes.
        The rectangle is ALWAYS recreated to avoid disappearing after redraws.
        """
        assert self.ax_overview is not None
        assert self.data.view is not None

        heartrate = self.data["heartrate"].timeseries

        # Redraw the overview axis completely.
        self.ax_overview.clear()
        self.ax_overview.plot(
            heartrate.times, heartrate.values, linewidth=0.25, alpha=1, color="green"
        )
        self._style_axis_clean(self.ax_overview)
        self._set_time_axis(
            self.ax_overview,
            float(heartrate.times.min()),
            float(heartrate.times.max()),
            show_xlabel=True,
        )

        # Recreate the rectangle every time - most robust behaviour.
        y0, y1 = self.ax_overview.get_ylim()
        self.overview_window = OverviewWindow(
            self.ax_overview,
            self.data.view.x_min,
            self.data.view.x_max,
        )

    # ==============================================================
    # Navigation helpers
    # ==============================================================

    def _set_window(self, x_min: float, x_max: float) -> None:
        """
        Update the current view window and redraw.
        """
        assert self.data.view is not None
        self.data.view.x_min = float(x_min)
        self.data.view.x_max = float(x_max)
        self.redraw()

    def _constrained_window(self, x_min: float, x_max: float) -> Tuple[float, float]:
        """
        Clamp the window [x_min, x_max] to the heartrate data range.
        """
        heartrate = self.data["heartrate"].timeseries
        global_min = float(heartrate.times.min())
        global_max = float(heartrate.times.max())
        width = x_max - x_min

        x_min = max(global_min, x_min)
        x_max = min(global_max, x_min + width)
        return x_min, x_max

    # ==============================================================
    # Navigation actions (called by toolbar buttons)
    # ==============================================================

    def zoom_in(self) -> None:
        """
        Zoom in by reducing the window width to 1/3 of current.
        """
        assert self.data.view is not None
        width = self.data.view.width() / 3.0
        mid = self.data.view.center()
        new_min = mid - width
        new_max = mid + width
        new_min, new_max = self._constrained_window(new_min, new_max)
        self._set_window(new_min, new_max)

    def zoom_out(self) -> None:
        """
        Zoom out by increasing the window width by factor 1.5.
        """
        assert self.data.view is not None
        width = self.data.view.width() * 1.5
        mid = self.data.view.center()
        new_min = mid - width / 2.0
        new_max = mid + width / 2.0
        new_min, new_max = self._constrained_window(new_min, new_max)
        self._set_window(new_min, new_max)

    def pan_left(self) -> None:
        """
        Pan window left by one window width.
        """
        assert self.data.view is not None
        width = self.data.view.width()
        new_min, new_max = self._constrained_window(
            self.data.view.x_min - width, self.data.view.x_max - width
        )
        self._set_window(new_min, new_max)

    def pan_right(self) -> None:
        """
        Pan window right by one window width.
        """
        assert self.data.view is not None
        width = self.data.view.width()
        new_min, new_max = self._constrained_window(
            self.data.view.x_min + width, self.data.view.x_max + width
        )
        self._set_window(new_min, new_max)

    def go_to_start(self) -> None:
        """
        Move window to the very beginning of the heartrate series.
        """
        assert self.data.view is not None
        heartrate = self.data["heartrate"].timeseries
        width = self.data.view.width()
        start = float(heartrate.times.min())
        self._set_window(start, start + width)

    def go_to_end(self) -> None:
        """
        Move window to the very end of the heartrate series.
        """
        assert self.data.view is not None
        heartrate = self.data["heartrate"].timeseries
        width = self.data.view.width()
        end = float(heartrate.times.max())
        self._set_window(end - width, end)

    def next(self) -> None:
        """
        Jump to next non-normal R-top (label != 'N') after current x_max.
        """
        if self.rtop_ctrl is None or self.data.view is None:
            return
        t = self.rtop_ctrl.next_non_normal(self.data.view.x_max)
        if t is None:
            return
        width = self.data.view.width()
        self._set_window(t - 0.5 * width, t + 0.5 * width)

    def prev(self) -> None:
        """
        Jump to previous non-normal R-top (label != 'N') before current x_min.
        """
        if self.rtop_ctrl is None or self.data.view is None:
            return
        t = self.rtop_ctrl.prev_non_normal(self.data.view.x_min)
        if t is None:
            return
        width = self.data.view.width()
        self._set_window(t - 0.5 * width, t + 0.5 * width)

    # ==============================================================
    # Event handlers (overview drag & add-mode)
    # ==============================================================

    def _on_press(self, event) -> None:
        """
        Matplotlib mouse press callback.

        - If click on overview: start dragging window.
        - If in Add mode and on heartrate axis: add a new R-top at click time.
        """
        if event.inaxes is None or self.data.view is None:
            return

        # Overview drag
        if event.inaxes is self.ax_overview:
            if event.xdata is None:
                return
            self.data.view.initial_xmin = self.data.view.x_min
            self.data.view.initial_xmax = self.data.view.x_max
            width = self.data.view.width()

            # Determine drag mode based on proximity to window edges
            if abs(event.xdata - self.data.view.x_min) < 0.3 * width:
                self.data.view.drag_mode = "left"
            elif abs(event.xdata - self.data.view.x_max) < 0.3 * width:
                self.data.view.drag_mode = "right"
            else:
                self.data.view.drag_mode = "center"

    def _on_motion(self, event) -> None:
        """
        Matplotlib mouse motion callback (while dragging window).
        """
        if event.inaxes is None or self.data.view is None:
            return

        if event.inaxes is self.ax_overview and self.data.view.drag_mode is not None:
            if (
                event.xdata is None
                or self.data.view.initial_xmin is None
                or self.data.view.initial_xmax is None
            ):
                return

            width = self.data.view.initial_xmax - self.data.view.initial_xmin
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
            self.redraw()

    def _on_release(self, event) -> None:
        """
        Matplotlib mouse release callback: finish dragging.
        """
        self.data.view.drag_mode = None
        self.redraw()

