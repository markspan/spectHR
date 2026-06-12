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

from matplotlib.figure import Figure

from spectHR.analysis.transfer import compute_transfer, compute_transfer_profile
from spectHR.session import Session
from spectUI.common.spectral_plots import band_color, draw_band_fills
from spectUI.widgets.grid.base import EpochGridView

_C_MOD = "#2c3e50"      # modulus line
_C_PHASE = "#8e44ad"    # phase
_C_COH = "#16a085"      # coherence


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
        # V2 Bode triple: |H| (with PSD-style band fills) / phase / coherence,
        # sharing the frequency x-axis.
        gs = fig.add_gridspec(3, 1, hspace=0.12, height_ratios=[2, 1, 1])
        ax_m = fig.add_subplot(gs[0])
        ax_p = fig.add_subplot(gs[1], sharex=ax_m)
        ax_c = fig.add_subplot(gs[2], sharex=ax_m)
        f = result.freqs

        draw_band_fills(ax_m, f, result.modulus, self._display_bands)
        ax_m.plot(f, result.modulus, "k", linewidth=1.0, zorder=3)
        ax_m.set_ylabel("|H|", fontsize=7)
        ax_m.set_ylim(bottom=0.0)
        ax_m.set_title(label, fontsize=9)
        ax_m.legend(fontsize=5, loc="upper right", framealpha=0.5)

        ax_p.plot(f, result.phase_wrapped, color=_C_PHASE, linewidth=0.8)
        ax_p.set_ylabel("∠H", fontsize=7)

        ax_c.plot(f, result.coherence, color=_C_COH, linewidth=0.8)
        ax_c.axhline(self._ts["min_coherence"], ls=":", color="#999", linewidth=0.8)
        ax_c.set_ylim(0.0, 1.0)
        ax_c.set_ylabel("coh", fontsize=7)
        ax_c.set_xlabel("Frequency (Hz)", fontsize=7)

        for ax in (ax_m, ax_p):
            ax.tick_params(labelbottom=False, labelsize=6)
        ax_c.tick_params(labelsize=6)
        ax_m.set_xlim(0.0, self._ts["f_max"])


class TransferProfilePlotWidget(_TransferBase):
    """Per-epoch transfer modulus per band over time."""

    DOCK_NAME = "transferprofile"

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
            ax.plot(result.timestamps, result.modulus[i], linewidth=1.0, label=name)
        ax.set_title(label, fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("|H|", fontsize=8)
        ax.tick_params(labelsize=7)
        if result.band_names:
            ax.legend(fontsize=6, loc="upper right")
        fig.tight_layout()
