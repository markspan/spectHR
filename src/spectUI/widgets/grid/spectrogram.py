# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Spectrogram docks: :class:`SpectrogramPlotWidget` (2-D heat map) and
:class:`Spectrogram3DPlotWidget` (interactive 3-D surface).

Both show the per-epoch sliding-window PSD grid (:func:`fetch_spectrogram`):
time on x, frequency on y, power as colour (2-D) or height (3-D).  When a
respiration channel is loaded the per-window breathing frequency is overlaid
(green dashed) so the user can see the HF peak track the breathing rate, as in
V2.  Window/step, colormap and the overlay toggle come from the workspace;
the widgets only draw.
"""
from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure

# Registers the "3d" projection as a side effect of import.
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from spectHR.analysis.spectrogram import fetch_spectrogram
from spectHR.session import Session
from spectUI.widgets._spectrogram_compute import (
    MAX_SURFACE_BINS,
    downsample_for_surface,
    epoch_relative_times,
    normalise_grid,
)
from spectUI.widgets.grid.base import EpochGridView

_C_RESP = "#1a9850"   # breathing-frequency overlay (green)


class _SpectrogramBase(EpochGridView):
    """Shared settings + per-epoch compute for the 2-D and 3-D spectrograms."""

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


class SpectrogramPlotWidget(_SpectrogramBase):
    """Per-epoch HRV spectrograms (2-D heat map)."""

    DOCK_NAME = "spectrogram"

    def _render_tile(self, fig: Figure, label: str, result) -> None:
        ax = fig.add_subplot(111)
        if result.error or result.power_grid.size == 0:
            ax.text(0.5, 0.5, f"{label}\n{result.error or 'no data'}",
                    ha="center", va="center", transform=ax.transAxes,
                    fontsize=8, color="#999")
            ax.set_xticks([]); ax.set_yticks([])
            return

        # Epoch-relative time on x, frequency on y, power as colour.
        t = epoch_relative_times(result)
        ax.pcolormesh(t, result.freqs, result.power_grid,
                      cmap=self._ss["colormap"], shading="nearest")

        # Breathing-frequency overlay (per-window), V2-style.
        if self._ss.get("show_respiration_overlay", True) and result.resp_freqs is not None:
            rf = np.asarray(result.resp_freqs).ravel()
            if rf.size == t.size and np.any(np.isfinite(rf)):
                ax.plot(t, rf, color=_C_RESP, ls="--", lw=1.3, alpha=0.85,
                        label="breath. freq.")
                ax.legend(fontsize=6, loc="upper right", framealpha=0.6)

        ax.set_title(label, fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("Hz", fontsize=8)
        ax.tick_params(labelsize=7)
        fig.tight_layout()


class Spectrogram3DPlotWidget(_SpectrogramBase):
    """Per-epoch HRV spectrograms as 3-D surfaces (V2)."""

    DOCK_NAME = "spectrogram3d"
    #: 3-D surfaces need room — one full-width tile per row (twice as wide).
    MAX_COLUMNS = 1

    def _render_tile(self, fig: Figure, label: str, result) -> None:
        ax = fig.add_subplot(111, projection="3d")
        if result.error or result.power_grid.size == 0:
            ax.text2D(0.5, 0.5, f"{label}\n{result.error or 'no data'}",
                      ha="center", va="center", transform=ax.transAxes,
                      fontsize=8, color="#999")
            return

        # Normalise to [0, 1] per epoch, then downsample so the surface stays
        # inside the polygon budget (MAX_SURFACE_BINS per axis).
        norm = normalise_grid(result.power_grid)
        t_rel = epoch_relative_times(result)
        ds_grid, ds_freqs, ds_t = downsample_for_surface(norm, result.freqs, t_rel)
        T, F = np.meshgrid(ds_t, ds_freqs)
        Z = np.where(np.isfinite(ds_grid), ds_grid, 0.0)

        ax.plot_surface(T, F, Z, cmap=self._ss["colormap"], vmin=0.0, vmax=1.0,
                        rstride=1, cstride=1, linewidth=0, antialiased=True,
                        alpha=0.9)
        ax.set_title(label, fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=7, labelpad=2)
        ax.set_ylabel("Hz", fontsize=7, labelpad=2)
        ax.set_zlabel("norm. power", fontsize=7, labelpad=2)
        ax.set_zlim(0.0, 1.0)
        ax.view_init(elev=35.0, azim=-60.0)
        ax.tick_params(labelsize=6)

        # Breathing-frequency overlay along the z = 0 floor.
        if self._ss.get("show_respiration_overlay", True) and result.resp_freqs is not None:
            rf = np.asarray(result.resp_freqs).ravel()
            stride = max(1, len(t_rel) // MAX_SURFACE_BINS)
            rf_ds = rf[::stride]
            if rf_ds.size == ds_t.size and np.any(np.isfinite(rf_ds)):
                rf_clean = np.where(np.isfinite(rf_ds), rf_ds, 0.0)
                ax.plot(ds_t, rf_clean, np.zeros_like(rf_clean),
                        color=_C_RESP, ls="--", lw=1.5, alpha=0.8,
                        label="breath. freq.")
                ax.legend(fontsize=6, loc="upper right")
