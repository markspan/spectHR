# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`SpectrogramPlotWidget` — per-epoch HRV spectrogram dock.

One tile per active epoch showing the sliding-window PSD grid
(:func:`fetch_spectrogram`).  Window/step and colormap come from the
workspace.  ``fetch_spectrogram`` never raises — failures arrive as a
``SpectrogramData`` with ``error`` set, which the tile renders as a label.
"""
from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure

from spectHR.analysis.spectrogram import fetch_spectrogram
from spectHR.session import Session
from spectUI.widgets.grid.base import EpochGridView


class SpectrogramPlotWidget(EpochGridView):
    """Per-epoch HRV spectrograms."""

    DOCK_NAME = "spectrogram"

    def _resolve(self, config) -> None:
        view = self._view(config)
        self._psd_method = view.psd_method
        self._ss = view.spectrogram_settings

    def _compute_epoch(self, events, scoped: Session):
        return fetch_spectrogram(
            events, "epoch",
            window_s=self._ss["window_s"],
            step_s=self._ss["step_s"],
            psd_method=self._psd_method,
            adaptive_source=self._ss["adaptive_source"],
        )

    def _render_tile(self, fig: Figure, label: str, result) -> None:
        ax = fig.add_subplot(111)
        if result.error or result.power_grid.size == 0:
            ax.text(0.5, 0.5, f"{label}\n{result.error or 'no data'}",
                    ha="center", va="center", transform=ax.transAxes,
                    fontsize=8, color="#999")
            ax.set_xticks([]); ax.set_yticks([])
            return

        # Epoch-relative time on x, frequency on y, power as colour.
        t0 = float(result.timestamps[0]) - result.window_s / 2.0
        t = result.timestamps - t0
        ax.pcolormesh(t, result.freqs, result.power_grid,
                      cmap=self._ss["colormap"], shading="nearest")
        ax.set_title(label, fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("Hz", fontsize=8)
        ax.tick_params(labelsize=7)
        fig.tight_layout()
