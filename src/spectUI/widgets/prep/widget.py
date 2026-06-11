# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`PrepPlotWidget` — the docked ECG pre-processing and R-peak editor.

The development-branch port of the V2 ``prepPlotWidget``.  All the scrolling
timeline machinery — visible-window model, overview strip with a draggable
zoom rectangle, zoom/pan/goto navigation, epoch arrows, the single gesture
dispatcher — is inherited from
:class:`~spectUI.widgets.timeline.base.TimelineView`.  This module adds only
what is specific to ECG pre-processing:

* the ECG trace (raw or prefiltered) with an optional respiration twinx and
  inhalation shading, plus draggable R-peak markers with IBI annotations;
* the three edit modes (Drag / Add / Remove) wired through the base's
  main-axis gesture hooks;
* background IBI re-classification after each edit.

Edits go through ``model.rtop_ctrl`` and commit back into
``session.events["hrv"]`` — call-by-reference — and :attr:`dataEdited` is
emitted so the host can mark the file dirty and refresh derived docks.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QWidget

from spectHR.config import CardioParams, WorkspaceView
from spectHR.session import Session
from spectHR.Tools.Decimation import decimate_minmax
from spectUI.common import style_axis_clean
from spectUI.plot_worker import DockScheduler
from spectUI.widgets.prep.model import PrepModel
from spectUI.widgets.timeline.base import TimelineView
from spectUI.widgets.timeline.state import YAxisState

# ─────────────────────────────────────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────────────────────────────────────

_C_ECG = "#c0392b"        # deep red — clinical ECG convention
_C_RESP = "#27ae60"       # green — respiration
_C_INH = "#d6eaf8"        # pale blue — inhalation shading
_C_IBI = "#2c3e50"        # near-black — IBI arrows/labels

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


class PrepPlotWidget(TimelineView):
    """Interactive ECG pre-processing and R-peak annotation dock.

    Signals (in addition to the inherited ``viewChanged`` / ``epoch_request``)
    -------
    dataEdited
        Emitted (no payload) after every committed R-peak edit.  Listeners
        read ``session.events["hrv"]`` directly.
    """

    dataEdited = Signal()

    PREV_TOOLTIP = "Previous abnormal beat"
    NEXT_TOOLTIP = "Next abnormal beat"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Gesture + marker state, owned by the main-axis gesture hooks.
        self._line_drag: _LineDrag | None = None
        self._marker_lines: list[Line2D] = []
        self._marker_times: np.ndarray = _NO_TIMES
        self._ax_br_twin = None  # breathing twinx, rebuilt each redraw

        self._classify_scheduler = DockScheduler()

    # ------------------------------------------------------------------
    # TimelineView hooks
    # ------------------------------------------------------------------

    def _header_widgets(self) -> list[QWidget]:
        """The edit-mode selector, mounted above the canvas."""
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["Drag", "Add", "Remove"])
        self.mode_selector.setFixedWidth(120)
        self.mode_selector.currentTextChanged.connect(self.set_edit_mode)
        return [self.mode_selector]

    def _build_model(self, session: Session, config) -> PrepModel:
        return PrepModel.build(session, self._cardio_params(config))

    def _on_loaded(self) -> None:
        """Reset transient drawing state for the freshly built figure."""
        self._line_drag = None
        self._ax_br_twin = None

    def _overview_data(self):
        m = self._model
        ecg = m.ecg_display if m is not None else None
        if ecg is None or not ecg.times.size:
            return None
        return ecg.times, ecg.values

    def _next_target(self, after: float):
        m = self._model
        return m.rtop_ctrl.next_non_normal(after) if (m and m.rtop_ctrl) else None

    def _prev_target(self, before: float):
        m = self._model
        return m.rtop_ctrl.prev_non_normal(before) if (m and m.rtop_ctrl) else None

    def set_edit_mode(self, mode: str) -> None:  # noqa: ARG002
        """React to an edit-mode change: cancel any in-progress marker drag.

        The mode itself is read live from the combo box by the gesture hooks.
        """
        self._line_drag = None

    def prepPlot(self, data: Session, x_min=None, x_max=None):
        """V2-compatible entry point: load *data*, return the figure."""
        self.set_session(data)
        m = self._model
        if (x_min is not None or x_max is not None) and m is not None:
            t0, t1 = m.extent if m.extent is not None else (0.0, 1.0)
            m.window.x_min = float(x_min) if x_min is not None else t0
            m.window.x_max = float(x_max) if x_max is not None else t1
            self.redraw()
        return self.fig

    # ------------------------------------------------------------------
    # Main-panel rendering
    # ------------------------------------------------------------------

    def _draw_main(self) -> None:
        """Paint ECG, breathing overlay and R-peak markers (epoch arrows: base)."""
        m = self._model
        assert m is not None
        self._marker_lines = []
        self._marker_times = _NO_TIMES
        self._draw_ecg(m, lift_for_resp=m.has_resp())
        self._draw_breathing(m)
        if m.rtop_ctrl is not None:
            self._draw_rtops_and_ibis(m)

    def _draw_ecg(self, m: PrepModel, *, lift_for_resp: bool) -> None:
        """Draw the decimated ECG for the visible window, auto-scaling y."""
        ax = self.ax_main
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

        # Headroom so the tallest R-wave and the IBI band (y≈0.985 axis-fraction)
        # never clip; extra room below when breathing shares the panel so the
        # two signals stay separated without shifting the view down.
        y0, y1 = ax.get_ylim()
        yr = y1 - y0
        if np.isfinite(yr) and yr > 0:
            bottom = _Y_MARGIN_BOTTOM_RESP if lift_for_resp else _Y_MARGIN_BOTTOM
            ax.set_ylim(y0 - bottom * yr, y1 + _Y_MARGIN_TOP * yr)

    def _draw_breathing(self, m: PrepModel) -> None:
        """Draw the respiration twinx overlay and inhalation shading, if present."""
        ax = self.ax_main
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
        twin.set_zorder(0)
        ax.set_zorder(1)
        ax.set_facecolor("none")

    def _draw_rtops_and_ibis(self, m: PrepModel) -> None:
        """Draw R-peak markers (hit-testable artists) and IBI annotation arrows.

        Markers are plain full-height vertical lines stored alongside their
        peak times so the gesture hooks can hit-test them.  The whole layer is
        skipped when more than :data:`_MAX_VISIBLE_RTOPS` markers are visible.
        """
        ax = self.ax_main
        assert ax is not None and m.rtop_ctrl is not None

        view = m.rtop_ctrl.window_view(m.window.x_min - 1.0, m.window.x_max + 1.0)
        if view.times.size > _MAX_VISIBLE_RTOPS:
            return

        xform = ax.get_xaxis_transform()
        times: list[float] = []
        for i in range(view.times.size):
            t = float(view.times[i])
            color = _RTOP_COLORS.get(str(view.labels[i]), _RTOP_COLORS["N"])
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

    # ------------------------------------------------------------------
    # Main-axis gesture hooks (Drag / Add / Remove)
    # ------------------------------------------------------------------

    def _on_main_press(self, event) -> None:
        """Add / remove / start-dragging a marker per the current edit mode."""
        m = self._model
        if (
            m is None or m.rtop_ctrl is None
            or event.inaxes is not self.ax_main or event.xdata is None
        ):
            return
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

    def _on_main_motion(self, event) -> None:
        """Slide the grabbed marker to follow the cursor (visual feedback only)."""
        if self._line_drag is None or event.xdata is None or event.inaxes is not self.ax_main:
            return
        self._line_drag.line.set_xdata([event.xdata, event.xdata])
        self.canvas.draw_idle()

    def _on_main_release(self, event) -> None:
        """Commit a marker drag, or snap it back when released off-axis."""
        if self._line_drag is None:
            return
        drag = self._line_drag
        self._line_drag = None
        if event.xdata is not None and event.inaxes is self.ax_main:
            self._apply_move(drag.orig_time, float(event.xdata))
        else:
            self.redraw()

    def _nearest_marker(self, event) -> "int | None":
        """Index of the marker within :data:`_PICK_TOLERANCE_PX` of the cursor.

        Compares in screen pixels so the grab tolerance is uniform at any zoom.
        """
        if self.ax_main is None or self._marker_times.size == 0 or event.x is None:
            return None
        pts = np.column_stack([self._marker_times, np.zeros(self._marker_times.size)])
        px = self.ax_main.transData.transform(pts)[:, 0]
        d = np.abs(px - event.x)
        i = int(np.argmin(d))
        return i if d[i] <= _PICK_TOLERANCE_PX else None

    # ------------------------------------------------------------------
    # Edit commits (called by the gesture hooks; also a testable seam)
    # ------------------------------------------------------------------

    def _apply_add(self, t: float) -> None:
        """Insert an R-peak at time *t*, redraw, then re-classify off-thread."""
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        m.rtop_ctrl.add_no_classify(t, label="N")
        self._after_edit()

    def _apply_move(self, old_t: float, new_t: float) -> None:
        """Move the R-peak nearest *old_t* to *new_t*, redraw, re-classify."""
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        m.rtop_ctrl.move_no_classify(old_t, new_t)
        self._after_edit()

    def _apply_delete(self, t: float) -> None:
        """Delete the R-peak nearest *t*, redraw, then re-classify off-thread."""
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        m.rtop_ctrl.delete_no_classify(t)
        self._after_edit()

    def _after_edit(self) -> None:
        """Repaint, notify dependants now, then re-classify labels off-thread.

        ``dataEdited`` fires *immediately* so derived docks (HR, Poincaré, …)
        refresh from the new beat set without waiting for the O(n) label
        re-classification, which runs on a pool thread and fires ``dataEdited``
        again once the labels settle.
        """
        self.redraw()
        self.dataEdited.emit()   # immediate — structural change is committed
        self._classify_async()   # later — refreshes again after labels update

    # ------------------------------------------------------------------
    # Keyboard (breathing y-zoom)
    # ------------------------------------------------------------------

    def _on_key(self, event) -> None:
        """Keyboard y-zoom for the breathing overlay.

        ``Space`` resets to auto, ``=`` fits to the visible breath, ``+`` /
        ``-`` zoom, ``Up`` / ``Down`` pan.  ECG y is never touched, keeping the
        R-peak markers anchored to the trace.
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
        """Re-classify the edited beats on a pool thread, then commit and notify.

        The current (immutable) :class:`Events` snapshot is handed to the pool,
        where :meth:`Events.reclassified` recomputes labels off the main
        thread; the result is applied back on the main thread.  The scheduler's
        generation counter discards a result a later edit has superseded, and a
        peak-count guard protects against a series that changed underneath us.
        """
        m = self._model
        if m is None or m.rtop_ctrl is None:
            return
        ctrl = m.rtop_ctrl
        events_snap = ctrl.events                 # frozen — safe to cross threads
        classify_kwargs = m.cardio.classify_kwargs

        def compute():
            return events_snap.reclassified(**classify_kwargs)

        def on_done(new_events) -> None:
            if self._model is None or self._model.rtop_ctrl is not ctrl:
                return  # session was reloaded under us
            if new_events.times.size != ctrl.count:
                return  # superseded by a later structural edit
            try:
                ctrl.labels = new_events.labels   # setter commits to session
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
        ``Parameters`` instance), a raw workspace dict, or ``None``.
        """
        if isinstance(config, WorkspaceView):
            return config.cardio_params
        if isinstance(config, dict):
            return WorkspaceView(config).cardio_params
        return CardioParams()
