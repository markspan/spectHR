# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`PSDPlotWidget` — per-epoch power-spectral-density dock.

One tile per active epoch, each the IBI power spectrum
(:meth:`PSDEngine.compute`) with the configured frequency bands shaded.  The
PSD method (algorithm, band table, options) and the display bands come
straight from the workspace, so every PSD setting is honoured; the widget
computes nothing itself.
"""
from __future__ import annotations

import math

from matplotlib.figure import Figure

from spectHR.analysis.psd import PSDResult, PsdMethod
from spectHR.analysis.psd._engine import PSDEngine
from spectHR.session import Session
from spectUI.common.spectral_plots import draw_psd_tile
from spectUI.widgets.grid.base import EpochGridView


class PSDPlotWidget(EpochGridView):
    """Per-epoch IBI PSD grid (V2-style: CI shading + band fills + units)."""

    DOCK_NAME = "psd"
    #: Up/Down arrows zoom the (shared) power y-axis.
    Y_ZOOM = True
    #: A-series landscape tiles (height = width / √2), scroll when they overflow.
    TILE_ASPECT = 1.0 / math.sqrt(2.0)

    def _resolve(self, config) -> None:
        """Resolve the PSD method, display bands and CI alpha (main thread)."""
        view = self._view(config)
        self._method: PsdMethod = view.psd_method
        self._bands: dict = view.display_bands
        self._ci_alpha: float = view.psd_ci_alpha
        # CARSPAN carries a plot-only 3-point display smoother (V2's
        # PSDPlotWidget._wants_smoothing); Welch / Lomb-Scargle never smooth.
        self._smooth: bool = (
            self._method.algorithm in ("carspan", "carspan_strict")
            and bool(self._method.carspan.smooth_for_display)
        )

    def _compute_epoch(self, events, scoped: Session) -> PSDResult:
        # Pool thread; PSDEngine + numpy are GIL-safe.  with_ci=True so the
        # tile can shade the confidence interval like V2.
        return PSDEngine(events).compute(self._method, with_ci=True)

    def _render_tile(self, fig: Figure, label: str, result: PSDResult) -> None:
        ax = fig.add_subplot(111)
        draw_psd_tile(ax, result, self._bands, ci_alpha=self._ci_alpha,
                      smooth=self._smooth)
        ax.set_title(label, fontsize=9)
        ax.tick_params(labelsize=7)
        fig.tight_layout()
