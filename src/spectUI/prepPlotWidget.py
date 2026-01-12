from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

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
from spectHR.DataSet.Series.CardioSeries import CardioSeries, CardioSeriesView
from spectUI.LineHandler import LineHandler

# ======================================================================
# View state & helpers
# ======================================================================
@dataclass
class AxisYState:
    auto: bool = True
    ymin: Optional[float] = None
    ymax: Optional[float] = None

@dataclass
class ViewState:
    """
    Holds the current x-range and drag state for the widget.
    """
    x_min: float
    x_max: float

    drag_mode: Optional[str] = None
    initial_xmin: Optional[float] = None
    initial_xmax: Optional[float] = None

    y: dict[str, AxisYState] = field(default_factory=lambda: {
        "ecg": AxisYState(),
        "br": AxisYState(),
    })

    def width(self) -> float:
        return self.x_max - self.x_min

    def center(self) -> float:
        return 0.5 * (self.x_min + self.x_max)



class RTopController:
    """
    Encapsulates all mutations & queries on a CardioSeries (R-top data).

    This class is purely about *data*: no plotting, no Qt.
    """

    def __init__(self, rtops: CardioSeries) -> None:
        self.rtops = rtops

    # ------------------------------------------------------------------
    # Basic helpers
    # ------------------------------------------------------------------
    @property
    def times(self) -> np.ndarray:
        return self.rtops.times

    @property
    def labels(self) -> np.ndarray:
        return self.rtops.labels

    @property
    def ibi(self) -> np.ndarray:
        return self.rtops.ibi

    def _sort_by_time(self) -> None:
        """
        Keep times & labels sorted ascending by time.
        """
        order = np.argsort(self.rtops.times)
        self.rtops.times = self.rtops.times[order]
        self.rtops.labels = self.rtops.labels[order]

    def _closest_idx(self, t: float) -> int:
        """
        Return index of R-top closest in time to t.
        """
        return int(np.argmin(np.abs(self.rtops.times - t)))

    # ------------------------------------------------------------------
    # Editing operations
    # ------------------------------------------------------------------
    def move(self, old_t: float, new_t: float) -> None:
        """
        Move the closest R-top around old_t to new_t (in seconds),
        and keep series sorted.
        """
        idx = self._closest_idx(old_t)
        self.rtops.times[idx] = float(new_t)
        self._sort_by_time()

    def add(self, t: float, label: str = "N") -> None:
        """
        Insert a new R-top at time t with label (default: "N").
        """
        t_arr = self.rtops.times
        lab_arr = self.rtops.labels

        self.rtops.times = np.concatenate([t_arr, np.array([t], dtype=float)])
        self.rtops.labels = np.concatenate([lab_arr, np.array([label], dtype=object)])
        self._sort_by_time()

    def delete(self, t: float) -> None:
        """
        Delete the R-top closest to t.
        """
        idx = self._closest_idx(t)
        mask = np.ones(self.rtops.times.shape[0], dtype=bool)
        mask[idx] = False
        self.rtops.times = self.rtops.times[mask]
        self.rtops.labels = self.rtops.labels[mask]

    # ------------------------------------------------------------------
    # Queries used for navigation
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    def window_view(self, x_min: float, x_max: float) -> CardioSeriesView:
        """
        Return a CardioSeriesView restricted to [x_min, x_max].
        """
        return self.rtops.view(x_min, x_max)


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
# PrepPlotWidget (UI + plotting)
# ======================================================================

class PrepPlotWidget(QWidget):
    """
    Interactive ECG pre-processing widget.

    Responsibilities
    ----------------
    - Displays:
        * ECG signal (main axis)
        * Optional breathing signal (if present)
        * Overview plot with draggable window
        * R-top markers and IBIs as arrows
    - Provides:
        * Navigation: zoom, pan, goto start/end, jump to next/prev abnormal R-top
        * Editing: Drag / Add / Remove R-tops via LineHandler

    It operates on a PhysioData instance with:
        - data["ecg"] -> StreamAccessor -> TimeSeries (times, values)
        - data.rtops  -> CardioSeries
        - optionally a "breathing..." TimeSeries.
    """

    # --------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # Matplotlib figure and canvas
        self.fig: Figure = Figure()
        self.canvas: FigureCanvas = FigureCanvas(self.fig)

        # Plot axes
        self.ax_ecg: Optional[Axes] = None
        self.ax_br: Optional[Axes] = None
        self.ax_overview: Optional[Axes] = None
        # for zooming
        self._hovered_ax: Optional[Axes] = None

        # State
        self.data: Optional[PhysioData] = None
        self.rtop_ctrl: Optional[RTopController] = None
        self.overview_window: Optional[OverviewWindow] = None
        self.line_handler: Optional[LineHandler] = None
        self.edit_mode: str = "Drag"

        # Mpl event ids
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

    # ==============================================================
    # Convenience properties
    # ==============================================================

    @property
    def ecg_series(self) -> TimeSeries:
        """Return the ECG TimeSeries from PhysioData."""
        assert self.data is not None
        return self.data["ecg"].timeseries

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
                    transform = QTransform().rotate(rotate if isinstance(rotate, int) else 0)
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

        begin = make_btn("fa6s.right-to-bracket", self.go_to_start, rotate=180, tooltip="Goto Start")
        left = make_btn("fa6s.backward", self.pan_left, tooltip="Pan Left")
        prev = make_btn("fa6s.square-caret-left", self.prev, tooltip="Previous non-normal R-top")
        zoom_in = make_btn("ei.zoom-in", self.zoom_in, tooltip="Zoom In")
        zoom_out = make_btn("ei.zoom-out", self.zoom_out, tooltip="Zoom Out")
        nxt = make_btn("fa6s.square-caret-right", self.next, tooltip="Next non-normal R-top")
        right = make_btn("fa6s.forward", self.pan_right, tooltip="Pan Right")
        end = make_btn("fa6s.right-to-bracket", self.go_to_end, rotate=False, tooltip="Goto End")

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
        data : PhysioData
            Dataset with at least an "ecg" timeseries and (optionally) .hrv.
        fig : Figure, optional
            An existing Matplotlib figure to reuse. If None, a new figure is created.
        x_min : float, optional
            Initial left bound of the visible time window. Defaults to start of ECG.
        x_max : float, optional
            Initial right bound of the visible time window. Defaults to end of ECG.

        Returns
        -------
        Figure
            The Matplotlib Figure used for plotting.
        """
        self.data = data
        if data.hrv is None:
            # No R-tops: still show ECG, but no editing/navigation by R-top.
            self.rtop_ctrl = None
        else:
            self.rtop_ctrl = RTopController(data.hrv)

        self.setVisible(True)
        plt.ioff()  # No blocking windows

        # Determine initial window
        if not hasattr(data, 'has_ecg') or data.has_ecg:
            ecg = self.ecg_series
            x_min_default = float(ecg.times.min())
            x_max_default = float(ecg.times.max())
        else:
            x_min_default = data["hrv"].times.min() if data["hrv"] else 0.0
            x_max_default = data["hrv"].times.max() if data["hrv"] else 100.0

        xmin = x_min if x_min is not None else x_min_default
        xmax = x_max if x_max is not None else x_max_default

        if not hasattr(data, "view"):
            self.data.view = ViewState(x_min=xmin, x_max=xmax)

        # Create or reuse figure/axes
        if fig is None:
            self._create_figure_and_axes()
        else:
            self.fig = fig
            self._reuse_axes_from_figure()

        self._setup_matplotlib_canvas()
        self._connect_mpl_events()

        # Initialize LineHandler for R-tops
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

    # ==============================================================
    # Figure / Axes setup
    # ==============================================================

    def _create_figure_and_axes(self) -> None:
        """
        Create new Matplotlib figure and axes based on whether breathing is present.
        """
        figsize = (15, 3)
        if self.has_breathing:
            self.fig, (ax_ecg, ax_br, ax_overview) = plt.subplots(
                3,
                1,
                figsize=figsize,
                sharex=False,
                gridspec_kw={"height_ratios": [9, 4, 1]},
            )
            self.ax_ecg, self.ax_br, self.ax_overview = ax_ecg, ax_br, ax_overview
        else:
            self.fig, (ax_ecg, ax_overview) = plt.subplots(
                2,
                1,
                figsize=figsize,
                sharex=False,
                gridspec_kw={"height_ratios": [4, 1]},
            )
            self.ax_ecg, self.ax_br, self.ax_overview = ax_ecg, None, ax_overview

    def _reuse_axes_from_figure(self) -> None:
        """
        Reuse existing figure's axes (if caller passed a figure).
        """
        axes = self.fig.axes
        if len(axes) == 3:
            self.ax_ecg, self.ax_br, self.ax_overview = axes
        elif len(axes) == 2:
            self.ax_ecg, self.ax_overview = axes
            self.ax_br = None
        else:
            raise RuntimeError("Unexpected number of axes in provided figure.")

    def _setup_matplotlib_canvas(self) -> None:
        """
        Attach the Matplotlib Figure to the Qt canvas and insert into layout.
        """
        # Hide toolbar/header for embedded use
        self.fig.canvas.toolbar_visible = False  # type: ignore[attr-defined]
        self.fig.canvas.header_visible = False   # type: ignore[attr-defined]
        self.fig.tight_layout()

        # Rebuild Qt canvas
        self.canvas.setParent(None)
        self.canvas = FigureCanvas(self.fig)
        # 🔑 REQUIRED FOR KEY EVENTS
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.setFocus()

        self.layout().insertWidget(1, self.canvas)
        # Insert new canvas at index 1: after mode_selector
        self.layout().insertWidget(1, self.canvas)  # type: ignore[arg-type]

    # ==============================================================
    # Matplotlib event wiring
    # ==============================================================

    def _connect_mpl_events(self) -> None:
        """
        Connect mouse events for overview dragging and add-mode clicks.
        """
        if self._mpl_cid_press is not None:
            self.fig.canvas.mpl_disconnect(self._mpl_cid_press)
        if self._mpl_cid_move is not None:
            self.fig.canvas.mpl_disconnect(self._mpl_cid_move)
        if self._mpl_cid_release is not None:
            self.fig.canvas.mpl_disconnect(self._mpl_cid_release)

        self._mpl_cid_press = self.fig.canvas.mpl_connect("button_press_event", self._on_press)
        self._mpl_cid_move = self.fig.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._mpl_cid_release = self.fig.canvas.mpl_connect("button_release_event", self._on_release)
        # for zooming: 
        self._mpl_cid_key_press = self.fig.canvas.mpl_connect("key_press_event", self._on_key_press)
    
    # ==============================================================
    # Rendering pipeline
    # ==============================================================

    def redraw(self) -> None:
        """
        Redraw all plots (ECG, breathing, overview, R-tops).
        """
        assert self.data.view is not None
        assert self.ax_ecg is not None
        assert self.ax_overview is not None
        assert self.data is not None

        # ECG main plot
        self._draw_ecg()

        # R-tops & IBIs
        if self.rtop_ctrl is not None:
            self._draw_rtops_and_ibis()

        # Breathing
        if self.ax_br is not None:
            self._draw_breathing()

        # Overview plot
        self._draw_overview()

        self.canvas.draw_idle()

    def _draw_ecg(self) -> None:
        """
        Draw ECG signal in the main axis.
        """
        assert self.ax_ecg is not None and self.data.view is not None
        ecg = self.ecg_series

        self.ax_ecg.clear()
        self.ax_ecg.plot(ecg.times, ecg.values, color="red", linewidth=0.8, alpha=1.0)

        self._style_axis_no_y(self.ax_ecg)
        self._set_time_axis(self.ax_ecg, self.data.view.x_min, self.data.view.x_max)

        ystate = self.data.view.y["ecg"]
        if not ystate.auto and ystate.ymin is not None:
            self.ax_ecg.set_ylim(ystate.ymin, ystate.ymax)

        if self.ax_br is not None:
            # Hide x-axis on ECG when breathing plot is below
            self.ax_ecg.get_xaxis().set_visible(False)
            self.ax_ecg.spines["bottom"].set_visible(False)
            self.ax_ecg.set_xlabel("")

    def _draw_rtops_and_ibis(self) -> None:
        """
        Draw R-top markers and IBI arrows in the ECG axis.
        Only shows R-tops within [x_min-1, x_max+1] and limits to <= 100 markers.
        """
        assert self.rtop_ctrl is not None
        assert self.ax_ecg is not None
        assert self.data.view is not None

        rt_view = self.rtop_ctrl.window_view(self.data.view.x_min - 1, self.data.view.x_max + 1)

        times = rt_view.times
        labels = rt_view.labels
        ibi = rt_view.ibi  # last is NaN

        self.line_handler.clear()  # type: ignore[union-attr]
        y0, y1 = self.ax_ecg.get_ylim()
        h = y1 + 0.05 * (y1 - y0)

        # If too many, do not plot verticals/arrows
        if times.size > 100:
            return

        for i in range(times.size):
            t = float(times[i])
            lab = str(labels[i])
            color = self.RTopColors.get(lab, "blue")
            self.line_handler.add_line(t, color=color)  # type: ignore[union-attr]

            # IBI arrow to next R-peak, skip last (NaN) or invalid
            ibi_val = float(ibi[i]) if i < ibi.size else float("nan")
            if not np.isnan(ibi_val) and ibi_val != 0.0:
                arrow = FancyArrowPatch(
                    (t, h),
                    (t + ibi_val, h),
                    arrowstyle="<->",
                    color="blue",
                    mutation_scale=5,
                    linewidth=0.5,
                )
                self.ax_ecg.add_patch(arrow)
                self.ax_ecg.text(
                    t + 0.5 * ibi_val,
                    h,
                    f"{1000.0 * ibi_val:.0f}",
                    fontsize=6,
                    horizontalalignment="center",
                    verticalalignment="bottom",
                    color="blue",
                    bbox=dict(
                        facecolor=self.ax_ecg.get_facecolor(),
                        edgecolor=self.ax_ecg.get_facecolor(),
                        alpha=0.4,
                    ),
                )

        # Slightly expand top of ECG axis to make room for labels
        y0, y1 = self.ax_ecg.get_ylim()
        self.ax_ecg.set_ylim(y0, y1 * 1.2)

    def _draw_breathing(self) -> None:
        """
        Draw breathing signal if present.
        """
        assert self.ax_br is not None
        assert self.data.view is not None

        ts = self.breathing_series
        if ts is None:
            self.ax_br.clear()
            return

        self.ax_br.clear()
        self.ax_br.plot(ts.times, ts.values, color="green", linewidth=0.8, alpha=1.0)
        self._style_axis_no_y(self.ax_br)
        self._set_time_axis(self.ax_br, self.data.view.x_min, self.data.view.x_max)

        ystate = self.data.view.y["br"]
        if not ystate.auto and ystate.ymin is not None:
            self.ax_br.set_ylim(ystate.ymin, ystate.ymax)


    def _draw_overview(self) -> None:
        """
        Draw the overview ECG plot and its draggable window rectangle.
        The x-axis of the overview never changes.
        The rectangle is ALWAYS recreated to avoid disappearing after redraws.
        """
        assert self.ax_overview is not None
        assert self.data.view is not None

        ecg = self.ecg_series
        
        # Redraw the overview axis completely.
        self.ax_overview.clear()
        self.ax_overview.plot(
            ecg.times, ecg.values,
            linewidth=0.25, alpha=0.5, color="green"
        )
        self.ax_overview.set_title("")
        self.ax_overview.set_yticks([])
        self._style_axis_no_y(self.ax_overview)

        # Recreate the rectangle every time — most robust behaviour.
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
        Clamp the window [x_min, x_max] to the ECG data range.
        """
        ecg = self.ecg_series
        global_min = float(ecg.times.min())
        global_max = float(ecg.times.max())
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
        new_min, new_max = self._constrained_window(self.data.view.x_min - width, self.data.view.x_max - width)
        self._set_window(new_min, new_max)

    def pan_right(self) -> None:
        """
        Pan window right by one window width.
        """
        assert self.data.view is not None
        width = self.data.view.width()
        new_min, new_max = self._constrained_window(self.data.view.x_min + width, self.data.view.x_max + width)
        self._set_window(new_min, new_max)

    def go_to_start(self) -> None:
        """
        Move window to the very beginning of the ECG.
        """
        assert self.data.view is not None
        ecg = self.ecg_series
        width = self.data.view.width()
        start = float(ecg.times.min())
        self._set_window(start, start + width)

    def go_to_end(self) -> None:
        """
        Move window to the very end of the ECG.
        """
        assert self.data.view is not None
        ecg = self.ecg_series
        width = self.data.view.width()
        end = float(ecg.times.max())
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
    def _is_data_axis(self, ax) -> bool:
        return ax in (self.ax_ecg, self.ax_br)

    def _axis_key(self, ax: Axes) -> Optional[str]:
        if ax is self.ax_ecg:
            return "ecg"
        if ax is self.ax_br:
            return "br"
        return None
    def _autoscale_visible_y(self, ax: Axes) -> None:
        """
        Autoscale y-axis using only data visible in the current x-window.
        """
        assert self.data is not None
        assert self.data.view is not None

        x0, x1 = self.data.view.x_min, self.data.view.x_max

        if ax is self.ax_ecg:
            ts = self.ecg_series
        elif ax is self.ax_br:
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

        # Avoid zero-height ranges
        if ymin == ymax:
            eps = 1e-6 if ymin == 0 else abs(ymin) * 1e-3
            ymin -= eps
            ymax += eps

        ax.autoscale(enable=False, axis="y")
        ax.set_ylim(ymin, ymax)

    def _on_key_press(self, event) -> None:
        if event.inaxes is None or self.data is None:
            return

        key = self._axis_key(event.inaxes)
        if key is None:
            return

        ystate = self.data.view.y[key]
        ax = event.inaxes

        # -------------------------
        # RESET
        # -------------------------
        if event.key == " ":
            ystate.auto = True
            ystate.ymin = None
            ystate.ymax = None
            self.redraw()
            return
        elif event.key == "=":
            self._autoscale_visible_y(ax)
            self.canvas.draw_idle()
            return

        # Ensure manual mode
        if ystate.auto:
            y0, y1 = ax.get_ylim()
            ystate.auto = False
            ystate.ymin = y0
            ystate.ymax = y1

        height = ystate.ymax - ystate.ymin
        center = 0.5 * (ystate.ymin + ystate.ymax)

        # -------------------------
        # ZOOM
        # -------------------------
        if event.key == "+":
            scale = 0.8
        elif event.key == "-":
            scale = 1.25
        else:
            scale = None

        if scale is not None:
            half = 0.5 * height * scale
            ystate.ymin = center - half
            ystate.ymax = center + half
            self.redraw()
            return

        # -------------------------
        # PAN
        # -------------------------
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

        # Add-mode: add a new R-top on ECG axis
        elif (
            self.edit_mode == "Add"
            and event.inaxes is self.ax_ecg
            and self.rtop_ctrl is not None
            and event.xdata is not None
        ):
            self.rtop_ctrl.add(float(event.xdata), label="N")
            self.redraw()

    def _on_motion(self, event) -> None:
        """
        Matplotlib mouse motion callback (while dragging window).
        """
        # save the hovered axis for zooming
        if event.inaxes in (self.ax_ecg, self.ax_br):
            self._hovered_ax = event.inaxes
        else:
            self._hovered_ax = None
        # Overview drag
        if event.inaxes is None or self.data.view is None:
            return

        if event.inaxes is self.ax_overview and self.data.view.drag_mode is not None:
            if event.xdata is None or self.data.view.initial_xmin is None or self.data.view.initial_xmax is None:
                return

            width = self.data.view.initial_xmax - self.data.view.initial_xmin
            if self.data.view.drag_mode == "left":
                x_min = min(event.xdata, self.data.view.x_max - 0.1)
                x_max = self.data.view.x_max
            elif self.data.view.drag_mode == "right":
                x_min = self.data.view.x_min
                x_max = max(event.xdata, self.data.view.x_min + 0.1)
            else:  # center
                dx = event.xdata - 0.5 * (self.data.view.initial_xmin + self.data.view.initial_xmax)
                x_min = self.data.view.initial_xmin + dx
                x_max = self.data.view.initial_xmax + dx

            x_min, x_max = self._constrained_window(x_min, x_max)
            self.data.view.x_min = x_min
            self.data.view.x_max = x_max

            if self.overview_window is not None:
                self.overview_window.set_window(x_min, x_max)
            self.canvas.draw_idle()

    def _on_release(self, event) -> None:
        """
        Matplotlib mouse release callback: finish dragging.
        """
        if event.inaxes is self.ax_overview and self.data.view is not None:
            self.data.view.drag_mode = None
            self.redraw()

    # ==============================================================
    # LineHandler callbacks (R-top drag/remove)
    # ==============================================================

    def _on_line_drag(self, old_x: float, new_x: float) -> None:
        """
        Called by LineHandler when a R-top line is dragged.
        """
        if self.rtop_ctrl is None:
            return
        self.rtop_ctrl.move(old_x, new_x)
        self.redraw()

    def _on_line_remove(self, old_x: float, new_x: float) -> None:
        """
        Called by LineHandler when a R-top line is removed.
        """
        if self.rtop_ctrl is None:
            return
        # We only care about the position of the removed line; use new_x
        self.rtop_ctrl.delete(new_x)
        self.redraw()

    # ==============================================================
    # Styling helpers
    # ==============================================================

    @staticmethod
    def _style_axis_no_y(ax: Axes) -> None:
        """
        Hide y-axis and unnecessary spines.
        """
        ax.get_yaxis().set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["top"].set_visible(False)

    @staticmethod
    def _set_time_axis(ax: Axes, x_min: float, x_max: float) -> None:
        """
        Configure the x-axis of a time-based plot with nice tick spacing.
        """
        ax.set_xlim(x_min, x_max)
        # Avoid log10 of 0 or negative ranges
        width = max(x_max - x_min, 1e-6)
        tdisp = round(math.log10(width), 0)
        major = math.pow(10, tdisp - 1)
        ax.set_xlabel("Time (seconds)")
        ax.xaxis.set_major_locator(MultipleLocator(major))
        ax.xaxis.set_minor_locator(MultipleLocator(major / 5.0))
