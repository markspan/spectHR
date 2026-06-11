# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`PrepPlotWidget` — the docked ECG pre-processing and R-peak editor.

The development-branch port of the V2 ``prepPlotWidget``.  It keeps the V2
look and feel — a tall ECG panel with a breathing overlay, epoch arrows and
draggable R-peak markers, over a thin full-recording overview strip with a
draggable zoom rectangle — but rests on the immutable
:class:`~spectHR.session.Session` model.

Design
------
*One model.*  Everything about a load — session, window, navigator, editing
controller, resolved channels, settings — lives in a single
:class:`~spectUI.widgets.prep.model.PrepModel`.  The widget holds one
``PrepModel | None`` and asks one question, *is a session loaded?*

*One gesture dispatcher.*  A single ``press / motion / release`` triad owns
every mouse interaction — overview drag, add, remove, and marker drag — and
routes by what was hit.  The R-peak markers are plain artists the widget
hit-tests itself; there is no second, competing event handler.

*Static vs dynamic layers.*  The overview trace (the decimated full
recording) is drawn once per load; :meth:`redraw` only repaints the ECG panel
and slides the overview's zoom rectangle, so panning never re-decimates the
whole signal.

Edits go through ``model.rtop_ctrl`` and commit back into
``session.events["hrv"]`` — call-by-reference — and :attr:`dataEdited` is
emitted (payload-free, as V2) so the host can mark the file dirty.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import MultipleLocator
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget

from spectHR.config import CardioParams, WorkspaceView
from spectHR.session import Session
from spectHR.Tools.Decimation import decimate_minmax
from spectHR.Tools.IbiClassification import classify_ibi
from spectUI.common import (
    OverviewWindow,
    make_nav_button,
    style_axis_clean,
    swap_canvas,
)
from spectUI.plot_worker import DockScheduler
from spectUI.widgets.prep.model import PrepModel
from spectUI.widgets.prep.state import YAxisState

# ─────────────────────────────────────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────────────────────────────────────

_C_ECG = "#c0392b"        # deep red — clinical ECG convention
_C_RESP = "#27ae60"       # green — respiration
_C_INH = "#d6eaf8"        # pale blue — inhalation shading
_C_IBI = "#2c3e50"        # near-black — IBI arrows/labels
_C_OVERVIEW = "#2980b9"   # blue — overview trace and zoom rectangle
_C_EPOCH = "#16a085"      # teal — epoch arrows

# Normal beats stay quiet; abnormal beats escalate in salience.
_RTOP_COLORS: dict[str, str] = {
    "N": "#7f8c8d",     # grey — normal
    "L": "#2980b9",     # blue — long
    "S": "#8e44ad",     # purple — short
    "TL": "#e67e22",    # orange — too long
    "SL": "#16a085",    # teal — short-then-long
    "SNS": "#27ae60",   # green — short-normal-short
    "T": "#bdc3c7",     # light grey — degenerate
}

# Max R-peaks to draw before the marker layer is skipped (keeps drags smooth).
_MAX_VISIBLE_RTOPS = 100
# Fixed axis-fraction height for the IBI annotation band, clear of the trace.
_Y_IBI = 0.985
# How near (screen pixels) a click must be to grab / remove a marker.
_PICK_TOLERANCE_PX = 8.0
# Fraction of the overview rectangle width that counts as grabbing an edge.
_EDGE_GRAB_FRAC = 0.3
# Debounce interval (ms) coalescing rapid window changes into one repaint.
_REDRAW_DEBOUNCE_MS = 160
# y-axis margins applied after autoscaling the ECG (fractions of the range).
_Y_MARGIN_TOP = 0.18
_Y_MARGIN_BOTTOM = 0.08
_Y_MARGIN_BOTTOM_RESP = 0.35   # extra room below when breathing shares the panel

_NO_TIMES: np.ndarray = np.empty(0, dtype=float)


@dataclass
class _LineDrag:
    """An in-progress R-peak marker drag: where it started, which artist moves."""

    orig_time: float
    line: Line2D


class PrepPlotWidget(QWidget):
    """Interactive ECG pre-processing and R-peak annotation dock.

    Signals
    -------
    dataEdited
        Emitted (no payload) after every committed R-peak edit.  Listeners
        read ``session.events["hrv"]`` directly.
    viewChanged
        Emitted after the visible window changes, so sibling docks can keep
        their own x-axis in sync.
    epoch_request(str)
        Emitted when the widget wants the globally active epoch changed.
        Reserved for the MainWindow broadcast pattern; not fired yet.
    """

    dataEdited = Signal()
    viewChanged = Signal()
    epoch_request = Signal(str)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # The single source of truth for "what is loaded" (None ⇒ nothing).
        self._model: PrepModel | None = None

        # Gesture + marker state, owned by the unified dispatcher.
        self._line_drag: _LineDrag | None = None
        self._marker_lines: list[Line2D] = []
        self._marker_times: np.ndarray = _NO_TIMES

        # Matplotlib figure/axes (rebuilt on each load).
        self.fig: Figure = Figure()
        self.canvas: FigureCanvas = FigureCanvas(self.fig)
        self.ax_ecg: Axes | None = None
        self.ax_overview: Axes | None = None
        self._ax_br_twin: Axes | None = None

        self.overview_window: OverviewWindow | None = None
        self._overview_bg = None  # blit pixel-buffer cache

        self._cid_press: int | None = None
        self._cid_move: int | None = None
        self._cid_release: int | None = None
        self._cid_key: int | None = None

        # Coalesce rapid window changes (button mashing, overview drag).
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(_REDRAW_DEBOUNCE_MS)
        self._redraw_timer.timeout.connect(self._deferred_redraw)

        self._classify_scheduler = DockScheduler()

        # Edit-mode selector.
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["Drag", "Add", "Remove"])
        self.mode_selector.setFixedWidth(120)
        self.mode_selector.currentTextChanged.connect(self.set_edit_mode)

        self.navigation_bar = self._build_navigation_bar()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.mode_selector)
        layout.addWidget(self.canvas)
        layout.addWidget(self.navigation_bar)
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_session(self, session: Session, config=None) -> None:
        """Load *session* and render the pre-processing view.

        Builds the :class:`PrepModel`, rebuilds the figure, draws the
        (static) overview once, and triggers the first ECG repaint.  R-peak
        editing is disabled (markers simply not drawn) when the session
        carries no ``"hrv"`` channel.
        """
        self._model = PrepModel.build(session, self._cardio_params(config))
        self._line_drag = None

        self._build_figure()
        self._mount_canvas()
        self._connect_events()
        self._draw_overview_static()

        self.setVisible(True)
        self.redraw()

    def set_epoch(self, name: str) -> None:
        """Scroll the window to the time range of epoch *name* (no-op if unknown)."""
        m = self._model
        if m is None:
            return
        ep = m.session.epochs.get(name)
        if ep is None:
            return
        m.window.x_min, m.window.x_max = m.navigator.constrain(
            float(ep.start), float(ep.end)
        )
        self._schedule_redraw()

    def prepPlot(
        self,
        data: Session,
        x_min: float | None = None,
        x_max: float | None = None,
    ) -> Figure:
        """V2-compatible entry point: load *data*, return the figure.

        Callers porting from V2's ``prepPlot(data, fig, x_min, x_max)`` need
        only drop the ``fig`` argument.  The optional ``x_min`` / ``x_max``
        seed the initial zoom window; omitted bounds default to the signal
        extent.
        """
        self.set_session(data)
        m = self._model
        if (x_min is not None or x_max is not None) and m is not None:
            t0, t1 = m.extent if m.extent is not None else (0.0, 1.0)
            m.window.x_min = float(x_min) if x_min is not None else t0
            m.window.x_max = float(x_max) if x_max is not None else t1
            self.redraw()
        return self.fig

    def set_edit_mode(self, mode: str) -> None:  # noqa: ARG002
        """React to an edit-mode change: cancel any in-progress marker drag.

        The mode itself is read live from the combo box by the gesture
        dispatcher, so nothing else needs storing.
        """
        self._line_drag = None

    # ------------------------------------------------------------------
    # Figure setup
    # ------------------------------------------------------------------

    def _build_figure(self) -> None:
        """Create a fresh 5:1 ECG-over-overview figure."""
        self.fig = Figure(facecolor="white")
        gs = self.fig.add_gridspec(
            2, 1, height_ratios=[5, 1], hspace=0.12,
            left=0.03, right=0.97, top=0.93, bottom=0.07,
        )
        self.ax_ecg = self.fig.add_subplot(gs[0])
        self.ax_overview = self.fig.add_subplot(gs[1])
        self._ax_br_twin = None

    def _mount_canvas(self) -> None:
        """Swap in a canvas backed by the freshly built figure."""
        self.canvas = swap_canvas(self.layout(), self.canvas, self.fig, index=1)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.setFocus()

    def _connect_events(self) -> None:
        """Connect matplotlib mouse/key callbacks, disconnecting any stale ones."""
        for cid in (self._cid_press, self._cid_move, self._cid_release, self._cid_key):
            if cid is not None:
                self.fig.canvas.mpl_disconnect(cid)
        connect = self.fig.canvas.mpl_connect
        self._cid_press = connect("button_press_event", self._on_press)
        self._cid_move = connect("motion_notify_event", self._on_motion)
        self._cid_release = connect("button_release_event", self._on_release)
        self._cid_key = connect("key_press_event", self._on_key_press)
        connect("resize_event", self._on_canvas_resize)

    def _build_navigation_bar(self) -> QWidget:
        """Build the icon toolbar shown beneath the canvas."""
        buttons = [
            make_nav_button("fa6s.right-to-bracket", self.go_to_start, rotate=180, tooltip="Goto Start"),
            make_nav_button("fa6s.backward", self.pan_left, tooltip="Pan Left"),
            make_nav_button("fa6s.square-caret-left", self.prev, tooltip="Previous abnormal beat"),
            make_nav_button("ei.zoom-in", self.zoom_in, tooltip="Zoom In"),
            make_nav_button("ei.zoom-out", self.zoom_out, tooltip="Zoom Out"),
            make_nav_button("fa6s.square-caret-right", self.next, tooltip="Next abnormal beat"),
            make_nav_button("fa6s.forward", self.pan_right, tooltip="Pan Right"),
            make_nav_button("fa6s.right-to-bracket", self.go_to_end, tooltip="Goto End"),
        ]
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        for btn in buttons:
            row.addWidget(btn)
        bar.setFixedHeight(46)
        return bar

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def redraw(self) -> None:
        """Repaint the ECG panel and slide the overview rectangle, then flush.

        The overview *trace* is static (drawn once by
        :meth:`_draw_overview_static`); here only its zoom rectangle moves, so
        panning never re-decimates the whole recording.
        """
        m = self._model
        if m is None:
            return
        self._marker_lines = []
        self._marker_times = _NO_TIMES
        self._draw_ecg(m, lift_for_resp=m.has_resp())
        self._draw_epoch_arrows(m)
        self._draw_breathing(m)
        if m.rtop_ctrl is not None:
            self._draw_rtops_and_ibis(m)
        if self.overview_window is not None:
            self.overview_window.set_window(m.window.x_min, m.window.x_max)
        self.canvas.draw_idle()

    def _draw_ecg(self, m: PrepModel, *, lift_for_resp: bool) -> None:
        """Draw the decimated ECG for the visible window, auto-scaling y."""
        ax = self.ax_ecg
        assert ax is not None
        ax.clear()
        ecg = m.ecg_display
        if ecg is None or not ecg.times.size:
            style_axis_clean(ax)
            return

        x0, x1 = m.window.x_min, m.window.x_max
        seg = ecg.window(x0, x1)
        t, v = decimate_minmax(seg.times, seg.values)
        if t.size == 0:  # window fell outside the recording
            t, v = decimate_minmax(ecg.times, ecg.values)

        ax.plot(t, v, color=_C_ECG, linewidth=0.8, zorder=2)
        style_axis_clean(ax)
        self._set_time_axis(ax, x0, x1)
        ax.relim()
        ax.autoscale_view(scalex=False, scaley=True)

        # Add headroom so the tallest R-wave and the IBI band (drawn at
        # y≈0.985 axis-fraction) never clip the trace.  When the breathing
        # overlay shares the panel, give extra room *below* so the ECG sits in
        # the upper part and the two signals stay visually separated — without
        # shifting the view down and clipping the peaks (the V2 bug).
        y0, y1 = ax.get_ylim()
        yr = y1 - y0
        if np.isfinite(yr) and yr > 0:
            bottom = _Y_MARGIN_BOTTOM_RESP if lift_for_resp else _Y_MARGIN_BOTTOM
            ax.set_ylim(y0 - bottom * yr, y1 + _Y_MARGIN_TOP * yr)

    def _draw_breathing(self, m: PrepModel) -> None:
        """Draw the respiration twinx overlay and inhalation shading, if present.

        The twinx axis is torn down and rebuilt on every redraw so it never
        stacks.  Inhalation phases (``"INH"`` intervals on the ``"breath"``
        channel) are shaded on the ECG axis behind both traces.
        """
        ax = self.ax_ecg
        assert ax is not None

        if self._ax_br_twin is not None:
            try:
                self._ax_br_twin.remove()
            except Exception:
                pass
            self._ax_br_twin = None

        resp = m.resp
        if resp is None or not resp.times.size:
            return

        x0, x1 = m.window.x_min, m.window.x_max

        breath = m.session.intervals.get("breath")
        if breath is not None:
            inh = breath.window(x0, x1).of("INH")
            for s, e in zip(inh.starts.tolist(), inh.ends.tolist()):
                ax.axvspan(s, e, color=_C_INH, alpha=1.0, linewidth=0, zorder=0)

        twin = ax.twinx()
        self._ax_br_twin = twin

        seg = resp.window(x0, x1)
        t, v = decimate_minmax(seg.times, seg.values)
        twin.plot(t, v, color=_C_RESP, linewidth=1.0, zorder=1)
        twin.set_xlim(x0, x1)

        ystate = m.window.y.get("br", YAxisState())
        if not ystate.auto and ystate.ymin is not None and ystate.ymax is not None:
            twin.set_ylim(ystate.ymin, ystate.ymax)

        style_axis_clean(twin)
        twin.tick_params(axis="y", colors=_C_RESP, labelsize=8)
        twin.set_ylabel("Breathing", color=_C_RESP, fontsize=8)
        twin.spines["right"].set_alpha(0.3)
        twin.spines["right"].set_visible(True)
        twin.get_yaxis().set_visible(True)
        # Keep breathing visually beneath the ECG trace.
        twin.set_zorder(0)
        ax.set_zorder(1)
        ax.set_facecolor("none")

    def _draw_epoch_arrows(self, m: PrepModel) -> None:
        """Draw labelled double-headed arrows for active epochs above the ECG.

        Epochs are clipped to the visible window and stacked into lanes so
        overlapping spans do not collide.  Drawn in axis-fraction y so they
        float above the autoscaled trace regardless of amplitude.
        """
        ax = self.ax_ecg
        assert ax is not None
        if not m.session.epochs:
            return

        x0, x1 = m.window.x_min, m.window.x_max
        visible: list[tuple[str, float, float]] = []
        for name, ep in m.session.epochs.items():
            if not getattr(ep, "active", True):
                continue
            a = max(float(ep.start), x0)
            b = min(float(ep.end), x1)
            if b > a:
                visible.append((name, a, b))
        if not visible:
            return

        # Greedy lane assignment: an arrow joins the first lane whose last
        # arrow ends before this one starts.
        visible.sort(key=lambda item: item[1])
        lane_end: list[float] = []
        base_y, lane_step = 1.04, 0.03
        xform = ax.get_xaxis_transform()
        for name, a, b in visible:
            lane = next((i for i, end in enumerate(lane_end) if a >= end), len(lane_end))
            if lane == len(lane_end):
                lane_end.append(b)
            else:
                lane_end[lane] = b
            y = base_y + lane * lane_step
            ax.add_patch(FancyArrowPatch(
                (a, y), (b, y), arrowstyle="<->",
                color=_C_EPOCH, mutation_scale=18.0, linewidth=0.5,
                transform=xform, clip_on=False, zorder=4,
            ))
            ax.text(
                0.5 * (a + b), y + 0.012, str(name),
                ha="center", va="bottom", fontsize=8, color=_C_EPOCH,
                transform=xform, clip_on=False, zorder=4,
            )

    def _draw_rtops_and_ibis(self, m: PrepModel) -> None:
        """Draw R-peak markers (hit-testable artists) and IBI annotation arrows.

        Queries one second beyond each edge so boundary IBIs are correct.  The
        whole layer is skipped when more than :data:`_MAX_VISIBLE_RTOPS`
        markers are visible, keeping the UI responsive when zoomed out.

        Markers are plain full-height vertical lines stored alongside their
        peak times in :attr:`_marker_lines` / :attr:`_marker_times`, so the
        gesture dispatcher can hit-test them without a second event handler.
        """
        ax = self.ax_ecg
        assert ax is not None and m.rtop_ctrl is not None

        view = m.rtop_ctrl.window_view(m.window.x_min - 1.0, m.window.x_max + 1.0)
        if view.times.size > _MAX_VISIBLE_RTOPS:
            return

        xform = ax.get_xaxis_transform()
        times: list[float] = []
        for i in range(view.times.size):
            t = float(view.times[i])
            color = _RTOP_COLORS.get(str(view.labels[i]), _RTOP_COLORS["N"])
            # y in axis-fraction [0, 1] → full height regardless of autoscale.
            line, = ax.plot(
                [t, t], [0.0, 1.0], transform=xform,
                color=color, linewidth=0.8, alpha=0.6, zorder=6,
            )
            self._marker_lines.append(line)
            times.append(t)
        self._marker_times = np.asarray(times, dtype=float)

        for i in range(view.times.size):
            if i >= view.ibi.size:
                continue
            ibi_val = float(view.ibi[i])
            if not np.isfinite(ibi_val) or ibi_val <= 0:
                continue
            t0 = float(view.times[i])
            t1 = t0 + ibi_val
            ax.add_patch(FancyArrowPatch(
                (t0, _Y_IBI), (t1, _Y_IBI), arrowstyle="<->",
                color=_C_IBI, mutation_scale=10, linewidth=0.8,
                transform=xform, clip_on=False, zorder=5,
            ))
            ax.text(
                0.5 * (t0 + t1), _Y_IBI, f"{1000.0 * ibi_val:.0f}",
                ha="center", va="center", fontsize=6, color=_C_IBI,
                transform=xform, clip_on=False, zorder=10,
                bbox=dict(facecolor="white", edgecolor="none", alpha=1.0, pad=1.2),
            )

    def _draw_overview_static(self) -> None:
        """Draw the full-recording overview trace once and seed the rectangle.

        Called on load only.  The decimated whole-signal trace never changes
        afterwards; :meth:`redraw` repositions :attr:`overview_window` rather
        than redrawing this.
        """
        m = self._model
        ax = self.ax_overview
        assert m is not None and ax is not None
        ax.clear()
        ecg = m.ecg_display
        if ecg is not None and ecg.times.size:
            t, v = decimate_minmax(ecg.times, ecg.values)
            ax.plot(t, v, linewidth=0.25, alpha=0.5, color=_C_OVERVIEW)
            self._set_time_axis(ax, float(ecg.times[0]), float(ecg.times[-1]))
        style_axis_clean(ax)
        ax.set_yticks([])
        self.overview_window = OverviewWindow(ax, m.window.x_min, m.window.x_max)

    @staticmethod
    def _set_time_axis(ax: Axes, x_min: float, x_max: float) -> None:
        """Set x-limits and pick a readable tick spacing for the window width."""
        ax.set_xlim(x_min, x_max)
        width = max(x_max - x_min, 1e-6)
        major = math.pow(10, round(math.log10(width)) - 1)
        ax.xaxis.set_major_locator(MultipleLocator(major))
        ax.xaxis.set_minor_locator(MultipleLocator(major / 5))
        ax.set_xlabel("Time (s)")

    # ------------------------------------------------------------------
    # Redraw scheduling
    # ------------------------------------------------------------------

    def _schedule_redraw(self) -> None:
        """Start the debounce timer for a coalesced redraw."""
        self._redraw_timer.start()

    def _deferred_redraw(self) -> None:
        """Redraw and announce the new window once the debounce delay elapses."""
        try:
            self.redraw()
            self.viewChanged.emit()
        except RuntimeError:
            pass  # widget torn down mid-timer

    def hideEvent(self, event) -> None:
        """Stop the debounce timer so it cannot paint a hidden canvas."""
        self._redraw_timer.stop()
        super().hideEvent(event)

    def _on_canvas_resize(self, event) -> None:  # noqa: ARG002
        """Drop the blit cache; its pixel dimensions no longer match the canvas."""
        self._overview_bg = None

    # ------------------------------------------------------------------
    # Navigation actions (toolbar)
    # ------------------------------------------------------------------

    def zoom_in(self) -> None:
        if self._model is not None and self._model.navigator.zoom_in():
            self._schedule_redraw()

    def zoom_out(self) -> None:
        if self._model is not None and self._model.navigator.zoom_out():
            self._schedule_redraw()

    def pan_left(self) -> None:
        if self._model is not None and self._model.navigator.pan_left():
            self._schedule_redraw()

    def pan_right(self) -> None:
        if self._model is not None and self._model.navigator.pan_right():
            self._schedule_redraw()

    def go_to_start(self) -> None:
        if self._model is not None and self._model.navigator.go_to_start():
            self._schedule_redraw()

    def go_to_end(self) -> None:
        if self._model is not None and self._model.navigator.go_to_end():
            self._schedule_redraw()

    def next(self) -> None:
        """Centre the window on the next abnormal beat after the right edge."""
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        t = m.rtop_ctrl.next_non_normal(m.window.x_max)
        if t is not None and m.navigator.center_on(t):
            self._schedule_redraw()

    def prev(self) -> None:
        """Centre the window on the previous abnormal beat before the left edge."""
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        t = m.rtop_ctrl.prev_non_normal(m.window.x_min)
        if t is not None and m.navigator.center_on(t):
            self._schedule_redraw()

    # ------------------------------------------------------------------
    # Overview blit (smooth window dragging)
    # ------------------------------------------------------------------

    def _begin_overview_blit(self) -> None:
        """Capture an overview-axis snapshot for cheap drag repaints."""
        if self.overview_window is None or self.ax_overview is None:
            return
        try:
            patch = self.overview_window.patch
            patch.set_animated(True)
            self.canvas.draw()
            self._overview_bg = self.canvas.copy_from_bbox(self.ax_overview.bbox)
            self.ax_overview.draw_artist(patch)
            self.canvas.blit(self.ax_overview.bbox)
        except Exception:
            self._overview_bg = None

    def _update_overview_blit(self) -> None:
        """Restore the snapshot and redraw only the moving zoom rectangle."""
        if self._overview_bg is None or self.overview_window is None:
            self.canvas.draw_idle()
            return
        try:
            self.canvas.restore_region(self._overview_bg)
            self.ax_overview.draw_artist(self.overview_window.patch)
            self.canvas.blit(self.ax_overview.bbox)
        except Exception:
            self.canvas.draw_idle()

    def _end_overview_blit(self) -> None:
        """Tear down blit state when a drag finishes."""
        if self.overview_window is not None:
            try:
                self.overview_window.patch.set_animated(False)
            except Exception:
                pass
        self._overview_bg = None

    # ------------------------------------------------------------------
    # Gesture dispatch — one press / motion / release for every interaction
    # ------------------------------------------------------------------

    def _on_press(self, event) -> None:
        """Route a press: overview drag, or an ECG-axis edit by current mode."""
        m = self._model
        if m is None or event.xdata is None:
            return
        if event.inaxes is self.ax_overview:
            self._press_overview(event, m)
        elif event.inaxes is self.ax_ecg and m.rtop_ctrl is not None:
            self._press_ecg(event, m)

    def _press_overview(self, event, m: PrepModel) -> None:
        """Begin an overview drag, grabbing the nearest edge or the body."""
        w = m.window.width()
        if abs(event.xdata - m.window.x_min) < _EDGE_GRAB_FRAC * w:
            mode = "left"
        elif abs(event.xdata - m.window.x_max) < _EDGE_GRAB_FRAC * w:
            mode = "right"
        else:
            mode = "center"
        m.window.begin_drag(mode)
        self._begin_overview_blit()

    def _press_ecg(self, event, m: PrepModel) -> None:
        """Add / remove / start-dragging a marker per the current edit mode."""
        mode = self.mode_selector.currentText()
        if mode == "Add":
            self._apply_add(float(event.xdata))
        elif mode == "Remove":
            i = self._nearest_marker(event)
            if i is not None:
                self._apply_delete(float(self._marker_times[i]))
        elif mode == "Drag":
            i = self._nearest_marker(event)
            if i is not None:
                self._line_drag = _LineDrag(
                    float(self._marker_times[i]), self._marker_lines[i]
                )

    def _on_motion(self, event) -> None:
        """Route motion to the active gesture: overview drag or marker drag."""
        m = self._model
        if m is None:
            return
        if m.window.drag_mode is not None:
            self._motion_overview(event, m)
        elif self._line_drag is not None:
            self._motion_marker(event)

    def _motion_overview(self, event, m: PrepModel) -> None:
        """Resize/translate the zoom window while dragging it in the overview."""
        if (
            event.inaxes is not self.ax_overview
            or event.xdata is None
            or m.window.initial_xmin is None
            or m.window.initial_xmax is None
        ):
            return
        x = event.xdata
        if m.window.drag_mode == "left":
            x_min = min(x, m.window.x_max - 0.1)
            x_max = m.window.x_max
        elif m.window.drag_mode == "right":
            x_min = m.window.x_min
            x_max = max(x, m.window.x_min + 0.1)
        else:
            dx = x - 0.5 * (m.window.initial_xmin + m.window.initial_xmax)
            x_min = m.window.initial_xmin + dx
            x_max = m.window.initial_xmax + dx

        x_min, x_max = m.navigator.constrain(x_min, x_max)
        m.window.x_min, m.window.x_max = x_min, x_max
        if self.overview_window is not None:
            self.overview_window.set_window(x_min, x_max)
        self._update_overview_blit()
        self._schedule_redraw()

    def _motion_marker(self, event) -> None:
        """Slide the grabbed marker to follow the cursor (visual feedback only)."""
        if event.xdata is None or event.inaxes is not self.ax_ecg:
            return
        assert self._line_drag is not None
        self._line_drag.line.set_xdata([event.xdata, event.xdata])
        self.canvas.draw_idle()

    def _on_release(self, event) -> None:
        """Finish whichever gesture is active; commit a marker drag if any."""
        m = self._model
        if m is None:
            return
        if m.window.drag_mode is not None:
            m.window.end_drag()
            self._end_overview_blit()
            self.redraw()
            self.viewChanged.emit()
        elif self._line_drag is not None:
            drag = self._line_drag
            self._line_drag = None
            if event.xdata is not None and event.inaxes is self.ax_ecg:
                self._apply_move(drag.orig_time, float(event.xdata))
            else:
                self.redraw()  # released off-axis — snap the marker back

    def _nearest_marker(self, event) -> int | None:
        """Index of the marker within :data:`_PICK_TOLERANCE_PX` of the cursor.

        Compares in screen pixels so the grab tolerance is uniform at any
        zoom.  Returns ``None`` when no marker is close enough.
        """
        if self.ax_ecg is None or self._marker_times.size == 0 or event.x is None:
            return None
        pts = np.column_stack(
            [self._marker_times, np.zeros(self._marker_times.size)]
        )
        px = self.ax_ecg.transData.transform(pts)[:, 0]
        d = np.abs(px - event.x)
        i = int(np.argmin(d))
        return i if d[i] <= _PICK_TOLERANCE_PX else None

    # ------------------------------------------------------------------
    # Edit commits (called by the dispatcher; also a testable seam)
    # ------------------------------------------------------------------

    def _apply_add(self, t: float) -> None:
        """Insert an R-peak at time *t*, redraw, then re-classify off-thread."""
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        m.rtop_ctrl.add_no_classify(t, label="N")
        self.redraw()
        self._classify_async()

    def _apply_move(self, old_t: float, new_t: float) -> None:
        """Move the R-peak nearest *old_t* to *new_t*, redraw, re-classify."""
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        m.rtop_ctrl.move_no_classify(old_t, new_t)
        self.redraw()
        self._classify_async()

    def _apply_delete(self, t: float) -> None:
        """Delete the R-peak nearest *t*, redraw, then re-classify off-thread."""
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        m.rtop_ctrl.delete_no_classify(t)
        self.redraw()
        self._classify_async()

    # ------------------------------------------------------------------
    # Keyboard (breathing y-zoom)
    # ------------------------------------------------------------------

    def _on_key_press(self, event) -> None:
        """Keyboard y-zoom for the breathing overlay.

        ``Space`` resets to auto, ``=`` fits to the visible breath, ``+`` /
        ``-`` zoom, ``Up`` / ``Down`` pan.  All keys operate on the stored
        ``"br"`` y-state so the choice survives a redraw.  ECG y is never
        touched, keeping the R-peak markers anchored to the trace.
        """
        m = self._model
        if m is None or self._ax_br_twin is None:
            return
        ax = self._ax_br_twin
        ystate = m.window.y.get("br")
        if ystate is None:
            return

        if event.key == " ":
            ystate.reset()
            self.redraw()
            return

        if event.key == "=":
            resp = m.resp
            if resp is not None:
                seg = resp.window(m.window.x_min, m.window.x_max)
                if seg.values.size:
                    ymin, ymax = float(seg.values.min()), float(seg.values.max())
                    if ymin < ymax:
                        ystate.auto = False
                        ystate.ymin, ystate.ymax = ymin, ymax
                        self.redraw()
            return

        if ystate.auto:
            y0, y1 = ax.get_ylim()
            ystate.auto = False
            ystate.ymin, ystate.ymax = float(y0), float(y1)
        if ystate.ymin is None or ystate.ymax is None:
            return

        height = ystate.ymax - ystate.ymin
        if event.key == "+":
            ystate.ymax = ystate.ymin + height * 0.8
        elif event.key == "-":
            ystate.ymax = ystate.ymin + height * 1.25
        elif event.key == "up":
            ystate.ymin -= 0.15 * height
            ystate.ymax -= 0.15 * height
        elif event.key == "down":
            ystate.ymin += 0.15 * height
            ystate.ymax += 0.15 * height
        else:
            return
        self.redraw()

    # ------------------------------------------------------------------
    # Background IBI re-classification
    # ------------------------------------------------------------------

    def _classify_async(self) -> None:
        """Re-classify IBIs on a pool thread, then commit labels and notify.

        The structural edit is already drawn with stale labels.  Here the
        IBI/label arrays are snapshotted on the main thread, classified on the
        pool, and the result applied back on the main thread.  The scheduler's
        generation counter discards a result that a later edit has superseded,
        and a length check guards against applying labels to a peak set that
        changed underneath us.
        """
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        ctrl = m.rtop_ctrl
        ibi_snap = ctrl.ibi.copy()
        labels_snap = ctrl.labels.copy()
        classify_kwargs = m.cardio.classify_kwargs

        def compute():
            classify_ibi(ibi_snap, labels_snap, **classify_kwargs)
            return labels_snap

        def on_done(new_labels: np.ndarray) -> None:
            if self._model is None or self._model.rtop_ctrl is not ctrl:
                return  # session was reloaded under us
            if new_labels.shape[0] != ctrl.count:
                return  # superseded by a later edit
            try:
                ctrl.labels = new_labels  # setter commits to session
                self.redraw()
            except RuntimeError:
                return
            self.dataEdited.emit()

        self._classify_scheduler.submit("prep_classify", compute, on_done)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cardio_params(config) -> CardioParams:
        """Resolve :class:`CardioParams` from the workspace *config*.

        Accepts a :class:`~spectHR.config.WorkspaceView` (the usual
        ``Parameters`` instance), a raw workspace dict, or ``None`` — falling
        back to defaults so headless/test callers work without a workspace.
        """
        if isinstance(config, WorkspaceView):
            return config.cardio_params
        if isinstance(config, dict):
            return WorkspaceView(config).cardio_params
        return CardioParams()
