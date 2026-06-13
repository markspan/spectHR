# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`ProfilePlotWidget` — per-epoch band-power profile dock.

One tile per active epoch showing the sliding-window band-power profile
(:func:`compute_band_power_profile`), one coloured line per frequency band.
A row of band checkboxes (like the Poincaré epoch selector) picks which bands
are drawn; toggling re-renders the tiles without recomputing.  Window/step,
adaptive source and the PSD method come from the workspace; the widget
computes nothing.
"""
from __future__ import annotations

from matplotlib.figure import Figure

from spectHR.analysis.profile import compute_band_power_profile
from spectHR.session import Session
from spectUI.common.spectral_plots import band_color, strip_per_hz
from spectUI.widgets.grid.band_select import BandSelectorMixin
from spectUI.widgets.grid.base import EpochGridView


class ProfilePlotWidget(BandSelectorMixin, EpochGridView):
    """Per-epoch sliding-window band-power profiles with band selection."""

    DOCK_NAME = "profiles"
    Y_ZOOM = True

    def _build_toolbar(self) -> None:
        self._build_band_selector()

    def _resolve(self, config) -> None:
        view = self._view(config)
        self._psd_method = view.psd_method
        self._ps = view.profile_settings
        self._bands = view.display_bands
        self._refresh_band_selector(self._bands)

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
        # Epoch-relative time so every tile starts at 0.
        t = result.timestamps - (float(result.timestamps[0]) if result.timestamps.size else 0.0)
        drawn = 0
        for i, name in enumerate(result.band_names):
            if not self._band_selected(name):
                continue
            ax.plot(t, result.band_power[i], linewidth=1.2,
                    color=band_color(self._bands, name), label=name)
            drawn += 1
        ax.set_title(label, fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel(strip_per_hz(result.unit) or "power", fontsize=8)
        ax.set_ylim(bottom=0.0)
        ax.tick_params(labelsize=7)
        if drawn:
            ax.legend(fontsize=6, loc="upper right", framealpha=0.6)
        fig.tight_layout()
