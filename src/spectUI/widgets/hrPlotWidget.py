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
        # RSA per-breath overlay axis (second twinx); rebuilt on each redraw.
        self._ax_rsa_twin: Axes | None = None

        self.workspace = None

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
        style_axis_clean(self.ax_main, show_y=True)
        self._set_time_axis(
            self.ax_main,
            self.data.view.x_min,
            self.data.view.x_max,
            show_xlabel=False,
        )

    def _draw_extras(self) -> None:
        self._draw_breathing()
        self._draw_rsa_overlay()

    # ==============================================================
    # Public API
    # ==============================================================

    def hrPlot(
        self,
        data: PhysioData,
        fig: Figure | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
        workspace=None,
    ) -> Figure:
        """Initialise and display the heart-rate plot for *data*."""
        self.workspace = workspace
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

        # X-coordinates: the R-peak time itself. ``ibi[i] = times[i+1] -
        # times[i]`` is the interval *opening* at R-peak ``i``, so its HR
        # value sits exactly on that R-top - the same absolute time axis the
        # Preprocessing and Blood-pressure timelines use, so the three views
        # line up beat-for-beat. (The final beat has no forward interval, so
        # its HR is NaN and simply isn't drawn.)
        return TimeSeries(times, hr)

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
        """Return the breathing TimeSeries for the active band, else None."""
        assert self.data is not None
        try:
            return self.data["rsp"].timeseries
        except (KeyError, AttributeError, TypeError):
            pass
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
        Draw INH/EXH phase shading and optional breathing waveform overlay.

        Phase shading is drawn whenever respiration phases are available,
        regardless of whether a raw breathing waveform exists.  The waveform
        overlay (green line on a twinx) is only added when the timeseries is
        present.
        """
        assert self.ax_main is not None
        assert self.data is not None and self.data.view is not None

        # Remove old twin axis to avoid stacking
        if self._ax_br_twin is not None:
            try:
                self._ax_br_twin.remove()
            except Exception:
                pass
            self._ax_br_twin = None

        # Phase shading on the primary axis regardless of waveform availability.
        if self._has_resp_phases():
            self._draw_phase_backgrounds(
                self.ax_main,
                phase_prefix="inh",
                color="#ADD8E6",
                alpha=0.25,
            )

        ts = self.breathing_series
        if ts is None:
            return

        ax_hr = self.ax_main
        self._ax_br_twin = ax_hr.twinx()

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
        self._ax_br_twin.set_ylabel("Breathing", color="green", fontsize=8)

        # Keep behind the HR trace
        self._ax_br_twin.set_zorder(0)
        style_axis_clean(self._ax_br_twin)  # removes top/left/right spines
        self._ax_br_twin.set_xlabel("")

    def _rsa_overlay_enabled(self) -> bool:
        ra = ((self.workspace or {}).get("RespirationAnalysis") or {})
        return bool(ra.get("rsa_overlay", True))

    def _draw_rsa_overlay(self) -> None:
        """
        Draw per-breath RSA and RSA0 as scatter points on a right y-axis.

        Each point is positioned at the midpoint of its INH→EXH cycle pair.
        Filled circles = RSA (valid breaths only); hollow circles = RSA0
        (invalid breaths zeroed).  A thin connecting line through RSA0 shows
        the trend.
        """
        # Clean up previous overlay axis unconditionally so a disabled
        # setting also removes a stale axis from the last redraw.
        if self._ax_rsa_twin is not None:
            try:
                self._ax_rsa_twin.remove()
            except Exception:
                pass
            self._ax_rsa_twin = None

        if not self._rsa_overlay_enabled():
            return
        if self.data is None or self.data.view is None:
            return

        active_band = getattr(self.data, "active_band", None)
        rsp_series = getattr(self.data, "rsp_map", {}).get(active_band)
        if rsp_series is None:
            return

        hrv = self.data.hrv
        if hrv is None:
            return

        x_min, x_max = self.data.view.x_min, self.data.view.x_max
        rsp_phases = rsp_series.view(x_min, x_max)
        if len(rsp_phases) < 2:
            return

        try:
            from spectHR.analysis.bp_metrics import grossman_rsa_per_breath
            lag_s = float(
                ((self.workspace or {}).get("RespirationAnalysis") or {})
                .get("rsa_lag_s", 1.0)
            )
            rsa_values = grossman_rsa_per_breath(
                np.asarray(hrv.times,  dtype=float),
                np.asarray(hrv.labels, dtype=object),
                rsp_phases,
                lag_s=lag_s,
            )
        except Exception:
            return

        if rsa_values.size == 0:
            return

        # Build per-breath (x, rsa, rsa0) arrays.
        p_starts = np.asarray(rsp_phases.starts, dtype=float)
        p_ends   = np.asarray(rsp_phases.ends,   dtype=float)
        p_labels = np.asarray(rsp_phases.labels, dtype=object)

        x_pts, rsa_pts, rsa0_pts = [], [], []
        pair_idx = 0
        for i in range(len(p_starts) - 1):
            if p_labels[i] == "INH" and p_labels[i + 1] == "EXH":
                if pair_idx < rsa_values.size:
                    v = float(rsa_values[pair_idx])
                    x_pts.append((p_starts[i] + p_ends[i + 1]) / 2.0)
                    rsa_pts.append(v if np.isfinite(v) else np.nan)
                    rsa0_pts.append(v if (np.isfinite(v) and v >= 0) else 0.0)
                pair_idx += 1

        if not x_pts:
            return

        x_arr    = np.array(x_pts)
        rsa_arr  = np.array(rsa_pts)
        rsa0_arr = np.array(rsa0_pts)

        self._ax_rsa_twin = self.ax_main.twinx()
        ax_r = self._ax_rsa_twin

        # Trend line + hollow markers for RSA0 (all cycles, invalid → 0)
        ax_r.plot(x_arr, rsa0_arr,
                  color="darkorange", linewidth=0.8, alpha=0.4, zorder=3)
        ax_r.scatter(x_arr, rsa0_arr, s=20,
                     facecolors="none", edgecolors="darkorange", alpha=0.7,
                     zorder=4)

        # Filled markers for RSA (valid cycles only)
        valid = np.isfinite(rsa_arr)
        if np.any(valid):
            ax_r.scatter(x_arr[valid], rsa_arr[valid], s=35,
                         color="darkorange", zorder=5)

        ax_r.set_xlim(x_min, x_max)
        ax_r.set_ylabel("RSA (ms)", color="darkorange", fontsize=8)
        ax_r.tick_params(axis="y", colors="darkorange", labelsize=8)
        ax_r.spines["right"].set_visible(True)
        ax_r.spines["right"].set_color("darkorange")
        ax_r.spines["right"].set_alpha(0.6)
        for spine in ("top", "left", "bottom"):
            ax_r.spines[spine].set_visible(False)
        ax_r.set_xlabel("")

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
