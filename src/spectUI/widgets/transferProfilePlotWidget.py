# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Per-epoch sliding-window transfer-profile widget.

Each tile holds three stacked subplots sharing the epoch-relative
time x-axis:

    1. modulus(t)              one line per band.
    2. phase(t)                one line per band, wrapped or unwrapped
                               per Settings.
    3. weighted coherence(t)   one line per band, optional horizontal
                               threshold line at coherence_threshold_level.

Per-band colours are pulled from FrequencyAnalysis.bands so the lines
match the PSD / Profile / Spectrogram views.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from spectHR.Tools.Logger import logger
from spectHR.analysis.transfer import (
    TransferProfileResult,
    compute_transfer_profile,
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
# Plot data
# ---------------------------------------------------------------------------


@dataclass
class _TransferProfilePlotData:
    """Everything one tile needs to render its three time-resolved panels."""

    label: str
    timestamps: np.ndarray
    band_names: list[str]
    modulus: np.ndarray             # (n_bands, n_windows)
    phase: np.ndarray               # (n_bands, n_windows), wrapped
    phase_unwrapped: np.ndarray     # (n_bands, n_windows), unwrapped
    weighted_coherence: np.ndarray  # (n_bands, n_windows)
    n_coherent: np.ndarray          # (n_bands, n_windows), int
    window_s: float
    step_s: float
    method: str
    error: str | None = None


def _band_edges(workspace: dict[str, Any] | None) -> dict[str, tuple[float, float]]:
    """Band edge dict to feed compute_transfer_profile.

    Returns every band defined in FrequencyAnalysis.bands except
    FullRange (a 0.02 - 0.5 Hz integration is a near-duplicate of the
    per-bin transfer and just clutters the per-line legend).
    """
    bands = display_bands_from_workspace(workspace)
    return {
        name: (float(spec["low"]), float(spec["high"]))
        for name, spec in bands.items()
        if name != "FullRange" and "low" in spec and "high" in spec
    }


def _fetch_transfer_profile(
    series,
    label: str,
    *,
    workspace: dict[str, Any] | None,
    window_s: float,
    step_s: float,
    min_coherence: float,
    f_max: float,
    smooth: bool = True,
) -> _TransferProfilePlotData:
    """Compute one epoch's transfer profile, never raises."""
    empty = _TransferProfilePlotData(
        label=label,
        timestamps=np.array([]),
        band_names=[],
        modulus=np.empty((0, 0)),
        phase=np.empty((0, 0)),
        phase_unwrapped=np.empty((0, 0)),
        weighted_coherence=np.empty((0, 0)),
        n_coherent=np.empty((0, 0), dtype=int),
        window_s=window_s,
        step_s=step_s,
        method="",
    )

    pd = getattr(series, "_pd", None)
    if pd is None:
        return _TransferProfilePlotData(
            **{**empty.__dict__, "error": "No PhysioData"}
        )
    # The continuous respiration TimeSeries lives at ``pd["rsp"].timeseries``
    # (StreamAccessor.timeseries). pd.rsp_map holds RespirationSeries phase
    # intervals (INH/EXH), which is a different object and has no
    # .times / .values - those would crash ``compute_transfer_profile``.
    try:
        rsp_for_transfer = pd["rsp"].timeseries
    except KeyError:
        return _TransferProfilePlotData(
            **{**empty.__dict__, "error": "No respiration channel"}
        )

    bands = _band_edges(workspace)
    if not bands:
        return _TransferProfilePlotData(
            **{**empty.__dict__, "error": "No bands configured"}
        )

    try:
        result: TransferProfileResult = compute_transfer_profile(
            series,
            rsp_for_transfer,
            bands=bands,
            window_s=window_s,
            step_s=step_s,
            min_coherence=min_coherence,
            f_max=f_max,
            smooth=smooth,
        )
    except Exception as exc:
        logger.debug("compute_transfer_profile failed for %s: %s", label, exc)
        return _TransferProfilePlotData(
            **{**empty.__dict__, "error": f"Transfer profile failed: {exc}"}
        )

    # Diagnostic: per-band count of finite weighted_coherence cells, so the
    # user can tell whether the bottom panel is empty because windows are
    # failing the n_peaks >= 4 gate (-> NaN) or because the coherence is
    # genuinely low (-> finite cells that hug y=0).
    coh_arr = np.asarray(result.weighted_coherence)
    n_windows_total = coh_arr.shape[1] if coh_arr.ndim == 2 else 0
    diag = ", ".join(
        f"{name}: {int(np.sum(np.isfinite(coh_arr[b])))}/{n_windows_total}"
        for b, name in enumerate(result.band_names)
    )
    logger.debug(
        "Transfer profile [%s]: finite weighted-coherence cells per band -> %s",
        label, diag,
    )

    return _TransferProfilePlotData(
        label=label,
        timestamps=result.timestamps,
        band_names=list(result.band_names),
        modulus=np.asarray(result.modulus),
        phase=np.asarray(result.phase),
        phase_unwrapped=np.asarray(result.phase_unwrapped),
        weighted_coherence=coh_arr,
        n_coherent=np.asarray(result.n_coherent),
        window_s=float(result.window_s),
        step_s=float(result.step_s),
        method=result.method,
    )


# ---------------------------------------------------------------------------
# Per-epoch tile
# ---------------------------------------------------------------------------


class _SingleTransferProfilePlot(QWidget):
    """Three-panel time-resolved transfer view for one epoch."""

    def __init__(
        self,
        data: _TransferProfilePlotData,
        parent: QWidget | None = None,
        *,
        bands: dict[str, dict] | None = None,
        phase_view: str = "wrapped",
        show_coherence_threshold: bool = True,
        coherence_threshold_level: float = 0.5,
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

        if (
            data.error is not None
            or data.timestamps.size == 0
            or not data.band_names
        ):
            ax = fig.add_subplot(111)
            ax.text(
                0.5, 0.5, data.error or "No transfer profile data",
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
        # at the top (modulus) panel.
        self.ax = ax_mod

        TransferProfilePlotWidget.plot_on_axes(
            ax_mod=ax_mod,
            ax_phase=ax_phase,
            ax_coh=ax_coh,
            data=data,
            bands=bands,
            phase_view=phase_view,
            show_coherence_threshold=show_coherence_threshold,
            coherence_threshold_level=coherence_threshold_level,
        )
        ax_mod.set_title(f"Transfer profile - {data.label}", fontsize=10)
        ax_mod.tick_params(labelbottom=False)
        ax_phase.tick_params(labelbottom=False)
        # subplots_adjust instead of tight_layout: tight_layout warns on
        # GridSpec triples with shared x-axes ("Axes that are not
        # compatible with tight_layout"), and we already control hspace
        # via GridSpec itself.
        fig.subplots_adjust(
            left=0.10, right=0.98, top=0.94, bottom=0.08, hspace=0.08,
        )
        self.canvas.draw()


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------


class TransferProfilePlotWidget(YZoomMixin, PlotExportMixin, QWidget):
    """Grid of time-resolved transfer-profile tiles, one per active epoch.

    Initial y-axes are linked across epochs: every tile starts with the
    same modulus y-top so the epochs are visually comparable at first
    glance. Up / Down zoom then acts **per tile** - it rescales only
    the tile currently under the mouse cursor, leaving the others
    untouched. That lets the user zoom into a weak epoch without
    losing the global scale on the other ones.
    """

    _export_context = "TransferProfile"

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
        bands = display_bands_from_workspace(workspace)

        plots: list[_TransferProfilePlotData] = [
            _fetch_transfer_profile(
                series, label,
                workspace=workspace,
                window_s=float(cfg["window_s"]),
                step_s=float(cfg["step_s"]),
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
        # the largest finite modulus across all bands and windows.
        # Tiles start linked; Up / Down zoom unlinks them per-tile.
        peaks: list[float] = []
        for d in plots:
            m = np.asarray(d.modulus)
            if m.size:
                finite = m[np.isfinite(m)]
                if finite.size:
                    peaks.append(float(finite.max()))
        y_top = max(peaks) * 1.1 if peaks else 1.0
        self._y_top: float = max(y_top, Y_TOP_FLOOR)

        self._subplots: list[_SingleTransferProfilePlot] = build_epoch_grid(
            self, plots,
            lambda data: _SingleTransferProfilePlot(
                data,
                bands=bands,
                phase_view=str(cfg["phase_view"]),
                show_coherence_threshold=bool(cfg["show_coherence_threshold"]),
                coherence_threshold_level=float(cfg["coherence_threshold_level"]),
            ),
        )
        # All tiles share the same initial modulus y-top so the
        # epochs are visually comparable at first glance. Up / Down
        # zoom then walks them apart per-tile (see _zoom_in / _zoom_out).
        for sp in self._subplots:
            sp.ax.set_ylim(bottom=0.0, top=self._y_top)
            sp.canvas.draw_idle()
        # Up / Down arrow shortcuts; build_epoch_grid already installs
        # Ctrl+Shift+P for _save_all_plots.
        wire_y_zoom_shortcuts(self)

    # YZoomMixin's _set_y_top would slam every tile to the same y_top.
    # Instead, find the tile under the mouse cursor and zoom it alone.
    # If the cursor is outside the grid, nothing happens (the user
    # probably meant a different widget's shortcut).
    def _tile_under_cursor(self) -> "_SingleTransferProfilePlot | None":
        """Return the subplot whose canvas / frame is under the mouse."""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication
        w = QApplication.widgetAt(QCursor.pos())
        while w is not None:
            if w in self._subplots:
                return w  # type: ignore[return-value]
            w = w.parent()
        return None

    def _zoom_in(self) -> None:
        """Up arrow: shrink the hovered tile's y-top by 20%."""
        tile = self._tile_under_cursor()
        if tile is None:
            return
        cur_top = float(tile.ax.get_ylim()[1])
        tile.ax.set_ylim(bottom=0.0, top=max(cur_top * 0.80, Y_TOP_FLOOR))
        tile.canvas.draw_idle()

    def _zoom_out(self) -> None:
        """Down arrow: grow the hovered tile's y-top by 25%."""
        tile = self._tile_under_cursor()
        if tile is None:
            return
        cur_top = float(tile.ax.get_ylim()[1])
        tile.ax.set_ylim(bottom=0.0, top=cur_top * 1.25)
        tile.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Pure plotting backend
    # ------------------------------------------------------------------

    @staticmethod
    def plot_on_axes(
        *,
        ax_mod,
        ax_phase,
        ax_coh,
        data: _TransferProfilePlotData,
        bands: dict[str, dict],
        phase_view: str = "wrapped",
        show_coherence_threshold: bool = True,
        coherence_threshold_level: float = 0.5,
    ) -> None:
        """Draw modulus, phase and coherence time-series onto three axes.

        One line per band, colour pulled from the workspace band table.
        """
        # Epoch-relative time. timestamps are absolute window centres.
        t0    = float(data.timestamps[0]) - data.window_s / 2.0
        t_rel = data.timestamps - t0
        t_lim = (data.window_s / 2.0, float(t_rel[-1]) + data.step_s * 0.5)

        phase_arr = (
            data.phase_unwrapped if phase_view == "unwrapped"
            else data.phase
        )

        for b, name in enumerate(data.band_names):
            spec = bands.get(name, {})
            colour = spec.get("color", "gray")
            fill_alpha = float(spec.get("alpha", 0.30))

            # Modulus: PSD-style filled interior under the band's line.
            # NaN cells become 0 for the fill polygon, so empty windows
            # don't drag the fill down through the axis.
            mod_line  = np.asarray(data.modulus[b], dtype=float)
            mod_fill  = np.nan_to_num(mod_line, nan=0.0)
            ax_mod.fill_between(
                t_rel, 0.0, mod_fill,
                color=colour, alpha=fill_alpha, zorder=2,
            )
            ax_mod.plot(
                t_rel, mod_line,
                color=colour, lw=1.4, label=name, zorder=3,
            )
            ax_phase.plot(
                t_rel, phase_arr[b],
                color=colour, lw=1.2, label=name, zorder=3,
            )
            ax_coh.plot(
                t_rel, data.weighted_coherence[b],
                color=colour, lw=1.2, label=name, zorder=3,
            )
        # ---- modulus -------------------------------------------------
        ax_mod.set_ylabel("|H|")
        ax_mod.set_xlim(*t_lim)
        ax_mod.set_ylim(bottom=0.0)
        ax_mod.spines["top"].set_visible(False)
        ax_mod.spines["right"].set_visible(False)
        ax_mod.legend(loc="upper right", fontsize=7, framealpha=0.75)

        # ---- phase ---------------------------------------------------
        ax_phase.set_ylabel("phase [rad]")
        ax_phase.set_xlim(*t_lim)
        ax_phase.axhline(0.0, color="dimgray", lw=0.6, zorder=1)
        if phase_view == "wrapped":
            ax_phase.set_ylim(-np.pi - 0.2, np.pi + 0.2)
            ax_phase.set_yticks([-np.pi, -np.pi / 2, 0.0, np.pi / 2, np.pi])
            ax_phase.set_yticklabels(
                [r"$-\pi$", r"$-\pi/2$", "0", r"$\pi/2$", r"$\pi$"],
                fontsize=8,
            )
        ax_phase.spines["top"].set_visible(False)
        ax_phase.spines["right"].set_visible(False)

        # ---- coherence -----------------------------------------------
        # Pick the max finite weighted-coherence across all bands. Below
        # ~0.2 a fixed [0, 1.05] axis renders every line invisibly close
        # to the bottom spine, so we auto-rescale to [0, max*1.5] (with
        # a small floor) and skip the 0.5 threshold line as meaningless
        # at that scale. Above 0.2 we keep the textbook [0, 1.05] view
        # so the 0.5 threshold line stays informative.
        finite_coh = data.weighted_coherence[
            np.isfinite(data.weighted_coherence)
        ]
        coh_peak = float(finite_coh.max()) if finite_coh.size else 0.0
        low_coh_regime = coh_peak < 0.2

        if low_coh_regime:
            top = max(coh_peak * 1.5, 0.05)
            ax_coh.set_ylim(0.0, top)
            ax_coh.set_yticks([0.0, top / 2.0, top])
            ax_coh.set_yticklabels(
                ["0", f"{top / 2.0:.2f}", f"{top:.2f}"]
            )
            ax_coh.set_ylabel(f"weighted coh.\n(peak {coh_peak:.3f})")
        else:
            ax_coh.set_ylim(0.0, 1.05)
            ax_coh.set_yticks([0.0, 0.5, 1.0])
            ax_coh.set_ylabel("weighted coh.")

        ax_coh.set_xlabel("time within epoch [s]")
        ax_coh.set_xlim(*t_lim)
        if show_coherence_threshold and not low_coh_regime:
            ax_coh.axhline(
                coherence_threshold_level,
                color="red", lw=1.0, ls="--", alpha=0.7,
                label=f"thr {coherence_threshold_level:.2f}",
                zorder=2,
            )
        ax_coh.spines["top"].set_visible(False)
        ax_coh.spines["right"].set_visible(False)

        if data.method:
            method_label = data.method.replace("_", " ").capitalize()
            ax_mod.set_title(
                f"{method_label}",
                fontsize=8, loc="left", color="dimgray",
            )
