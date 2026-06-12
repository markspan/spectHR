# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`ProfilePlotWidget` — per-epoch band-power profile dock.

One tile per active epoch showing the sliding-window band-power profile
(:func:`compute_band_power_profile`).  Window/step, adaptive source and the
PSD method come from the workspace; the widget computes nothing.
"""
from __future__ import annotations

from matplotlib.figure import Figure

from spectHR.analysis.profile import compute_band_power_profile
from spectHR.session import Session
from spectUI.widgets.grid.base import EpochGridView


class ProfilePlotWidget(EpochGridView):
    """Per-epoch sliding-window band-power profiles."""

    DOCK_NAME = "profiles"

    def _resolve(self, config) -> None:
        view = self._view(config)
        self._psd_method = view.psd_method
        self._ps = view.profile_settings

    def _compute_epoch(self, events, scoped: Session):
        return compute_band_power_profile(
            events,
            window_s=self._ps["window_s"],
            step_s=self._ps["step_s"],
            psd_method=self._psd_method,
            rsp_phases=scoped.intervals.get("breath"),
            adaptive_source=self._ps["adaptive_source"],
            smooth_breath_freq=self._ps["smooth_breath_freq"],
        )

    def _render_tile(self, fig: Figure, label: str, result) -> None:
        ax = fig.add_subplot(111)
        t = result.timestamps
        for i, name in enumerate(result.band_names):
            ax.plot(t, result.band_power[i], linewidth=1.0, label=name)
        ax.set_title(label, fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel(result.unit or "power", fontsize=8)
        ax.tick_params(labelsize=7)
        if result.band_names:
            ax.legend(fontsize=6, loc="upper right")
        fig.tight_layout()
