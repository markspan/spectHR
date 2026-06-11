# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`HRSeriesWidget` — the instantaneous heart-rate (tachogram) dock.

A thin :class:`~spectUI.widgets.timeline.base.TimelineView`: it inherits the
window / overview / navigation machinery and supplies only the heart-rate
trace.  The series itself is computed in ``spectHR`` — the widget calls
:func:`~spectHR.analysis.derived_series.heart_rate_series` and plots the
result, computing nothing.  Because it derives from ``events["hrv"]``, the
coordinator refreshes it whenever an R-peak edit changes that channel.

The next/previous nav buttons jump to abnormal beats via
:meth:`Events.next_abnormal` / :meth:`Events.prev_abnormal`, mirroring the
pre-processing dock.

Follow-ups to reach full V2 parity: the respiration twinx overlay and the
per-breath RSA scatter (both already have ``spectHR`` support).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from spectHR.analysis.derived_series import heart_rate_series
from spectHR.session import Events, Session
from spectUI.common import style_axis_clean
from spectUI.widgets.timeline.base import TimelineView
from spectUI.widgets.timeline.model import TimelineModel

_C_HR = "#c0392b"   # deep red — heart rate


@dataclass
class HRModel(TimelineModel):
    """Per-load state for the HR dock: the tachogram plus its beat series.

    Attributes
    ----------
    times, hr
        Aligned beat times (s) and instantaneous heart rate (bpm), with
        artefact intervals removed.
    events
        The ``"hrv"`` :class:`Events` (or ``None``) — used for abnormal-beat
        navigation.
    """

    times: np.ndarray
    hr: np.ndarray
    events: Events | None

    @classmethod
    def build(cls, session: Session, config=None) -> "HRModel":
        hrv = session.events.get("hrv")
        if hrv is not None:
            times, hr = heart_rate_series(hrv)
        else:
            times, hr = np.array([], dtype=float), np.array([], dtype=float)

        extent: tuple[float, float] | None = None
        if times.size:
            extent = (float(times[0]), float(times[-1]))
        window, navigator = cls.open_window(extent)
        return cls(
            session=session, window=window, navigator=navigator, extent=extent,
            times=times, hr=hr, events=hrv,
        )


class HRSeriesWidget(TimelineView):
    """Instantaneous heart-rate (tachogram) dock."""

    PREV_TOOLTIP = "Previous abnormal beat"
    NEXT_TOOLTIP = "Next abnormal beat"

    # ---- TimelineView hooks ----

    def _build_model(self, session: Session, config) -> HRModel:
        return HRModel.build(session, config)

    def _overview_data(self):
        m: HRModel = self._model  # type: ignore[assignment]
        if m is None or m.times.size == 0:
            return None
        return m.times, m.hr

    def _next_target(self, after: float):
        m: HRModel = self._model  # type: ignore[assignment]
        return m.events.next_abnormal(after) if (m and m.events is not None) else None

    def _prev_target(self, before: float):
        m: HRModel = self._model  # type: ignore[assignment]
        return m.events.prev_abnormal(before) if (m and m.events is not None) else None

    def _draw_main(self) -> None:
        m: HRModel = self._model  # type: ignore[assignment]
        ax = self.ax_main
        assert ax is not None and m is not None
        ax.clear()

        if m.times.size == 0:
            style_axis_clean(ax, show_y=True)
            ax.set_ylabel("Heart rate (bpm)")
            return

        x0, x1 = m.window.x_min, m.window.x_max
        mask = (m.times >= x0) & (m.times <= x1)
        t, hr = m.times[mask], m.hr[mask]

        if t.size:
            ax.plot(t, hr, color=_C_HR, linewidth=1.5, alpha=1.0, zorder=2)

        style_axis_clean(ax, show_y=True)   # HR amplitude is meaningful
        self._set_time_axis(ax, x0, x1)
        ax.set_ylabel("Heart rate (bpm)")

        if hr.size:
            lo, hi = float(np.min(hr)), float(np.max(hr))
            pad = max(2.0, 0.1 * (hi - lo))
            ax.set_ylim(lo - pad, hi + pad)
