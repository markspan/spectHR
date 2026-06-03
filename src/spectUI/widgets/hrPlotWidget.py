# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectUI.common import (
    TimelinePlotWidget,
    make_nav_button,
    style_axis_clean,
)

# ======================================================================
# HRPlotWidget (UI + plotting)
# ======================================================================


class HRPlotWidget(TimelinePlotWidget):
    """
    Interactive heart-rate (IBI) timeseries widget.

    A :class:`~spectUI.common.TimelinePlotWidget` whose primary series is
    a heart-rate trace derived from the active CardioSeries. Adds two
    things on top of the shared scaffolding:

    - an optional breathing overlay on a twinned y-axis, and
    - two extra navigation buttons that jump to the previous / next
      non-normal R-top.

    It operates on a PhysioData instance with:
        - data.hrv  -> CardioSeries (R-peak times, IBIs, labels)
        - optionally a "RSP..." breathing TimeSeries.
    """

    overview_color = "green"

    # --------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Breathing overlay axis (twinx); rebuilt on each redraw.
        self._ax_br_twin: Axes | None = None

        # Not used by this widget directly; present so the next/prev
        # guards have something to test. Wired by the preprocessing flow.
        self.rtop_ctrl = None

        # R-top color mapping (kept for parity with the preprocessing view).
        self.RTopColors = {
            "N": "blue",
            "L": "cyan",
            "S": "magenta",
            "TL": "orange",
            "SL": "turquoise",
            "SNS": "lightseagreen",
        }

    # ==============================================================
    # TimelinePlotWidget hooks
    # ==============================================================

    def _nav_buttons(self):
        """Standard nav set plus prev/next non-normal R-top jumps."""
        return (
            make_nav_button("fa6s.right-to-bracket", self.go_to_start, rotate=180, tooltip="Goto Start"),
            make_nav_button("fa6s.backward",          self.pan_left,               tooltip="Pan Left"),
            make_nav_button("fa6s.square-caret-left", self.prev,                   tooltip="Previous non-normal R-top"),
            make_nav_button("ei.zoom-in",             self.zoom_in,                tooltip="Zoom In"),
            make_nav_button("ei.zoom-out",            self.zoom_out,               tooltip="Zoom Out"),
            make_nav_button("fa6s.square-caret-right",self.next,                   tooltip="Next non-normal R-top"),
            make_nav_button("fa6s.forward",           self.pan_right,              tooltip="Pan Right"),
            make_nav_button("fa6s.right-to-bracket",  self.go_to_end,              tooltip="Goto End"),
        )

    def _prepare(self) -> None:
        """Derive the heart-rate series and stash it on the dataset."""
        assert self.data is not None
        hr_ts = self.hr_from_hrvseries(self.data.hrv)
        self.data.timeseries["heartrate"] = hr_ts

    def _primary_series(self) -> TimeSeries:
        assert self.data is not None
        return self.data["heartrate"].timeseries

    def _draw_main(self) -> None:
        """Draw the heart-rate signal in the main axis."""
        assert self.ax_main is not None
        assert self.data is not None and self.data.view is not None
        heartrate = self.data["heartrate"].timeseries

        self.ax_main.clear()
        self.ax_main.plot(
            heartrate.times, heartrate.values, color="red", linewidth=2, alpha=1.0
        )
        self.ax_main.set_title("Heart Rate Timeseries")
        self.ax_main.set_ylabel("Heart rate (bpm)")
        style_axis_clean(self.ax_main)
        self._set_time_axis(
            self.ax_main,
            self.data.view.x_min,
            self.data.view.x_max,
            show_xlabel=False,
        )

    def _draw_extras(self) -> None:
        self._draw_breathing()

    # ==============================================================
    # Public API
    # ==============================================================

    def hrPlot(
        self,
        data: PhysioData,
        fig: Figure | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
    ) -> Figure:
        """Initialise and display the heart-rate plot for *data*."""
        return self._plot(data, fig, x_min, x_max)

    # ==============================================================
    # HR-specific helpers
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
    def breathing_series(self) -> TimeSeries | None:
        """
        Return the first breathing TimeSeries if present, otherwise None.
        """
        assert self.data is not None
        for name, ts in self.data.timeseries.items():
            if name.startswith("RSP"):
                return ts
        return None

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

    def _draw_breathing(self) -> None:
        """
        Draw breathing signal as a twin y-axis overlay on the main axis.

        Behavior
        --------
        - If no breathing series exists, remove any previous twin axis and return.
        - Otherwise, rebuild the twin axis on each redraw (robust).
        """
        assert self.ax_main is not None
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

        ax_hr = self.ax_main
        self._ax_br_twin = ax_hr.twinx()

        # Optional: phase shading on the HR axis
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
        style_axis_clean(self._ax_br_twin)  # removes top/left/right spines too
        self._ax_br_twin.set_xlabel("")

    # ==============================================================
    # R-top jump navigation
    # ==============================================================

    def next(self) -> None:
        """
        Jump to next non-normal R-top (label != 'N') after current x_max.
        """
        if self.rtop_ctrl is None or self.data is None or self.data.view is None:
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
        if self.rtop_ctrl is None or self.data is None or self.data.view is None:
            return
        t = self.rtop_ctrl.prev_non_normal(self.data.view.x_min)
        if t is None:
            return
        width = self.data.view.width()
        self._set_window(t - 0.5 * width, t + 0.5 * width)
