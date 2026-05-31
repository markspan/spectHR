# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Per-epoch Bode-plot widget for the respiration -> HR transfer function.

Each tile holds three stacked subplots sharing the frequency x-axis:

    1. modulus  |H(f)|    linear y, PSD-style band fills under the curve.
    2. phase    /_H(f)    wrapped or unwrapped per Settings, points
                          below the coherence threshold are faded
                          via the coherence_mask_alpha setting.
    3. coherence |C(f)|^2 in [0, 1], optional horizontal threshold
                          line at coherence_threshold_level. Auto-
                          rescales when the peak is small so a flat-
                          near-zero line stays visible.

Frequency bands from FrequencyAnalysis.bands are shaded vertically
across the phase + coherence panels so the user can read structure
at a glance. The modulus panel uses PSD-style under-curve fills.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from spectHR.Tools.Logger import logger
from spectHR.analysis.transfer import (
    BandTransfer,
    TransferResult,
    compute_transfer,
)
from spectUI.common import (
    PlotExportMixin,
    YZoomMixin,
    Y_TOP_FLOOR,
    build_epoch_grid,
    wire_y_zoom_shortcuts,
)
from spectUI.workSpace import (
    display_bands_from_workspace,
    transfer_settings_from_workspace,
)


# ---------------------------------------------------------------------------
# Band-fill helpers (PSD-style under-curve shading for the modulus panel)
# ---------------------------------------------------------------------------


def _band_draw_extents(
    bands: dict[str, dict],
) -> dict[str, tuple[float, float]]:
    """Per-band ``(draw_low, draw_high)`` extending to neighbour midpoints.

    Mirrors the PSD widget's helper so the under-curve fills for adjacent
    bands meet visually even when the configured edges leave gaps
    (e.g. 0.06 -> 0.07, 0.14 -> 0.15). FullRange is skipped because the
    modulus panel doesn't fill it.
    """
    items = sorted(
        (
            (name, spec) for name, spec in bands.items()
            if name != "FullRange"
            and float(spec.get("high", 0.0)) > float(spec.get("low", 0.0))
        ),
        key=lambda kv: float(kv[1]["low"]),
    )
    extents: dict[str, tuple[float, float]] = {}
    for i, (name, spec) in enumerate(items):
        draw_low  = float(spec["low"])
        draw_high = float(spec["high"])
        if i > 0:
            draw_low = (float(items[i - 1][1]["high"]) + float(spec["low"])) / 2.0
        if i < len(items) - 1:
            draw_high = (float(spec["high"]) + float(items[i + 1][1]["low"])) / 2.0
        extents[name] = (draw_low, draw_high)
    return extents


def _draw_modulus_band_fill(
    ax,
    freqs: np.ndarray,
    modulus: np.ndarray,
    *,
    name: str,
    spec: dict,
    band_results: "dict[str, BandTransfer] | None",
    draw_low: float,
    draw_high: float,
) -> None:
    """Fill the area under the modulus curve for one band, PSD-style."""
    if freqs.size == 0 or modulus.size == 0:
        return

    fill_mask = (freqs >= draw_low) & (freqs <= draw_high)
    if not fill_mask.any():
        return
    p_lo = float(np.interp(draw_low,  freqs, modulus))
    p_hi = float(np.interp(draw_high, freqs, modulus))
    f_band = np.concatenate(([draw_low],  freqs[fill_mask], [draw_high]))
    m_band = np.concatenate(([p_lo],      modulus[fill_mask], [p_hi]))

    bt = (band_results or {}).get(name)
    if bt is not None and np.isfinite(getattr(bt, "modulus", float("nan"))):
        label = f"{name}: |H|={bt.modulus:.2f} (n={int(bt.n_coherent)})"
    else:
        label = f"{name}: n/a"

    colour = spec.get("color", "gray")
    alpha  = float(spec.get("alpha", 0.35))
    ax.fill_between(
        f_band, 0.0, m_band,
        color=colour, alpha=alpha,
        label=label, zorder=2,
    )


# ---------------------------------------------------------------------------
# Plot data
# ---------------------------------------------------------------------------


@dataclass
class _TransferPlotData:
    """Everything one tile needs to render its Bode triple."""

    label: str
    freqs: np.ndarray
    modulus: np.ndarray
    phase_wrapped: np.ndarray
    phase_unwrapped: np.ndarray
    coherence: np.ndarray
    freq_resolution: float
    method: str
    band_results: "dict[str, BandTransfer] | None"
    error: str | None = None


def _band_edges_for_transfer(
    workspace: dict[str, Any] | None,
) -> dict[str, tuple[float, float]]:
    """Return the band-edge dict that ``compute_transfer`` accepts.

    Filters FullRange because a 0.02 - 0.5 Hz integration adds a
    near-duplicate row that just clutters the band table.
    """
    bands = display_bands_from_workspace(workspace)
    return {
        name: (float(spec["low"]), float(spec["high"]))
        for name, spec in bands.items()
        if name != "FullRange" and "low" in spec and "high" in spec
    }


def _fetch_transfer(
    series,
    label: str,
    *,
    workspace: dict[str, Any] | None,
    min_coherence: float,
    f_max: float,
    smooth: bool = True,
) -> _TransferPlotData:
    """Compute a single-epoch TransferResult, never raises."""
    empty = _TransferPlotData(
        label=label,
        freqs=np.array([]),
        modulus=np.array([]),
        phase_wrapped=np.array([]),
        phase_unwrapped=np.array([]),
        coherence=np.array([]),
        freq_resolution=0.0,
        method="",
        band_results=None,
    )

    pd = getattr(series, "_pd", None)
    if pd is None:
        return _TransferPlotData(**{**empty.__dict__, "error": "No PhysioData"})
    # Continuous respiration TimeSeries lives at ``pd["rsp"].timeseries`` -
    # ``pd.rsp_map`` holds phase intervals (INH/EXH) and has no .times.
    try:
        rsp_for_transfer = pd["rsp"].timeseries
    except KeyError:
        return _TransferPlotData(
            **{**empty.__dict__, "error": "No respiration channel"}
        )

    try:
        result: TransferResult = compute_transfer(
            series,
            rsp_for_transfer,
            bands=_band_edges_for_transfer(workspace) or None,
            min_coherence=min_coherence,
            smooth=smooth,   # CARSPAN profile smoother default; toggleable via Settings.
            f_max=f_max,
        )
    except Exception as exc:
        logger.debug("compute_transfer failed for %s: %s", label, exc)
        return _TransferPlotData(
            **{**empty.__dict__, "error": f"Transfer failed: {exc}"}
        )

    # Diagnostic: max coherence so the user can tell at a glance whether
    # the panel is empty because values are tiny or because the trace
    # genuinely vanished.
    coh_arr = np.asarray(result.coherence)
    finite_coh = coh_arr[np.isfinite(coh_arr)]
    coh_peak = float(finite_coh.max()) if finite_coh.size else float("nan")
    coh_mean = float(finite_coh.mean()) if finite_coh.size else float("nan")
    logger.debug(
        "Transfer [%s]: coherence peak=%.4f mean=%.4f bins=%d",
        label, coh_peak, coh_mean, int(finite_coh.size),
    )

    return _TransferPlotData(
        label=label,
        freqs=result.freqs,
        modulus=result.modulus,
        phase_wrapped=result.phase_wrapped,
        phase_unwrapped=result.phase_unwrapped,
        coherence=coh_arr,
        freq_resolution=float(result.freq_resolution),
        method=result.method,
        band_results=result.band_results,
    )


# ---------------------------------------------------------------------------
# Per-epoch tile
# ---------------------------------------------------------------------------


class _SingleTransferPlot(QWidget):
    """Bode triple for one epoch."""

    def __init__(
        self,
        data: _TransferPlotData,
        parent: QWidget | None = None,
        *,
        bands: dict[str, dict] | None = None,
        phase_view: str = "wrapped",
        show_coherence_threshold: bool = True,
        coherence_threshold_level: float = 0.5,
        coherence_mask_alpha: float = 0.20,
        min_coherence: float = 0.5,
        f_min: float = 0.0,
        f_max: float = 0.5,
    ) -> None:
        super().__init__(parent)
        self.canvas: FigureCanvas = FigureCanvas(
            Figure(figsize=(5.5, 6.0), facecolor="white")
        )
        self.setStyleSheet("background-color: white;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(520)

        bands = bands or {}
        fig = self.canvas.figure

        if data.error is not None or data.freqs.size == 0:
            ax = fig.add_subplot(111)
            ax.text(
                0.5, 0.5, data.error or "No transfer data",
                ha="center", va="center",
                transform=ax.transAxes, color="gray",
            )
            ax.set_axis_off()
            self.canvas.draw()
            return

        gs = GridSpec(
            3, 1, figure=fig,
            height_ratios=[3, 2, 2],
            hspace=0.08,
        )
        ax_mod   = fig.add_subplot(gs[0, 0])
        ax_phase = fig.add_subplot(gs[1, 0], sharex=ax_mod)
        ax_coh   = fig.add_subplot(gs[2, 0], sharex=ax_mod)
        # YZoomMixin._set_y_top reads ``.ax`` on each subplot. Point it
        # at the top (modulus) panel - that's the "top panel" zoom the
        # user expects to control with Up / Down.
        self.ax = ax_mod

        TransferPlotWidget.plot_on_axes(
            ax_mod=ax_mod,
            ax_phase=ax_phase,
            ax_coh=ax_coh,
            data=data,
            bands=bands,
            phase_view=phase_view,
            show_coherence_threshold=show_coherence_threshold,
            coherence_threshold_level=coherence_threshold_level,
            coherence_mask_alpha=coherence_mask_alpha,
            min_coherence=min_coherence,
            f_min=f_min,
            f_max=f_max,
        )
        ax_mod.set_title(f"Transfer - {data.label}", fontsize=10)
        ax_mod.tick_params(labelbottom=False)
        ax_phase.tick_params(labelbottom=False)

        fig.subplots_adjust(
            left=0.10, right=0.98, top=0.94, bottom=0.08, hspace=0.08,
        )
        self.canvas.draw()


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------


class TransferPlotWidget(YZoomMixin, PlotExportMixin, QWidget):
    """Grid of Bode-plot tiles, one per active epoch."""

    _export_context = "Transfer"

    def __init__(
        self,
        series_list: list,
        labels: list[str],
        parent: QWidget | None = None,
        *,
        workspace: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)

        cfg = transfer_settings_from_workspace(workspace)
        bands_all = display_bands_from_workspace(workspace)
        # FullRange is always excluded from the per-epoch band table - a
        # 0.02 - 0.5 Hz fill / legend entry is a near-duplicate of the
        # underlying curve.
        bands = {n: s for n, s in bands_all.items() if n != "FullRange"}

        plots: list[_TransferPlotData] = [
            _fetch_transfer(
                series, label,
                workspace=workspace,
                min_coherence=float(cfg["min_coherence"]),
                f_max=float(cfg["f_max"]),
                smooth=bool(cfg["smooth"]),
            )
            for series, label in zip(series_list, labels)
        ]

        self._labels: list[str] = list(labels)
        self._series_list: list = list(series_list)
        self._workspace: dict[str, Any] | None = workspace

        # Initial shared y-max for the modulus panel: 10% headroom above
        # the largest finite modulus across all epochs, with a sane
        # fallback so the axis never collapses.
        peaks: list[float] = []
        for d in plots:
            m = np.asarray(d.modulus)
            if m.size:
                finite = m[np.isfinite(m)]
                if finite.size:
                    peaks.append(float(finite.max()))
        y_top = max(peaks) * 1.1 if peaks else 1.0
        self._y_top: float = max(y_top, Y_TOP_FLOOR)

        self._subplots: list[_SingleTransferPlot] = build_epoch_grid(
            self, plots,
            lambda data: _SingleTransferPlot(
                data,
                bands=bands,
                phase_view=str(cfg["phase_view"]),
                show_coherence_threshold=bool(cfg["show_coherence_threshold"]),
                coherence_threshold_level=float(cfg["coherence_threshold_level"]),
                coherence_mask_alpha=float(cfg["coherence_mask_alpha"]),
                min_coherence=float(cfg["min_coherence"]),
                f_min=float(cfg["f_min"]),
                f_max=float(cfg["f_max"]),
            ),
        )
        # Pin the initial modulus y-max across every tile so Up / Down
        # zoom feels uniform rather than per-tile autoscaled.
        for sp in self._subplots:
            sp.ax.set_ylim(bottom=0.0, top=self._y_top)
            sp.canvas.draw_idle()
        # Up / Down arrow shortcuts; build_epoch_grid already installs
        # Ctrl+Shift+P for _save_all_plots.
        wire_y_zoom_shortcuts(self)

    # ------------------------------------------------------------------
    # Pure plotting backend
    # ------------------------------------------------------------------

    @staticmethod
    def plot_on_axes(
        *,
        ax_mod,
        ax_phase,
        ax_coh,
        data: _TransferPlotData,
        bands: dict[str, dict],
        phase_view: str = "wrapped",
        show_coherence_threshold: bool = True,
        coherence_threshold_level: float = 0.5,
        coherence_mask_alpha: float = 0.20,
        min_coherence: float = 0.5,
        f_min: float = 0.0,
        f_max: float = 0.5,
    ) -> None:
        """Draw modulus, phase and coherence onto the three axes."""
        freqs = data.freqs
        # Shared x-axis range from Settings. sharex=ax_mod propagates the
        # *limits*, but matplotlib's default autoscale_on=True re-expands
        # them on the next plot() call - so we pin xlim AND disable
        # autoscale on each axes individually. (Same pattern PSDPlotWidget
        # uses.)
        for ax in (ax_mod, ax_phase, ax_coh):
            ax.set_xlim(f_min, f_max)
            ax.autoscale(enable=False, axis="x")

        # ---- band axvspans on phase + coherence ---------------------
        for name, spec in bands.items():
            if name == "FullRange":
                continue
            low = float(spec.get("low", 0.0))
            high = float(spec.get("high", 0.0))
            if high <= low:
                continue
            colour = spec.get("color", "gray")
            alpha = float(spec.get("alpha", 0.18))
            for ax in (ax_phase, ax_coh):
                ax.axvspan(low, high, color=colour, alpha=alpha, zorder=0)

        # ---- modulus, PSD-style under-curve fills -------------------
        # ``bands`` is already filtered to the user-selected subset by the
        # container, so the FullRange-skip guard from the historical
        # implementation is gone: if the user ticked FullRange they get a
        # gray backdrop fill across the panel (mirrors PSD widget look).
        ax_mod.plot(freqs, data.modulus, color="black", lw=1.0,
                    alpha=0.85, zorder=3)
        band_extents = _band_draw_extents(bands)
        for name, spec in bands.items():
            draw_low, draw_high = band_extents.get(name, (None, None))
            if draw_low is None:
                continue
            _draw_modulus_band_fill(
                ax_mod, freqs, data.modulus,
                name=name, spec=spec,
                band_results=data.band_results,
                draw_low=draw_low, draw_high=draw_high,
            )
        ax_mod.set_ylabel("|H(f)|")
        ax_mod.set_ylim(bottom=0.0)
        ax_mod.legend(loc="upper right", fontsize=7, framealpha=0.75)
        ax_mod.spines["top"].set_visible(False)
        ax_mod.spines["right"].set_visible(False)

        # ---- phase --------------------------------------------------
        phase = (
            data.phase_unwrapped if phase_view == "unwrapped"
            else data.phase_wrapped
        )
        coh = data.coherence
        coherent = coh >= min_coherence
        ax_phase.plot(
            freqs[coherent], phase[coherent],
            ".", color="black", markersize=3, zorder=3,
        )
        if coherence_mask_alpha > 0.0 and (~coherent).any():
            ax_phase.plot(
                freqs[~coherent], phase[~coherent],
                ".", color="black",
                markersize=3, alpha=coherence_mask_alpha,
                zorder=2,
            )
        if phase_view == "wrapped":
            ax_phase.axhline(0.0, color="dimgray", lw=0.6, zorder=1)
            ax_phase.set_ylim(-np.pi - 0.2, np.pi + 0.2)
            ax_phase.set_yticks([-np.pi, -np.pi / 2, 0.0, np.pi / 2, np.pi])
            ax_phase.set_yticklabels(
                [r"$-\pi$", r"$-\pi/2$", "0", r"$\pi/2$", r"$\pi$"],
                fontsize=8,
            )
        else:
            ax_phase.axhline(0.0, color="dimgray", lw=0.6, zorder=1)
        ax_phase.set_ylabel("phase [rad]")
        ax_phase.spines["top"].set_visible(False)
        ax_phase.spines["right"].set_visible(False)

        # ---- coherence ----------------------------------------------
        # Auto-rescale when peak coherence < 0.2 so a flat-near-zero
        # line is actually visible; otherwise the textbook [0, 1.05]
        # view with the 0.5 threshold line.
        ax_coh.plot(freqs, coh, color="black", lw=1.2, zorder=3)
        finite_coh = coh[np.isfinite(coh)] if coh.size else coh
        coh_peak = float(finite_coh.max()) if finite_coh.size else 0.0
        low_coh_regime = coh_peak < 0.2

        if low_coh_regime:
            top = max(coh_peak * 1.5, 0.05)
            ax_coh.set_ylim(0.0, top)
            ax_coh.set_yticks([0.0, top / 2.0, top])
            ax_coh.set_yticklabels(
                ["0", f"{top / 2.0:.2f}", f"{top:.2f}"]
            )
            ax_coh.set_ylabel(
                r"$|C(f)|^2$" + f"\n(peak {coh_peak:.3f})"
            )
        else:
            ax_coh.set_ylim(0.0, 1.05)
            ax_coh.set_yticks([0.0, 0.5, 1.0])
            ax_coh.set_ylabel(r"$|C(f)|^2$")

        if show_coherence_threshold and not low_coh_regime:
            ax_coh.axhline(
                coherence_threshold_level,
                color="red", lw=1.0, ls="--", alpha=0.7,
                label=f"thr {coherence_threshold_level:.2f}",
                zorder=2,
            )
            ax_coh.legend(loc="upper right", fontsize=7, framealpha=0.75)

        ax_coh.set_xlabel("frequency [Hz]")
        ax_coh.spines["top"].set_visible(False)
        ax_coh.spines["right"].set_visible(False)

        if data.method:
            method_label = data.method.replace("_", " ").capitalize()
            ax_mod.set_title(
                f"{method_label}",
                fontsize=8, loc="left", color="dimgray",
            )
