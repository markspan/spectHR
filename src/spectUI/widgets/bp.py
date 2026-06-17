# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`BPSeriesWidget`, the blood-pressure waveform dock.

A :class:`~spectUI.widgets.timeline.base.TimelineView` that plots the
calibrated blood-pressure channel.  Calibration (raw ADC → mmHg) is applied
once in the load pipeline (``apply_bp_calibration``), so the widget only
windows and decimates the channel for display, it computes nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from spectHR.session import Samples, Session
from spectHR.Tools.Decimation import decimate_minmax
from spectUI.common import style_axis_clean
from spectUI.widgets.timeline.base import TimelineView
from spectUI.widgets.timeline.model import TimelineModel

_C_BP = "#1f3a93"   # dark blue, blood pressure


@dataclass
class BPModel(TimelineModel):
    """Per-load state for the BP dock: the calibrated waveform.

    Attributes
    ----------
    bp
        The blood-pressure :class:`~spectHR.session.Samples`, or ``None``.
    """

    bp: Samples | None

    @classmethod
    def build(cls, session: Session, config=None) -> "BPModel":
        bp = session.bp
        extent: tuple[float, float] | None = None
        if bp is not None and bp.times.size:
            extent = (float(bp.times[0]), float(bp.times[-1]))
        window, navigator = cls.open_window(extent)
        return cls(
            session=session, window=window, navigator=navigator, extent=extent,
            bp=bp,
        )


class BPSeriesWidget(TimelineView):
    """Blood-pressure waveform dock."""

    def _build_model(self, session: Session, config) -> BPModel:
        return BPModel.build(session, config)

    def _overview_data(self):
        m: BPModel = self._model  # type: ignore[assignment]
        if m is None or m.bp is None or not m.bp.times.size:
            return None
        return m.bp.times, m.bp.values

    def _draw_main(self) -> None:
        m: BPModel = self._model  # type: ignore[assignment]
        ax = self.ax_main
        assert ax is not None and m is not None
        ax.clear()

        if m.bp is None or not m.bp.times.size:
            style_axis_clean(ax, show_y=True)
            ax.set_ylabel("Blood pressure (mmHg)")
            return

        x0, x1 = m.window.x_min, m.window.x_max
        seg = m.bp.window(x0, x1)
        t, v = decimate_minmax(seg.times, seg.values)
        if t.size == 0:
            t, v = decimate_minmax(m.bp.times, m.bp.values)

        ax.plot(t, v, color=_C_BP, linewidth=1.0, alpha=1.0, zorder=2)
        style_axis_clean(ax, show_y=True)
        self._set_time_axis(ax, x0, x1)
        ax.set_ylabel("Blood pressure (mmHg)")
        ax.relim()
        ax.autoscale_view(scalex=False, scaley=True)
        y0, y1 = ax.get_ylim()
        yr = y1 - y0
        if np.isfinite(yr) and yr > 0:
            ax.set_ylim(y0 - 0.08 * yr, y1 + 0.12 * yr)
