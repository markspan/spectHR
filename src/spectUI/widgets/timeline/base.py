# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`TimelineView` — base widget for every scrolling-time-series dock.

It owns the parts every timeline dock shares: a main panel over a thin
full-recording overview strip, a draggable zoom rectangle (blitted for
smooth dragging), a zoom / pan / goto navigation bar, epoch arrows, and
debounced repaints.  The visible-window state lives in a
:class:`~spectUI.widgets.timeline.model.TimelineModel`; the widget holds one
``TimelineModel | None``.

Concrete docks subclass this and fill in a handful of hooks:

``_build_model(session, config)``   (required) build the dock's TimelineModel
``_draw_main()``                     (required) paint the main panel
``_overview_data()``                 the full-recording trace for the overview
``_header_widgets()``                widgets to mount above the canvas
``_on_main_press/motion/release``    gestures on the main axis (editing docks)
``_on_key``                          key handling
``_next_target`` / ``_prev_target``  targets for the prev/next nav buttons

One gesture dispatcher (``_on_press`` / ``_on_motion`` / ``_on_release``)
owns every interaction: it handles the overview drag itself and forwards
main-axis events to the hooks, so editing docks never wire a second,
competing set of canvas callbacks.
"""
from __future__ import annotations

import math

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import MultipleLocator
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from spectHR.session import Session
from spectHR.Tools.Decimation import decimate_minmax
from spectUI.common import (
    OverviewWindow,
    make_nav_button,
    style_axis_clean,
    swap_canvas,
)
from spectUI.widgets.timeline.model import TimelineModel

# Palette shared across timeline docks.
_C_OVERVIEW = "#2980b9"   # blue — overview trace and zoom rectangle
_C_EPOCH = "#16a085"      # teal — epoch arrows

# Debounce (ms) coalescing rapid window changes into one repaint.
_REDRAW_DEBOUNCE_MS = 160
# Fraction of the rectangle width that counts as grabbing an edge vs the body.
_EDGE_GRAB_FRAC = 0.3
# Epoch-arrow layout (axis-fraction y above the trace).
_EPOCH_BASE_Y = 1.04
_EPOCH_LANE_STEP = 0.03


class TimelineView(QWidget):
    """Scrolling-time-series dock base (figure, overview, navigation).

    Signals
    -------
    viewChanged
        Emitted after the visible window changes, so the coordinator can
        keep sibling timeline docks scrolling together.
    epoch_request(str)
        Emitted to ask the host to switch the globally active epoch.
    """

    viewChanged = Signal()
    epoch_request = Signal(str)

    # Main-panel : overview height ratio.
    MAIN_OVERVIEW_RATIO: tuple[int, int] = (5, 1)
    # Tooltips for the prev/next nav buttons (override per dock).
    PREV_TOOLTIP: str = "Previous marker"
    NEXT_TOOLTIP: str = "Next marker"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._model: TimelineModel | None = None
        self._config = None

        self.fig: Figure = Figure()
        self.canvas: FigureCanvas = FigureCanvas(self.fig)
        self.ax_main: Axes | None = None
        self.ax_overview: Axes | None = None

        self.overview_window: OverviewWindow | None = None
        self._overview_bg = None  # blit pixel-buffer cache

        self._cid_press: int | None = None
        self._cid_move: int | None = None
        self._cid_release: int | None = None
        self._cid_key: int | None = None

        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(_REDRAW_DEBOUNCE_MS)
        self._redraw_timer.timeout.connect(self._deferred_redraw)

        # Optional header widgets (e.g. an edit-mode selector) above the canvas.
        header = self._header_widgets()
        self._canvas_index = len(header)
        self.navigation_bar = self._build_navigation_bar()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for w in header:
            layout.addWidget(w)
        layout.addWidget(self.canvas)
        layout.addWidget(self.navigation_bar)
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Public interface (called by the host / coordinator)
    # ------------------------------------------------------------------

    def set_session(self, session: Session, config=None) -> None:
        """Load *session*: build the model, figure, and first paint."""
        self._config = config
        self._model = self._build_model(session, config)
        self._build_figure()
        self._mount_canvas()
        self._connect_events()
        self._on_loaded()
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

    def refresh(self) -> None:
        """Rebuild derived data from the (possibly edited) session and repaint.

        Default implementation rebuilds the model from the current session,
        preserving the visible window, then redraws.  Docks that derive
        nothing from edited channels can leave this as-is cheaply.
        """
        m = self._model
        if m is None:
            return
        x_min, x_max = m.window.x_min, m.window.x_max
        self._model = self._build_model(m.session, self._config)
        self._model.window.x_min, self._model.window.x_max = x_min, x_max
        self._draw_overview_static()
        self.redraw()

    def current_window(self) -> "tuple[float, float] | None":
        """The visible ``(x_min, x_max)``, or ``None`` when nothing is loaded."""
        m = self._model
        return (m.window.x_min, m.window.x_max) if m is not None else None

    def apply_window(self, x_min: float, x_max: float) -> None:
        """Set the visible window (used by the coordinator to sync siblings)."""
        m = self._model
        if m is None:
            return
        m.window.x_min, m.window.x_max = m.navigator.constrain(x_min, x_max)
        self._schedule_redraw()

    # ------------------------------------------------------------------
    # Hooks for subclasses
    # ------------------------------------------------------------------

    def _build_model(self, session: Session, config) -> TimelineModel:
        """Build the dock's :class:`TimelineModel`.  Must be overridden."""
        raise NotImplementedError

    def _draw_main(self) -> None:
        """Paint the main panel into ``self.ax_main``.  Must be overridden."""
        raise NotImplementedError

    def _overview_data(self) -> "tuple[np.ndarray, np.ndarray] | None":
        """Return the full-recording ``(times, values)`` for the overview trace."""
        return None

    def _header_widgets(self) -> list[QWidget]:
        """Widgets to mount above the canvas (default: none)."""
        return []

    def _on_loaded(self) -> None:
        """Called at the end of a load, before the first redraw (default no-op)."""

    def _on_main_press(self, event) -> None:
        """Press on the main axis (default no-op; editing docks override)."""

    def _on_main_motion(self, event) -> None:
        """Motion with no overview drag active (default no-op)."""

    def _on_main_release(self, event) -> None:
        """Release with no overview drag active (default no-op)."""

    def _on_key(self, event) -> None:
        """Key press on the canvas (default no-op)."""

    def _next_target(self, after: float) -> "float | None":
        """Time for the 'next' nav button to centre on (default: none)."""
        return None

    def _prev_target(self, before: float) -> "float | None":
        """Time for the 'previous' nav button to centre on (default: none)."""
        return None

    def _nav_button_specs(self):
        """``(icon, slot, kwargs)`` triples for the navigation bar."""
        return [
            ("fa6s.right-to-bracket", self.go_to_start, dict(rotate=180, tooltip="Goto Start")),
            ("fa6s.backward", self.pan_left, dict(tooltip="Pan Left")),
            ("fa6s.square-caret-left", self.prev, dict(tooltip=self.PREV_TOOLTIP)),
            ("ei.zoom-in", self.zoom_in, dict(tooltip="Zoom In")),
            ("ei.zoom-out", self.zoom_out, dict(tooltip="Zoom Out")),
            ("fa6s.square-caret-right", self.next, dict(tooltip=self.NEXT_TOOLTIP)),
            ("fa6s.forward", self.pan_right, dict(tooltip="Pan Right")),
            ("fa6s.right-to-bracket", self.go_to_end, dict(tooltip="Goto End")),
        ]

    # ------------------------------------------------------------------
    # Figure setup
    # ------------------------------------------------------------------

    def _build_figure(self) -> None:
        """Create a fresh main-over-overview figure."""
        self.fig = Figure(facecolor="white")
        gs = self.fig.add_gridspec(
            2, 1, height_ratios=list(self.MAIN_OVERVIEW_RATIO), hspace=0.12,
            left=0.03, right=0.97, top=0.93, bottom=0.07,
        )
        self.ax_main = self.fig.add_subplot(gs[0])
        self.ax_overview = self.fig.add_subplot(gs[1])

    def _mount_canvas(self) -> None:
        """Swap in a canvas backed by the freshly built figure."""
        self.canvas = swap_canvas(
            self.layout(), self.canvas, self.fig, index=self._canvas_index
        )
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.setFocus()

    def _connect_events(self) -> None:
        """Connect matplotlib mouse/key callbacks, disconnecting stale ones."""
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
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        for icon, slot, kwargs in self._nav_button_specs():
            row.addWidget(make_nav_button(icon, slot, **kwargs))
        bar.setFixedHeight(46)
        return bar

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def redraw(self) -> None:
        """Repaint the main panel + epoch arrows; slide the overview rectangle."""
        m = self._model
        if m is None:
            return
        self._draw_main()
        self._draw_epoch_arrows()
        if self.overview_window is not None:
            self.overview_window.set_window(m.window.x_min, m.window.x_max)
        self.canvas.draw_idle()

    def _draw_epoch_arrows(self) -> None:
        """Draw labelled double-headed arrows for active epochs above the panel.

        Epochs are clipped to the visible window and stacked into lanes so
        overlapping spans do not collide.  Drawn in axis-fraction y so they
        float above the trace regardless of amplitude.
        """
        ax, m = self.ax_main, self._model
        assert ax is not None and m is not None
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

        visible.sort(key=lambda item: item[1])
        lane_end: list[float] = []
        xform = ax.get_xaxis_transform()
        for name, a, b in visible:
            lane = next((i for i, end in enumerate(lane_end) if a >= end), len(lane_end))
            if lane == len(lane_end):
                lane_end.append(b)
            else:
                lane_end[lane] = b
            y = _EPOCH_BASE_Y + lane * _EPOCH_LANE_STEP
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

    def _draw_overview_static(self) -> None:
        """Draw the full-recording overview trace once and seed the rectangle."""
        m, ax = self._model, self.ax_overview
        assert m is not None and ax is not None
        ax.clear()
        data = self._overview_data()
        if data is not None and data[0].size:
            t, v = decimate_minmax(data[0], data[1])
            ax.plot(t, v, linewidth=0.25, alpha=0.5, color=_C_OVERVIEW)
            ext = m.extent if m.extent is not None else (float(data[0][0]), float(data[0][-1]))
            self._set_time_axis(ax, ext[0], ext[1])
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
        """Centre the window on the next subclass-defined target, if any."""
        m = self._model
        if m is None:
            return
        t = self._next_target(m.window.x_max)
        if t is not None and m.navigator.center_on(t):
            self._schedule_redraw()

    def prev(self) -> None:
        """Centre the window on the previous subclass-defined target, if any."""
        m = self._model
        if m is None:
            return
        t = self._prev_target(m.window.x_min)
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
        """Route a press: overview drag, or a main-axis gesture hook."""
        m = self._model
        if m is None or event.xdata is None:
            return
        if event.inaxes is self.ax_overview:
            self._press_overview(event)
        else:
            self._on_main_press(event)

    def _press_overview(self, event) -> None:
        """Begin an overview drag, grabbing the nearest edge or the body."""
        m = self._model
        assert m is not None
        w = m.window.width()
        if abs(event.xdata - m.window.x_min) < _EDGE_GRAB_FRAC * w:
            mode = "left"
        elif abs(event.xdata - m.window.x_max) < _EDGE_GRAB_FRAC * w:
            mode = "right"
        else:
            mode = "center"
        m.window.begin_drag(mode)
        self._begin_overview_blit()

    def _on_motion(self, event) -> None:
        """Route motion to the active gesture: overview drag or main-axis hook."""
        m = self._model
        if m is None:
            return
        if m.window.drag_mode is not None:
            self._motion_overview(event)
        else:
            self._on_main_motion(event)

    def _motion_overview(self, event) -> None:
        """Resize/translate the zoom window while dragging it in the overview."""
        m = self._model
        assert m is not None
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

    def _on_release(self, event) -> None:
        """Finish an overview drag, else forward to the main-axis release hook."""
        m = self._model
        if m is None:
            return
        if m.window.drag_mode is not None:
            m.window.end_drag()
            self._end_overview_blit()
            self.redraw()
            self.viewChanged.emit()
        else:
            self._on_main_release(event)

    def _on_key_press(self, event) -> None:
        """Forward key presses to the subclass hook."""
        self._on_key(event)
