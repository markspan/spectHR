# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Transfer-function docks: :class:`TransferPlotWidget` and
:class:`TransferProfilePlotWidget`.

Both compute an input→HR transfer function per epoch (input = respiration or
blood pressure, selectable in the workspace).  ``TransferPlotWidget`` shows
the spectrum (``|H|`` + coherence vs frequency); ``TransferProfilePlotWidget``
shows the per-band modulus over time.  All settings come from the workspace's
``TransferAnalysis`` chapter and the band table; the widgets only draw.
"""
from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure

from spectHR.analysis.transfer import (
    compute_transfer,
    compute_transfer_profile,
    modulus_unit,
)
from spectHR.session import Session
from spectUI.common.spectral_plots import band_color, draw_band_fills
from spectUI.widgets.grid.base import EpochGridView


def _shade_bands(ax, bands: dict) -> None:
    """Vertical band shading (V2 ``axvspan``) across a Bode sub-panel."""
    for name, spec in bands.items():
        if name == "FullRange" or "low" not in spec or "high" not in spec:
            continue
        lo, hi = float(spec["low"]), float(spec["high"])
        if hi <= lo:
            continue
        ax.axvspan(lo, hi, color=spec.get("color", "gray"),
                   alpha=float(spec.get("alpha", 0.18)), zorder=0)


class _TransferBase(EpochGridView):
    """Shared settings resolution and input-channel selection."""

    def _resolve(self, config) -> None:
        view = self._view(config)
        self._ts = view.transfer_settings
        self._display_bands = view.display_bands     # {name: {low, high, color}}
        self._bands = {
            name: (float(s["low"]), float(s["high"]))
            for name, s in self._display_bands.items()
            if "low" in s and "high" in s
        }

    def _input_series(self, scoped: Session):
        """Resolve the configured input channel (respiration or BP)."""
        sig = self._ts["input_signal"].lower()
        if sig.startswith(("rsp", "resp")):
            return scoped.resp
        if sig.startswith("bp"):
            return scoped.bp
        return scoped.resp or scoped.bp


class TransferPlotWidget(_TransferBase):
    """Per-epoch input→HR transfer spectrum (|H| and coherence)."""

    DOCK_NAME = "transfer"
    #: The modulus panel carries a linkable / zoomable magnitude y-axis.
    Y_ZOOM = True

    def _compute_epoch(self, events, scoped: Session):
        inp = self._input_series(scoped)
        if inp is None:
            raise ValueError(f"no '{self._ts['input_signal']}' channel")
        return compute_transfer(
            events, inp,
            input_signal=self._ts["input_signal"],
            bands=self._bands,
            min_coherence=self._ts["min_coherence"],
            smooth=self._ts["smooth"],
            f_max=self._ts["f_max"],
        )

    def _render_tile(self, fig: Figure, label: str, result) -> None:
        # V2 Bode triple: |H| (PSD-style under-curve band fills) / phase /
        # coherence, sharing the frequency x-axis.  The phase and coherence
        # panels carry vertical band shading; the phase axis reads in π.
        gs = fig.add_gridspec(3, 1, hspace=0.12, height_ratios=[3, 2, 2])
        ax_m = fig.add_subplot(gs[0])
        ax_p = fig.add_subplot(gs[1], sharex=ax_m)
        ax_c = fig.add_subplot(gs[2], sharex=ax_m)
        f = result.freqs
        f_min, f_max = float(self._ts["f_min"]), float(self._ts["f_max"])
        min_coh = float(self._ts["min_coherence"])

        # ---- modulus: black line + under-curve band fills ----------------
        draw_band_fills(ax_m, f, result.modulus, self._display_bands)
        ax_m.plot(f, result.modulus, "k", linewidth=1.0, alpha=0.85, zorder=3)
        unit = modulus_unit(self._ts["input_signal"])
        ax_m.set_ylabel(f"|H| [{unit}]" if unit else "|H|", fontsize=7)
        ax_m.set_ylim(bottom=0.0)
        ax_m.set_title(label, fontsize=9)
        ax_m.legend(fontsize=5, loc="upper right", framealpha=0.5)

        # ---- phase: points gated by coherence, y-axis in π ---------------
        _shade_bands(ax_p, self._display_bands)
        wrapped = self._ts.get("phase_view", "wrapped") != "unwrapped"
        phase = result.phase_wrapped if wrapped else result.phase_unwrapped
        coh = np.asarray(result.coherence)
        coherent = coh >= min_coh
        ax_p.plot(f[coherent], phase[coherent], ".", color="black",
                  markersize=3, zorder=3)
        mask_alpha = float(self._ts.get("coherence_mask_alpha", 0.2))
        if mask_alpha > 0.0 and (~coherent).any():
            ax_p.plot(f[~coherent], phase[~coherent], ".", color="black",
                      markersize=3, alpha=mask_alpha, zorder=2)
        ax_p.axhline(0.0, color="dimgray", lw=0.6, zorder=1)
        if wrapped:
            ax_p.set_ylim(-np.pi - 0.2, np.pi + 0.2)
            ax_p.set_yticks([-np.pi, -np.pi / 2, 0.0, np.pi / 2, np.pi])
            ax_p.set_yticklabels(
                [r"$-\pi$", r"$-\pi/2$", "0", r"$\pi/2$", r"$\pi$"], fontsize=7)
        ax_p.set_ylabel("∠H [rad]", fontsize=7)

        # ---- coherence: line + threshold + band shading ------------------
        _shade_bands(ax_c, self._display_bands)
        ax_c.plot(f, coh, color="black", linewidth=1.0, zorder=3)
        if self._ts.get("show_coherence_threshold", True):
            ax_c.axhline(min_coh, ls="--", color="red", linewidth=1.0,
                         alpha=0.7, zorder=2)
        ax_c.set_ylim(0.0, 1.05)
        ax_c.set_yticks([0.0, 0.5, 1.0])
        ax_c.set_ylabel(r"$|C(f)|^2$", fontsize=7)
        ax_c.set_xlabel("Frequency (Hz)", fontsize=7)

        for ax in (ax_m, ax_p, ax_c):
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
        for ax in (ax_m, ax_p):
            ax.tick_params(labelbottom=False, labelsize=6)
        ax_c.tick_params(labelsize=6)
        ax_m.set_xlim(f_min, f_max)


class TransferProfilePlotWidget(_TransferBase):
    """Per-epoch transfer modulus per band over time."""

    DOCK_NAME = "transferprofile"
    Y_ZOOM = True

    def _compute_epoch(self, events, scoped: Session):
        inp = self._input_series(scoped)
        if inp is None:
            raise ValueError(f"no '{self._ts['input_signal']}' channel")
        return compute_transfer_profile(
            events, inp,
            input_signal=self._ts["input_signal"],
            bands=self._bands,
            window_s=self._ts["window_s"],
            step_s=self._ts["step_s"],
            min_coherence=self._ts["min_coherence"],
            f_max=self._ts["f_max"],
        )

    def _render_tile(self, fig: Figure, label: str, result) -> None:
        ax = fig.add_subplot(111)
        for i, name in enumerate(result.band_names):
            ax.plot(result.timestamps, result.modulus[i], linewidth=1.0,
                    color=band_color(self._display_bands, name), label=name)
        ax.set_title(label, fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("|H|", fontsize=8)
        ax.tick_params(labelsize=7)
        if result.band_names:
            ax.legend(fontsize=6, loc="upper right")
        fig.tight_layout()
