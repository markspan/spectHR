# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Interactive ECG pre-processing and annotation widget.

Embeds a Matplotlib figure with: ECG signal inspection, manual R-peak
editing via LineHandler, optional breathing overlay on a twinned
y-axis, epoch ranges drawn as horizontal interval arrows above the
ECG axis, and a draggable window rectangle on a small overview axis.

The widget is a view layer, it does not own the underlying data.
All time coordinates are in dataset time (seconds). Overlapping
epochs are stacked into lanes. The PhysioData contract this widget
expects is documented as a comment near :meth:`PrepPlotWidget.prepPlot`.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.RTopController import RTopController
from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectUI.common import (
    AxisYState,
    EpochName,
    LineHandler,
    OverviewWindow,
    TimelinePlotWidget,
    TimeSeconds,
    ViewState,
    draw_interval_arrows,
    decimate_minmax,
    make_nav_button,
    style_axis_clean,
    swap_canvas,
)
from spectUI.plot_worker import DockScheduler

# ``AxisYState``, ``ViewState``, ``draw_interval_arrows`` and the
# ``TimeSeconds`` / ``EpochName`` aliases now live in
# ``spectUI.common.timeline`` so every timeline widget shares one
# window-state model. They are imported above and re-used unchanged here.

# ``RTopController`` is the headless R-peak editing API; it now lives in
# ``spectHR.DataSet.RTopController`` and is imported above.

# ======================================================================
# OverviewWindow (shared, see spectUI._uitools)
# ======================================================================

# ======================================================================
# PrepPlotWidget (UI + plotting)
# ======================================================================


class PrepPlotWidget(TimelinePlotWidget):
    """
    Interactive ECG pre-processing widget.

    Subclasses :class:`~spectUI.common.TimelinePlotWidget` to inherit the
    shared zoom / pan / goto navigation and the ``viewChanged`` view-sync
    signal, but builds its own richer figure (ECG axis + breathing twin +
    overview) and rendering, so it sets its widgets up directly rather than
    through the base ``__init__`` template used by the simpler HR / BP docks.

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

    # Emitted whenever the user actually mutates the R-peaks (add / move /
    # remove). MainWindow connects this to mark the dataset dirty, so plot
    # caches are invalidated only on a real edit - merely viewing this dock
    # leaves them intact. (``viewChanged`` is inherited from the base.)
    dataEdited = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Initialize the widget UI and set up state containers.
        """
        # PrepPlotWidget assembles its own 3-axis figure and an edit-mode
        # toolbar, so it skips TimelinePlotWidget.__init__ (which lays out
        # the single-signal HR / BP form) and initialises the QWidget
        # directly. The shared navigation methods it inherits only need
        # ``data`` / ``data.view`` / ``_primary_series`` / ``redraw``, all
        # provided below.
        QWidget.__init__(self, parent)

        # Matplotlib figure and canvas
        self.fig: Figure = Figure()
        self.canvas: FigureCanvas = FigureCanvas(self.fig)

        # Plot axes
        self.ax_ecg: Axes | None = None
        self.ax_overview: Axes | None = None
        self.ax_br: Axes | None = None
        self._ax_br_twin: Axes | None = None  # breathing overlay axis (twinx)

        # Hovered axis for key interactions
        self._hovered_ax: Axes | None = None

        # State
        self.data: PhysioData | None = None
        self.rtop_ctrl: RTopController | None = None
        self.overview_window: OverviewWindow | None = None
        self.line_handler: LineHandler | None = None
        self.edit_mode: str = "Drag"

        # Cached overview background for blitting the window rectangle during a
        # drag (blit helpers are inherited from TimelinePlotWidget).
        self._overview_bg = None

        # Matplotlib event ids
        self._mpl_cid_press: int | None = None
        self._mpl_cid_move: int | None = None
        self._mpl_cid_release: int | None = None
        self._mpl_cid_key_press: int | None = None

        # Debounce timer for toolbar nav (shared with TimelinePlotWidget._set_window).
        # PrepPlotWidget skips TimelinePlotWidget.__init__, so we create it here.
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(160)
        self._redraw_timer.timeout.connect(self._deferred_redraw)

        # IBI re-classification after R-top edits runs on a background thread
        # (it is O(n) over every beat). The structural change is shown
        # immediately with stale labels; when the worker finishes, the final
        # label-corrected redraw + dataEdited notification happen on the main
        # thread. Rapid edits bump the generation counter so only the latest
        # classification is applied (see plot_worker.DockScheduler).
        self._classify_scheduler = DockScheduler()

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

    def _primary_series(self) -> TimeSeries | None:
        """The ECG series drives the navigation window (TimelinePlotWidget hook).

        Returns ``None`` when no dataset / ECG channel is loaded so the
        inherited ``_can_navigate`` / ``_constrained_window`` guards stay
        safe.
        """
        if self.data is None:
            return None
        try:
            return self.data["ecg"].timeseries
        except (KeyError, AttributeError):
            return None

    @property
    def breathing_series(self) -> TimeSeries | None:
        """
        Return the breathing TimeSeries for the active band, else None.

        Resolution order:

        1. The band_map ``"rsp"`` role for the active band. This is the
           canonical hook and works for every source - XDF/Polar streams
           named ``RSP-[device]`` as well as NFF channels keyed ``resp``.
        2. Legacy fallback: the first timeseries whose name starts with
           ``"RSP"`` (datasets without a band_map ``"rsp"`` entry).

        Returns
        -------
        TimeSeries | None
        """
        assert self.data is not None
        # 1. Canonical band-aware resolution (XDF "RSP-[...]" and NFF "resp").
        try:
            return self.data["rsp"].timeseries
        except KeyError:
            pass
        # 2. Legacy name-prefix scan.
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
        """Create the navigation bar with zoom/pan/next/prev controls."""
        buttons = (
            make_nav_button("fa6s.right-to-bracket", self.go_to_start, rotate=180, tooltip="Goto Start"),
            make_nav_button("fa6s.backward",          self.pan_left,               tooltip="Pan Left"),
            make_nav_button("fa6s.square-caret-left", self.prev,                   tooltip="Previous non-normal R-top"),
            make_nav_button("ei.zoom-in",             self.zoom_in,                tooltip="Zoom In"),
            make_nav_button("ei.zoom-out",            self.zoom_out,               tooltip="Zoom Out"),
            make_nav_button("fa6s.square-caret-right",self.next,                   tooltip="Next non-normal R-top"),
            make_nav_button("fa6s.forward",           self.pan_right,              tooltip="Pan Right"),
            make_nav_button("fa6s.right-to-bracket",  self.go_to_end,              tooltip="Goto End"),
        )
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        for btn in buttons:
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

    # ------------------------------------------------------------------
    # PhysioData contract this widget expects
    #
    #   data["ecg"].timeseries : TimeSeries
    #       .times   1D float seconds; .values 1D float signal units.
    #   data.timeseries : dict[str, TimeSeries]
    #       Optional breathing series, identified by name.startswith("RSP"),
    #       the first match wins.
    #   data.hrv : CardioSeries | None
    #       R-peak times and labels, drives the edit / visualization layer.
    #   data.epochs : dict[str, Epoch-like]
    #       Each entry exposes active: bool, start: float, end: float
    #       (seconds). Optional is_valid: bool, when False the epoch is
    #       skipped.
    #   data.view : ViewState
    #       Created here on first call when missing.
    # ------------------------------------------------------------------

    def prepPlot(
        self,
        data: PhysioData,
        fig: Figure | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
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
        self.fig = Figure(figsize=(15, 3))
        self.fig.set_facecolor("white")
        gs = self.fig.add_gridspec(2, 1, height_ratios=[5, 1])
        self.ax_ecg      = self.fig.add_subplot(gs[0])
        self.ax_overview = self.fig.add_subplot(gs[1])
        self._compact_layout()

    def _reuse_axes_from_figure(self) -> None:
        """
        Reuse existing figure's axes (if caller passed a figure).
        Expected:
        - 2 axes: ECG and overview
        """
        axes = self.fig.axes
        if len(axes) >= 2:
            self.ax_ecg, self.ax_overview = axes[0], axes[-1]
        else:
            raise RuntimeError(
                "Unexpected number of axes in provided figure; expected at least 2 (ECG + overview)."
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

        # Replace the previous canvas at index 1 (after the mode
        # selector). The orphan-window rationale lives in swap_canvas.
        self.canvas = swap_canvas(
            self.layout(),   # type: ignore[arg-type]
            self.canvas,
            self.fig,
            index=1,
        )
        # Required for key events
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.setFocus()

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

        # Clear and plot only the visible ECG segment.
        # This ensures y-axis autoscaling is based on the currently shown
        # window, not the full recording.
        x0, x1 = self.data.view.x_min, self.data.view.x_max
        mask = (ecg.times >= x0) & (ecg.times <= x1)
        if np.any(mask):
            plot_times = ecg.times[mask]
            plot_values = ecg.values[mask]
        else:
            plot_times = ecg.times
            plot_values = ecg.values

        # A screen can't show more samples than it has pixels: min/max
        # decimate the visible segment so a wide window doesn't push
        # millions of points through matplotlib. The envelope (incl.
        # R-peaks) and the per-window min/max — and thus the y-autoscale
        # below — are preserved. No-op once zoomed in past ~screen width.
        plot_times, plot_values = decimate_minmax(plot_times, plot_values)

        self.ax_ecg.clear()
        self.ax_ecg.plot(
            plot_times,
            plot_values,
            color="red",
            linewidth=0.8,
            alpha=1.0,
            zorder=2,
        )

        # Styling (no y-axis, no top/side spines)
        style_axis_clean(self.ax_ecg)

        # Time window
        self._set_time_axis(
            self.ax_ecg, self.data.view.x_min, self.data.view.x_max,
            show_xlabel=True,
        )

        # ------------------------------------------------------------
        # Y-scaling
        # ------------------------------------------------------------
        if self.ax_br is None:
            # No breathing, normal autoscale
            self.ax_ecg.relim()
            self.ax_ecg.autoscale_view(scalex=False, scaley=True)
            return

        # ------------------------------------------------------------
        # Breathing present, lift ECG upward
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
        x0, x1 = self.data.view.x_min, self.data.view.x_max
        mask = (ts.times >= x0) & (ts.times <= x1)
        if np.any(mask):
            plot_times = ts.times[mask]
            plot_values = ts.values[mask]
        else:
            plot_times = ts.times
            plot_values = ts.values

        # Decimate the visible segment to ~screen resolution (see _draw_ecg).
        plot_times, plot_values = decimate_minmax(plot_times, plot_values)

        ax_br.plot(
            plot_times,
            plot_values,
            color="green",
            linewidth=1,
            alpha=1.0,
            zorder=1,
        )
        ax_br.set_xlim(x0, x1)

        # Apply manual y-limits if set
        ystate = self.data.view.y["br"]
        if not ystate.auto and ystate.ymin is not None and ystate.ymax is not None:
            ax_br.set_ylim(ystate.ymin, ystate.ymax)

        # Visual style: keep breathing subtle and clearly distinguishable
        ax_br.tick_params(axis="y", colors="green", labelsize=8)
        ax_br.spines["right"].set_alpha(0.3)
        style_axis_clean(ax_br)
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

        visible: list[tuple[EpochName, TimeSeconds, TimeSeconds]] = []
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
        # The overview is only ~screen-width pixels; decimate so a long
        # recording is not re-rendered at full resolution on every redraw.
        ov_t, ov_v = decimate_minmax(ecg.times, ecg.values)
        self.ax_overview.clear()
        self.ax_overview.plot(
            ov_t,
            ov_v,
            linewidth=0.25,
            alpha=0.5,
            color="blue",
        )
        self.ax_overview.set_title("")
        self.ax_overview.set_yticks([])
        style_axis_clean(self.ax_overview)

        self.overview_window = OverviewWindow(
            self.ax_overview,
            self.data.view.x_min,
            self.data.view.x_max,
        )

    # ------------------------------------------------------------------
    # Navigation actions (toolbar)
    #
    # zoom_in / zoom_out / pan_left / pan_right / go_to_start / go_to_end,
    # plus _set_window and _constrained_window, are inherited unchanged from
    # TimelinePlotWidget (they drive the shared ``data.view`` through the
    # ``_primary_series`` hook above). Only the R-top jump buttons below are
    # specific to the preprocessing dock.
    # ------------------------------------------------------------------

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

    def _axis_key(self, ax: Axes) -> str | None:
        """Map an Axes to a ViewState ``y`` key, or None for untracked axes.

        Returns ``"br"`` for the breathing twin-axis (y-zoom is supported).
        Returns ``None`` for the ECG axis and any other axis — ECG y-zoom
        is intentionally blocked so R-top markers stay anchored to the trace.
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

    def _active_y_axis(self, event) -> Axes | None:
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
            # ystate is already in manual mode (set above)
            height = ystate.ymax - ystate.ymin
            if height <= 0:
                return
            scale = 0.8 if event.key == "+" else 1.25
            ystate.ymax = ystate.ymin + height * scale
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

            self._begin_overview_blit()

        # Add-mode: add a new R-top on ECG axis
        elif (
            self.edit_mode == "Add"
            and event.inaxes is not self.ax_overview
            and self.rtop_ctrl is not None
            and event.xdata is not None
        ):
            self.rtop_ctrl.add_no_classify(float(event.xdata), label="N")
            self.redraw()                 # instant structural feedback (stale labels)
            self._classify_async()        # final label-corrected redraw off-thread

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
            self._update_overview_blit()

    def _on_release(self, event) -> None:
        """Finish overview dragging and redraw full plot.

        Finishes the drag wherever the mouse is released (it may leave the
        overview axis mid-drag), so the blit state is always torn down.
        """
        if self.data is None or self.data.view is None:
            return
        if self.data.view.drag_mode is None:
            return
        self.data.view.drag_mode = None
        self._end_overview_blit()
        self.redraw()
        self.viewChanged.emit()

    # ------------------------------------------------------------------
    # LineHandler callbacks (R-top drag/remove)
    # ------------------------------------------------------------------

    def _on_line_drag(self, old_x: float, new_x: float) -> None:
        """Called when a R-top line is dragged to a new position."""
        if self.rtop_ctrl is None:
            return
        self.rtop_ctrl.move_no_classify(old_x, new_x)
        self.redraw()                 # instant structural feedback (stale labels)
        self._classify_async()        # final label-corrected redraw off-thread

    def _on_line_remove(self, old_x: float, new_x: float) -> None:
        """Called when a R-top line is removed."""
        if self.rtop_ctrl is None:
            return
        self.rtop_ctrl.delete_no_classify(new_x)
        self.redraw()                 # instant structural feedback (stale labels)
        self._classify_async()        # final label-corrected redraw off-thread

    def _classify_async(self) -> None:
        """Reclassify IBIs on a background thread, then redraw + notify.

        The structural edit has already been applied and drawn with stale
        labels. Here we snapshot the IBI/label arrays on the main thread,
        run the O(n) classification on the pool, and apply the result back
        on the main thread once it completes. The scheduler's generation
        counter means a fresh edit cancels an in-flight classification, so
        only the labels for the latest edit are ever applied.
        """
        if self.rtop_ctrl is None:
            return
        rtops = self.rtop_ctrl.rtops
        ibi_snapshot    = np.asarray(rtops.ibi,    dtype=float).copy()
        labels_snapshot = np.asarray(rtops.labels, dtype=object).copy()

        def compute():
            from spectHR.Tools.IbiClassification import classify_ibi
            classify_ibi(ibi_snapshot, labels_snapshot)  # mutates the copy
            return labels_snapshot

        def on_done(new_labels):
            if self.rtop_ctrl is None:
                return
            rtops = self.rtop_ctrl.rtops
            # Belt-and-suspenders: the generation guard already discards
            # results superseded by a later edit, so the length matches.
            if new_labels.shape[0] != rtops.labels.shape[0]:
                return
            try:
                rtops.labels = new_labels
                self.redraw()
            except RuntimeError:
                return
            self.dataEdited.emit()

        self._classify_scheduler.submit("prep_classify", compute, on_done)
