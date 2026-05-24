# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectUI.PrepPlotWidget
======================
Interactive ECG pre-processing and annotation widget for the spectHR/spectUI ecosystem.

This module provides a Qt widget that embeds a Matplotlib figure for:
- ECG signal inspection
- Manual R-peak editing (drag/add/remove) via `LineHandler`
- Optional breathing signal overlay (default) using a twinned y-axis (twinx)
- Epoch visualization as horizontal interval arrows above the ECG axis
- Overview axis with a draggable window rectangle for fast navigation

Key design principles
---------------------
- The widget is a visualization/controller layer: it does not own the underlying data.
- All time coordinates are in dataset time (seconds).
- Breathing, when available, is rendered on a twin y-axis on the same subplot as ECG.
  This keeps the ECG and breathing aligned in x while allowing independent y scaling.
- Epochs are rendered in axis coordinates (y in axes fraction; x in data units) so that:
    * arrows remain anchored to time,
    * labels remain visible when zooming/panning,
    * clip_on=False allows arrows above the plot area.
- Overlapping epochs are stacked into lanes.

Expected PhysioData interface (contract)
----------------------------------------
A `PhysioData` instance is expected to provide:

- data["ecg"].timeseries : TimeSeries
    * `.times`: 1D float array (seconds)
    * `.values`: 1D float array (signal units)
- data.timeseries : Dict[str, TimeSeries]
    * Optional breathing signals exist and are identified by name.startswith("RSP")
      (the first matching series is used)
- data.hrv : Optional[CardioSeries]
    * R-peak times and labels; used for editing/visualization
- data.epochs : Dict[str, Epoch-like]
    Each epoch object must provide:
    * `active: bool`
    * `start: float` (seconds)
    * `end: float` (seconds)
    Optionally:
    * `is_valid: bool` (if present, epochs with is_valid=False are ignored)
- data.view : ViewState
    This widget will attach `data.view` if not present.

Notes
-----
- This file is intended as a drop-in module for spectUI and therefore depends on
  your existing `LineHandler` and spectHR data model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import qtawesome as qta
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import MultipleLocator
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.DataSet.Series.CardioSeriesView import CardioSeriesView
from spectUI.LineHandler import LineHandler

# ======================================================================
# Type aliases
# ======================================================================

TimeSeconds = float
EpochName = str

# ======================================================================
# View state & helpers
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
    ymin: Optional[float] = None
    ymax: Optional[float] = None


@dataclass
class ViewState:
    """
    Holds the current x-range and drag state for the widget.

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
    drag_mode: Optional[str] = None
    initial_xmin: Optional[TimeSeconds] = None
    initial_xmax: Optional[TimeSeconds] = None
    y: Dict[str, AxisYState] = field(
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
    intervals: Iterable[Tuple[EpochName, TimeSeconds, TimeSeconds]],
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
        Target axis (ECG axis).
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
    lane_ends: List[TimeSeconds] = []
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
# R-top controller
# ======================================================================


class RTopController:
    """
    Encapsulates all mutations & queries on a CardioSeries (R-top data).

    This class is purely about *data*: no plotting, no Qt.

    After any mutation to R-peak times, `classify_ibi()` is called
    automatically so that labels always reflect the current IBI values.
    """

    def __init__(self, rtops: CardioSeries) -> None:
        """
        Parameters
        ----------
        rtops:
            The CardioSeries instance to control (mutated in place).
        """
        self.rtops = rtops

    @property
    def times(self) -> np.ndarray:
        """R-top times in seconds."""
        return self.rtops.times

    @property
    def labels(self) -> np.ndarray:
        """Labels aligned to R-top indexing."""
        return self.rtops.labels

    @property
    def ibi(self) -> np.ndarray:
        """Inter-beat intervals in seconds."""
        return self.rtops.ibi

    def _sort_by_time(self) -> None:
        """Keep times & labels sorted ascending by time."""
        order = np.argsort(self.rtops.times)
        self.rtops.times = self.rtops.times[order]
        self.rtops.labels = self.rtops.labels[order]

    def _closest_idx(self, t: float) -> int:
        """Return index of R-top closest in time to t."""
        return int(np.argmin(np.abs(self.rtops.times - t)))

    def move(self, old_t: float, new_t: float) -> None:
        """
        Move the closest R-top around old_t to new_t (seconds).

        Reclassifies all IBIs after the move so that label colours
        reflect the updated intervals immediately on redraw.
        """
        idx = self._closest_idx(old_t)
        self.rtops.times[idx] = float(new_t)
        self._sort_by_time()
        self.rtops.classify_ibi()  # labels must reflect the new IBI values

    def add(self, t: float, label: str = "N") -> None:
        """
        Insert a new R-top at time t with label.

        Reclassifies all IBIs after insertion so that the new interval
        and its neighbours are correctly labelled.

        Parameters
        ----------
        t:
            Time in seconds.
        label:
            Initial label string (default: "N"). Will be overwritten by
            classification unless the series is too short to classify.
        """
        self.rtops.times = np.concatenate(
            [self.rtops.times, np.array([t], dtype=float)]
        )
        self.rtops.labels = np.concatenate(
            [self.rtops.labels, np.array([label], dtype=object)]
        )
        self._sort_by_time()
        self.rtops.classify_ibi()  # labels must reflect the new IBI values

    def delete(self, t: float) -> None:
        """
        Delete the R-top closest to t.

        Reclassifies all IBIs after deletion so that the merged interval
        is correctly labelled.
        """
        idx = self._closest_idx(t)
        mask = np.ones(self.rtops.times.shape[0], dtype=bool)
        mask[idx] = False
        self.rtops.times = self.rtops.times[mask]
        self.rtops.labels = self.rtops.labels[mask]
        self.rtops.classify_ibi()  # labels must reflect the merged interval

    def next_non_normal(self, after_time: float) -> Optional[float]:
        """
        First non-'N' R-top strictly after `after_time`.
        """
        mask = (self.rtops.labels != "N") & (self.rtops.times > after_time)
        if not np.any(mask):
            return None
        return float(self.rtops.times[mask][0])

    def prev_non_normal(self, before_time: float) -> Optional[float]:
        """
        Last non-'N' R-top strictly before `before_time`.
        """
        mask = (self.rtops.labels != "N") & (self.rtops.times < before_time)
        if not np.any(mask):
            return None
        return float(self.rtops.times[mask][-1])

    def window_view(self, x_min: float, x_max: float) -> CardioSeriesView:
        """
        Return a CardioSeriesView restricted to [x_min, x_max].
        """
        return self.rtops.view(x_min, x_max)


# ======================================================================
# Overview window
# ======================================================================


class OverviewWindow:
    """
    Manages the overview rectangle that indicates the current zoom window
    in the overview Axes.
    """

    def __init__(self, ax: Axes, x_min: float, x_max: float) -> None:
        """
        Parameters
        ----------
        ax:
            Overview axis.
        x_min, x_max:
            Window bounds to visualize.
        """
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
        """Update the vertical span of the patch to match current y-limits."""
        y0, y1 = self.ax.get_ylim()
        self.patch.set_y(y0)
        self.patch.set_height(y1 - y0)

    def set_window(self, x_min: float, x_max: float) -> None:
        """Update rectangle position to new [x_min, x_max] window."""
        self.patch.set_x(x_min)
        self.patch.set_width(x_max - x_min)
        self.update_y()


# ======================================================================
# PrepPlotWidget (UI + plotting)
# ======================================================================


class PrepPlotWidget(QWidget):
    """
    Interactive ECG pre-processing widget.

    Responsibilities
    ----------------
    - Displays:
        * ECG signal (main axis)
        * Optional breathing signal overlay (twin y-axis on ECG)
        * Overview plot with draggable window
        * R-top markers and IBI arrows
        * Epoch interval arrows above the ECG axis
    - Provides:
        * Navigation: zoom, pan, goto start/end, jump to next/prev abnormal R-top
        * Editing: Drag / Add / Remove R-tops via LineHandler

    Data expectations
    -----------------
    Operates on a PhysioData instance as described in the module docstring.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initialize the widget UI and set up state containers.
        """
        super().__init__(parent)

        # Matplotlib figure and canvas
        self.fig: Figure = Figure()
        self.canvas: FigureCanvas = FigureCanvas(self.fig)

        # Plot axes
        self.ax_ecg: Optional[Axes] = None
        self.ax_overview: Optional[Axes] = None
        self.ax_br: Optional[Axes] = None
        self._ax_br_twin: Optional[Axes] = None  # breathing overlay axis (twinx)

        # Hovered axis for key interactions
        self._hovered_ax: Optional[Axes] = None

        # State
        self.data: Optional[PhysioData] = None
        self.rtop_ctrl: Optional[RTopController] = None
        self.overview_window: Optional[OverviewWindow] = None
        self.line_handler: Optional[LineHandler] = None
        self.edit_mode: str = "Drag"

        # Matplotlib event ids
        self._mpl_cid_press: Optional[int] = None
        self._mpl_cid_move: Optional[int] = None
        self._mpl_cid_release: Optional[int] = None
        self._mpl_cid_key_press: Optional[int] = None

        # R-top color mapping
        self.RTopColors = {
            "N": "blue",
            "L": "cyan",
            "S": "magenta",
            "TL": "orange",
            "SL": "turquoise",
            "SNS": "lightseagreen",
        }

        # UI elements
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["Drag", "Add", "Remove"])
        self.mode_selector.setFixedWidth(120)
        self.mode_selector.currentTextChanged.connect(self.set_edit_mode)

        self.navigation_bar = self._create_navigation_bar()

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.mode_selector)
        layout.addWidget(self.canvas)
        layout.addWidget(self.navigation_bar)
        self.setLayout(layout)
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def ecg_series(self) -> TimeSeries:
        """
        Return the ECG TimeSeries from PhysioData.

        Returns
        -------
        TimeSeries
            ECG series.
        """
        assert self.data is not None
        return self.data["ecg"].timeseries

    @property
    def breathing_series(self) -> Optional[TimeSeries]:
        """
        Return the first breathing TimeSeries if present, otherwise None.

        Breath series are detected by name.startswith("RSP").

        Returns
        -------
        Optional[TimeSeries]
        """
        assert self.data is not None
        for name, ts in self.data.timeseries.items():
            if name.startswith("RSP"):
                return ts
        return None

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _compact_layout(self) -> None:
        """
        Reduce vertical spacing between subplots.
        Call after axes exist and after major labels are configured.
        """
        self.fig.subplots_adjust(
            left=0.04,
            right=0.995,
            top=0.9,
            bottom=0.05,
            hspace=0.2,  # tight
            wspace=0.08,
        )

    def _create_navigation_bar(self) -> QWidget:
        """
        Create the navigation bar with zoom/pan/next/prev controls.

        Returns
        -------
        QWidget
            A QWidget containing navigation buttons.
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_edit_mode(self, mode: str) -> None:
        """
        Set the current editing mode: "Drag", "Add", or "Remove".
        """
        self.edit_mode = mode
        if self.line_handler is not None:
            self.line_handler.update_mode(mode)

    def prepPlot(
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
        data:
            Dataset with at least an "ecg" TimeSeries and optionally .hrv and breathing.
        fig:
            Existing Matplotlib Figure to reuse. If None, a new figure is created.
        x_min, x_max:
            Initial visible window bounds in seconds. If None, uses ECG extents.

        Returns
        -------
        Figure
            The Matplotlib Figure used for plotting.
        """
        self.data = data

        # Attach R-top controller if available
        self.rtop_ctrl = (
            RTopController(data.hrv) if getattr(data, "hrv", None) is not None else None
        )

        self.setVisible(True)
        plt.ioff()  # avoid pop-up windows

        # Determine initial window from ECG
        ecg = self.ecg_series
        x_min_default = float(np.min(ecg.times))
        x_max_default = float(np.max(ecg.times))
        xmin = float(x_min) if x_min is not None else x_min_default
        xmax = float(x_max) if x_max is not None else x_max_default

        if not hasattr(data, "view") or data.view is None:
            data.view = ViewState(x_min=xmin, x_max=xmax)

        # Create or reuse figure/axes
        if fig is None:
            self._create_figure_and_axes()
        else:
            self.fig = fig
            self._reuse_axes_from_figure()

        self._setup_matplotlib_canvas()
        self._connect_mpl_events()

        # Initialize LineHandler for R-tops (ECG axis required)
        assert self.ax_ecg is not None
        self.line_handler = LineHandler(
            self.ax_ecg,
            callback_drag=self._on_line_drag,
            callback_remove=self._on_line_remove,
        )

        # Draw everything once
        self.redraw()

        # Ensure combo box uses current mode
        if self.mode_selector.currentText() == "":
            self.mode_selector.setCurrentText("Drag")
        self.set_edit_mode(self.mode_selector.currentText())

        return self.fig

    # ------------------------------------------------------------------
    # Figure / Axes setup
    # ------------------------------------------------------------------

    def _create_figure_and_axes(self) -> None:
        """
        Create a compact figure with:
        - a main ECG axis (with optional breathing overlay)
        - an overview axis
        """
        self.fig, (ax_ecg, ax_overview) = plt.subplots(
            2,
            1,
            figsize=(15, 3),
            sharex=False,
            gridspec_kw={"height_ratios": [5, 1]},
        )
        self.ax_ecg, self.ax_overview = ax_ecg, ax_overview
        self._compact_layout()

    def _reuse_axes_from_figure(self) -> None:
        """
        Reuse existing figure's axes (if caller passed a figure).
        Expected:
        - 2 axes: ECG and overview
        """
        axes = self.fig.axes
        if len(axes) == 2:
            self.ax_ecg, self.ax_overview = axes
        else:
            raise RuntimeError(
                "Unexpected number of axes in provided figure; expected 2 (ECG + overview)."
            )

    def _setup_matplotlib_canvas(self) -> None:
        """
        Attach the Matplotlib Figure to the Qt canvas and insert into layout.

        Notes
        -----
        - The canvas is rebuilt so that key events are reliably delivered to Qt.
        """
        # Hide toolbar/header for embedded use (safe if attributes exist)
        try:
            self.fig.canvas.toolbar_visible = False  # type: ignore[attr-defined]
            self.fig.canvas.header_visible = False  # type: ignore[attr-defined]
        except Exception:
            pass

        # Rebuild Qt canvas
        self.canvas.setParent(None)
        self.canvas = FigureCanvas(self.fig)

        # Required for key events
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.setFocus()

        # Replace canvas in layout (index 1: after mode selector)
        self.layout().insertWidget(1, self.canvas)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Matplotlib event wiring
    # ------------------------------------------------------------------

    def _connect_mpl_events(self) -> None:
        """
        Connect mouse and keyboard events.
        """
        if self._mpl_cid_press is not None:
            self.fig.canvas.mpl_disconnect(self._mpl_cid_press)
        if self._mpl_cid_move is not None:
            self.fig.canvas.mpl_disconnect(self._mpl_cid_move)
        if self._mpl_cid_release is not None:
            self.fig.canvas.mpl_disconnect(self._mpl_cid_release)
        if self._mpl_cid_key_press is not None:
            self.fig.canvas.mpl_disconnect(self._mpl_cid_key_press)

        self._mpl_cid_press = self.fig.canvas.mpl_connect(
            "button_press_event", self._on_press
        )
        self._mpl_cid_move = self.fig.canvas.mpl_connect(
            "motion_notify_event", self._on_motion
        )
        self._mpl_cid_release = self.fig.canvas.mpl_connect(
            "button_release_event", self._on_release
        )
        self._mpl_cid_key_press = self.fig.canvas.mpl_connect(
            "key_press_event", self._on_key_press
        )

    # ------------------------------------------------------------------
    # Rendering pipeline
    # ------------------------------------------------------------------

    def redraw(self) -> None:
        """
        Redraw ECG, breathing overlay (if present), epochs, R-tops, overview.
        """
        assert self.data is not None
        assert self.data.view is not None
        assert self.ax_ecg is not None
        assert self.ax_overview is not None

        # ECG is the base layer
        self._draw_ecg()
        # Epoch annotations in axis coords above the ECG (must be after ECG clears)
        self._draw_epochs()
        # Breathing overlay (twinx) is drawn after ECG so it can be stacked "under" ECG
        self._draw_breathing()
        # R-tops and IBI arrows should be on top of everything
        if self.rtop_ctrl is not None:
            self._draw_rtops_and_ibis()
        # Overview plot last
        self._draw_overview()

        self.canvas.draw_idle()

    def _draw_ecg(self) -> None:
        """
        Draw the ECG signal in the main axis.

        Behaviour
        ---------
        - ECG y-scaling is always automatic (no manual zoom or pan).
        - Keyboard y-controls never affect ECG.
        - After autoscaling, the visible y-range is shifted upward to visually
          separate ECG from annotations and breathing.
        """
        assert self.ax_ecg is not None
        assert self.data is not None
        assert self.data.view is not None

        ecg = self.ecg_series

        # Clear and plot ECG
        self.ax_ecg.clear()
        self.ax_ecg.plot(
            ecg.times,
            ecg.values,
            color="red",
            linewidth=0.8,
            alpha=1.0,
            zorder=2,
        )

        # Styling (no y-axis, no top/side spines)
        self._style_axis_clean(self.ax_ecg)

        # Time window
        self._set_time_axis(self.ax_ecg, self.data.view.x_min, self.data.view.x_max)

        # ------------------------------------------------------------
        # Y-scaling
        # ------------------------------------------------------------
        if self.ax_br is None:
            # No breathing → normal autoscale
            self.ax_ecg.relim()
            self.ax_ecg.autoscale_view(scalex=False, scaley=True)
            return

        # ------------------------------------------------------------
        # Breathing present → lift ECG upward
        # ------------------------------------------------------------
        self.ax_ecg.relim()
        self.ax_ecg.autoscale(enable=True, axis="y")

        # ------------------------------------------------------------------
        # Shift ECG upward for visual separation
        # ------------------------------------------------------------------
        y0, y1 = self.ax_ecg.get_ylim()
        yr = y1 - y0
        if np.isfinite(yr) and yr > 0:
            dy = 0.2 * yr  # visual offset fraction
            self.ax_ecg.set_ylim(y0 - dy, y1 - dy)

        # If breathing exists below, hide ECG x-axis
        if getattr(self, "_ax_br_twin", None) is not None:
            self.ax_ecg.get_xaxis().set_visible(False)
            self.ax_ecg.spines["bottom"].set_visible(False)
            self.ax_ecg.set_xlabel("")

    def _draw_breathing(self) -> None:
        """
        Draw breathing signal as a twin y-axis overlay on the ECG axis.

        Safe behavior
        -------------
        - If no breathing series exists, remove any previous twin axis and return.
        - Otherwise, rebuild the twin axis on each redraw for robustness.
        """
        assert self.ax_ecg is not None
        assert self.data is not None and self.data.view is not None

        ts = self.breathing_series

        # Remove any existing twin axis to avoid stale overlays after redraws
        if self._ax_br_twin is not None:
            try:
                self._ax_br_twin.remove()
            except Exception:
                pass
            self._ax_br_twin = None

        if ts is None:
            return

        ax_ecg = self.ax_ecg
        self._ax_br_twin = ax_ecg.twinx()

        self._draw_phase_backgrounds(
            self.ax_ecg,
            phase_prefix="inh",
            color="#ADD8E6",
            alpha=0.25,
        )

        ax_br = self._ax_br_twin
        ax_br.plot(
            ts.times,
            ts.values,
            color="green",
            linewidth=1,
            alpha=1.0,
            zorder=1,
        )
        ax_br.set_xlim(self.data.view.x_min, self.data.view.x_max)

        # Apply manual y-limits if set
        ystate = self.data.view.y["br"]
        if not ystate.auto and ystate.ymin is not None and ystate.ymax is not None:
            ax_br.set_ylim(ystate.ymin, ystate.ymax)

        # Visual style: keep breathing subtle and clearly distinguishable
        ax_br.tick_params(axis="y", colors="green", labelsize=8)
        ax_br.spines["right"].set_alpha(0.3)
        self._style_axis_clean(ax_br)
        ax_br.set_ylabel("Breathing", color="green", fontsize=8)

        # Keep breathing visually "under" the ECG
        ax_br.set_zorder(0)

    def _draw_phase_backgrounds(
        self,
        ax,
        *,
        phase_prefix: str,
        color: str = "#ADD8E6",
        alpha: float = 0.25,
    ) -> None:
        """
        Draw background shading for Phase intervals.

        Parameters
        ----------
        ax:
            Matplotlib Axes to draw on.
        phase_prefix:
            Phase name prefix (e.g. "inh").
        color:
            Fill color.
        alpha:
            Transparency.
        """
        if self.data is None or not hasattr(self.data, "phases"):
            return
        band = self.data.active_band
        if band is None:
            return
        key = f"{phase_prefix}-{band}"
        phase = self.data.phases.get(key)
        if phase is None or not phase.active:
            return
        for start, end in phase.intervals:
            ax.axvspan(
                start,
                end,
                color=color,
                alpha=alpha,
                zorder=0,  # behind signals
                linewidth=0,
            )

    def _draw_epochs(self) -> None:
        """
        Draw dataset epochs as stacked horizontal arrows above the ECG plot.
        Overlapping epochs are placed on separate vertical lanes.
        """
        assert self.ax_ecg is not None
        assert self.data is not None and self.data.view is not None

        if not hasattr(self.data, "epochs"):
            return

        ax = self.ax_ecg
        x_view_min, x_view_max = self.data.view.x_min, self.data.view.x_max

        visible: List[Tuple[EpochName, TimeSeconds, TimeSeconds]] = []
        for name, ep in self.data.epochs.items():
            if not getattr(ep, "active", False):
                continue
            if hasattr(ep, "is_valid") and not getattr(ep, "is_valid", True):
                continue
            x0 = max(float(ep.start), x_view_min)
            x1 = min(float(ep.end), x_view_max)
            if x1 <= x0:
                continue
            visible.append((name, x0, x1))

        if not visible:
            return

        draw_interval_arrows(
            ax=ax,
            intervals=visible,
            base_y=1.04,
            lane_step=0.03,
            color="green",
            mutation_scale=18.0,
            linewidth=0.5,
            fontsize=8.0,
        )

    def _draw_rtops_and_ibis(self) -> None:
        """
        Draw R-top markers and IBI arrows in the ECG axis.

        Design
        ------
        - R-top vertical markers live in DATA coordinates
        - IBI arrows and labels live in AXIS coordinates (annotation layer)
        - No y-axis manipulation is required
        - Robust against zooming, autoscale, breathing overlay, etc.
        """
        assert self.rtop_ctrl is not None
        assert self.ax_ecg is not None
        assert self.data is not None and self.data.view is not None
        assert self.line_handler is not None

        rt_view = self.rtop_ctrl.window_view(
            self.data.view.x_min - 1,
            self.data.view.x_max + 1,
        )
        times = rt_view.times
        labels = rt_view.labels
        ibi = rt_view.ibi  # last is NaN

        # Clear existing draggable lines
        self.line_handler.clear()

        # If too many markers, abort to keep UI responsive
        if times.size > 100:
            return

        # --------------------------------------------------
        # R-top vertical markers (DATA coordinates)
        # --------------------------------------------------
        for i in range(times.size):
            t = float(times[i])
            lab = str(labels[i])
            color = self.RTopColors.get(lab, "blue")
            self.line_handler.add_line(t, color=color)

        # --------------------------------------------------
        # IBI arrows + labels (AXIS coordinates)
        # --------------------------------------------------
        y_axis = 0.985  # axis fraction, slightly above ECG trace

        for i in range(times.size):
            if i >= ibi.size:
                continue
            ibi_val = float(ibi[i])
            if np.isnan(ibi_val) or ibi_val <= 0.0:
                continue

            t0 = float(times[i])
            t1 = t0 + ibi_val

            # Arrow
            arrow = FancyArrowPatch(
                (t0, y_axis),
                (t1, y_axis),
                arrowstyle="<->",
                color="blue",
                mutation_scale=10,
                linewidth=0.8,
                transform=self.ax_ecg.get_xaxis_transform(),
                clip_on=False,
                zorder=5,
            )
            self.ax_ecg.add_patch(arrow)

            # Label (centered horizontally AND vertically on arrow)
            self.ax_ecg.text(
                t0 + 0.5 * ibi_val,
                y_axis,
                f"{1000.0 * ibi_val:.0f}",
                ha="center",
                va="center",
                fontsize=6,
                color="blue",
                transform=self.ax_ecg.get_xaxis_transform(),
                zorder=10,
                bbox=dict(
                    facecolor=self.ax_ecg.get_facecolor(),
                    edgecolor="none",
                    alpha=1.0,
                    pad=1.2,
                ),
                clip_on=False,
            )

        # --------------------------------------------------
        # Ensure draggable R-top lines span full visible height
        # --------------------------------------------------
        for dl in self.line_handler.draggable_lines:
            dl.update_y_extent()

    def _draw_overview(self) -> None:
        """
        Draw overview ECG plot and its draggable window rectangle.

        Notes
        -----
        - Overview x-axis never changes.
        - Rectangle is recreated each redraw for robustness.
        """
        assert self.ax_overview is not None
        assert self.data is not None and self.data.view is not None

        ecg = self.ecg_series
        self.ax_overview.clear()
        self.ax_overview.plot(
            ecg.times,
            ecg.values,
            linewidth=0.25,
            alpha=0.5,
            color="blue",
        )
        self.ax_overview.set_title("")
        self.ax_overview.set_yticks([])
        self._style_axis_clean(self.ax_overview)

        self.overview_window = OverviewWindow(
            self.ax_overview,
            self.data.view.x_min,
            self.data.view.x_max,
        )

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _set_window(self, x_min: float, x_max: float) -> None:
        """Update view window and redraw."""
        assert self.data is not None and self.data.view is not None
        self.data.view.x_min = float(x_min)
        self.data.view.x_max = float(x_max)
        self.redraw()

    def _constrained_window(self, x_min: float, x_max: float) -> Tuple[float, float]:
        """Clamp window to ECG time range."""
        ecg = self.ecg_series
        global_min = float(np.min(ecg.times))
        global_max = float(np.max(ecg.times))
        width = x_max - x_min
        x_min = max(global_min, x_min)
        x_max = min(global_max, x_min + width)
        return x_min, x_max

    # ------------------------------------------------------------------
    # Navigation actions (toolbar)
    # ------------------------------------------------------------------

    def zoom_in(self) -> None:
        """Zoom in by reducing window width to 1/3."""
        assert self.data is not None and self.data.view is not None
        width = self.data.view.width() / 3.0
        mid = self.data.view.center()
        new_min = mid - width
        new_max = mid + width
        new_min, new_max = self._constrained_window(new_min, new_max)
        self._set_window(new_min, new_max)

    def zoom_out(self) -> None:
        """Zoom out by increasing window width by factor 1.5."""
        assert self.data is not None and self.data.view is not None
        width = self.data.view.width() * 1.5
        mid = self.data.view.center()
        new_min = mid - width / 2.0
        new_max = mid + width / 2.0
        new_min, new_max = self._constrained_window(new_min, new_max)
        self._set_window(new_min, new_max)

    def pan_left(self) -> None:
        """Pan window left by one window width."""
        assert self.data is not None and self.data.view is not None
        width = self.data.view.width()
        new_min, new_max = self._constrained_window(
            self.data.view.x_min - width, self.data.view.x_max - width
        )
        self._set_window(new_min, new_max)

    def pan_right(self) -> None:
        """Pan window right by one window width."""
        assert self.data is not None and self.data.view is not None
        width = self.data.view.width()
        new_min, new_max = self._constrained_window(
            self.data.view.x_min + width, self.data.view.x_max + width
        )
        self._set_window(new_min, new_max)

    def go_to_start(self) -> None:
        """Move window to start of ECG."""
        assert self.data is not None and self.data.view is not None
        ecg = self.ecg_series
        width = self.data.view.width()
        start = float(np.min(ecg.times))
        self._set_window(start, start + width)

    def go_to_end(self) -> None:
        """Move window to end of ECG."""
        assert self.data is not None and self.data.view is not None
        ecg = self.ecg_series
        width = self.data.view.width()
        end = float(np.max(ecg.times))
        self._set_window(end - width, end)

    def next(self) -> None:
        """Jump to next non-normal R-top after current x_max."""
        if self.rtop_ctrl is None or self.data is None or self.data.view is None:
            return
        t = self.rtop_ctrl.next_non_normal(self.data.view.x_max)
        if t is None:
            return
        width = self.data.view.width()
        self._set_window(t - 0.5 * width, t + 0.5 * width)

    def prev(self) -> None:
        """Jump to previous non-normal R-top before current x_min."""
        if self.rtop_ctrl is None or self.data is None or self.data.view is None:
            return
        t = self.rtop_ctrl.prev_non_normal(self.data.view.x_min)
        if t is None:
            return
        width = self.data.view.width()
        self._set_window(t - 0.5 * width, t + 0.5 * width)

    # ------------------------------------------------------------------
    # Event handlers (overview drag & add-mode)
    # ------------------------------------------------------------------

    def _axis_key(self, ax: Axes) -> Optional[str]:
        """
        Map an Axes instance to the ViewState y-key.

        Returns
        -------
        Optional[str]
            "ecg" for the main ECG axis, "br" for the breathing overlay axis,
            None otherwise.
        """
        if ax is self._ax_br_twin:
            return "br"
        return None

    def _autoscale_visible_y(self, ax: Axes) -> None:
        """
        Autoscale y-axis using only data visible in the current x-window.
        This is used for '=' key.
        """
        assert self.data is not None and self.data.view is not None
        x0, x1 = self.data.view.x_min, self.data.view.x_max

        if ax is self.ax_ecg:
            ts = self.ecg_series
        elif ax is self._ax_br_twin:
            ts = self.breathing_series
            if ts is None:
                return
        else:
            return

        mask = (ts.times >= x0) & (ts.times <= x1)
        if not np.any(mask):
            return
        y = ts.values[mask]
        ymin, ymax = float(np.min(y)), float(np.max(y))
        if ymin == ymax:
            eps = 1e-6 if ymin == 0 else abs(ymin) * 1e-3
            ymin -= eps
            ymax += eps
        ax.autoscale(enable=False, axis="y")
        ax.set_ylim(ymin, ymax)

    def _active_y_axis(self, event) -> Optional[Axes]:
        """
        Decide which y-axis should receive y-scaling key events.

        Priority:
        1) Breathing axis if present
        2) ECG axis otherwise
        """
        if self._ax_br_twin is not None:
            return self._ax_br_twin
        return self.ax_ecg

    def _on_key_press(self, event) -> None:
        """
        Keyboard handling for y-axis scaling:
        - SPACE: reset y autoscale for the hovered axis (ECG or breathing)
        - '='  : autoscale y based on visible x window
        - '+'  : zoom y in
        - '-'  : zoom y out
        - up/down: pan y
        """
        if self.data is None or self.data.view is None:
            return

        ax = self._active_y_axis(event)
        if ax is None:
            return
        key = self._axis_key(ax)
        if key is None:
            return

        ystate = self.data.view.y[key]
        ax = event.inaxes

        if event.key == " ":
            ystate.auto = True
            ystate.ymin = None
            ystate.ymax = None
            self.redraw()
            return

        if event.key == "=":
            self._autoscale_visible_y(ax)
            self.canvas.draw_idle()
            return

        # Switch to manual mode if necessary
        if ystate.auto:
            y0, y1 = ax.get_ylim()
            ystate.auto = False
            ystate.ymin = float(y0)
            ystate.ymax = float(y1)

        assert ystate.ymin is not None and ystate.ymax is not None
        height = ystate.ymax - ystate.ymin
        center = 0.5 * (ystate.ymin + ystate.ymax)

        # -------------------------
        # ZOOM
        # -------------------------
        if event.key in ("+", "-"):
            if ax is self.ax_ecg:
                # ECG: no y-zoom
                return
            if ystate.auto:
                y0, y1 = ax.get_ylim()
                ystate.auto = False
                ystate.ymin = y0
                ystate.ymax = y1
            ymin = ystate.ymin
            ymax = ystate.ymax
            height = ymax - ymin
            if height <= 0:
                return
            scale = 0.8 if event.key == "+" else 1.25
            new_height = height * scale
            ystate.ymax = ymin + new_height
            self.redraw()
            return

        # Pan
        if event.key == "up":
            shift = -0.15 * height
        elif event.key == "down":
            shift = 0.15 * height
        else:
            return
        ystate.ymin += shift
        ystate.ymax += shift
        self.redraw()

    def _on_press(self, event) -> None:
        """
        Matplotlib mouse press callback.
        - If click on overview: start dragging window.
        - If in Add mode and on ECG axis: add a new R-top at click time.
        """
        if self.data is None or self.data.view is None:
            return

        # Overview drag
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

        # Add-mode: add a new R-top on ECG axis
        elif (
            self.edit_mode == "Add"
            and event.inaxes is not self.ax_overview
            and self.rtop_ctrl is not None
            and event.xdata is not None
        ):
            self.rtop_ctrl.add(float(event.xdata), label="N")
            self.redraw()

    def _on_motion(self, event) -> None:
        """
        Matplotlib mouse motion callback.
        - Tracks hovered axis (for key interactions)
        - Updates overview window rectangle during drag
        """
        if event.inaxes in (self.ax_ecg, self._ax_br_twin):
            self._hovered_ax = event.inaxes
        else:
            self._hovered_ax = None

        if event.inaxes is None or self.data is None or self.data.view is None:
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
            else:
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
        """Finish overview dragging and redraw full plot."""
        if (
            event.inaxes is self.ax_overview
            and self.data is not None
            and self.data.view is not None
        ):
            self.data.view.drag_mode = None
            self.redraw()

    # ------------------------------------------------------------------
    # LineHandler callbacks (R-top drag/remove)
    # ------------------------------------------------------------------

    def _on_line_drag(self, old_x: float, new_x: float) -> None:
        """Called when a R-top line is dragged to a new position."""
        if self.rtop_ctrl is None:
            return
        self.rtop_ctrl.move(old_x, new_x)
        self.redraw()

    def _on_line_remove(self, old_x: float, new_x: float) -> None:
        """Called when a R-top line is removed."""
        if self.rtop_ctrl is None:
            return
        self.rtop_ctrl.delete(new_x)
        self.redraw()

    # ------------------------------------------------------------------
    # Styling helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _style_axis_clean(ax: Axes) -> None:
        """Hide y-axis and unnecessary spines."""
        ax.get_yaxis().set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["top"].set_visible(False)

    @staticmethod
    def _set_time_axis(ax: Axes, x_min: float, x_max: float) -> None:
        """
        Configure the x-axis for a time-based plot with nice tick spacing.
        """
        ax.set_xlim(x_min, x_max)
        width = max(x_max - x_min, 1e-6)
        tdisp = round(math.log10(width), 0)
        major = math.pow(10, tdisp - 1)
        ax.set_xlabel("Time (seconds)")
        ax.xaxis.set_major_locator(MultipleLocator(major))
        ax.xaxis.set_minor_locator(MultipleLocator(major / 5.0))
