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

from matplotlib.figure import Figure

from spectHR.analysis.psd import PSDResult, PsdMethod
from spectHR.analysis.psd._engine import PSDEngine
from spectHR.config import WorkspaceView
from spectHR.session import Session
from spectUI.widgets.grid.base import EpochGridView


class PSDPlotWidget(EpochGridView):
    """Per-epoch IBI PSD grid."""

    DOCK_NAME = "psd"

    def _resolve(self, config) -> None:
        """Resolve the PSD method and display bands on the main thread."""
        view = config if isinstance(config, WorkspaceView) else WorkspaceView(
            config if isinstance(config, dict) else None
        )
        self._method: PsdMethod = view.psd_method
        self._bands: dict = view.display_bands

    def _compute_epoch(self, events, scoped: Session) -> PSDResult:
        # Runs on a pool thread; PSDEngine + numpy are GIL-safe.  ``_method``
        # was resolved on the main thread in _resolve, so no Qt/cache races.
        return PSDEngine(events).compute(self._method, with_ci=False)

    def _render_tile(self, fig: Figure, label: str, result: PSDResult) -> None:
        ax = fig.add_subplot(111)

        # Shade the configured bands behind the spectrum.
        for name, spec in self._bands.items():
            try:
                low, high = float(spec["low"]), float(spec["high"])
            except (KeyError, TypeError, ValueError):
                continue
            ax.axvspan(low, high, color=spec.get("color", "gray"),
                       alpha=float(spec.get("alpha", 0.15)), linewidth=0, zorder=1)

        ax.plot(result.freqs, result.power, color="#2c3e50", linewidth=1.0, zorder=2)
        if result.freqs.size:
            ax.set_xlim(float(result.freqs[0]), float(result.freqs[-1]))
        ax.set_title(label, fontsize=9)
        ax.set_xlabel("Frequency (Hz)", fontsize=8)
        ax.set_ylabel(result.unit or "power", fontsize=8)
        ax.tick_params(labelsize=7)
        fig.tight_layout()
