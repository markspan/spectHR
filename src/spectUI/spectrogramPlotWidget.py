# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Spectrogram plotting widget, sibling of ProfilePlotWidget.

Where ProfilePlotWidget shows the time course of a small set of
named band powers, SpectrogramPlotWidget shows the full PSD as a
time-frequency heat map. The sliding window is the same idea, but
every per-window PSD is kept as a column of the spectrogram grid
rather than collapsed into band integrals.

Design notes
------------
- Mirrors ProfilePlotWidget's container shape (one tile per epoch,
  shared 2-column grid, Shift+Ctrl+P export).
- The y-axis is frequency in Hz, so the band-power Up/Down zoom
  used by Profile / PSD does not apply. The mixin used here is
  PlotExportMixin only, not YZoomMixin.
- Compute is a dedicated sliding-window PSD pass on the cardio
  series, configured via workspace["Spectrogram"] (window, step,
  optional respiration overlay).
- The PSD method (Welch / Lomb-Scargle / CARSPAN / strict) comes
  from FrequencyAnalysis, the same way ProfilePlotWidget reads it,
  so switching the analysis method from Settings updates every
  spectral view consistently.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional

import numpy as np

from matplotlib.axes import Axes
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGridLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from spectHR.Tools.Logger import logger
from spectHR.Tools.RespirationSegmentation import mean_breath_frequency_hz
from spectHR.analysis.psd._config import PsdMethod, _DEFAULT_PSD_METHOD
from spectHR.analysis.psd._engine import PSDEngine
from spectUI._plot_export import PlotExportMixin
from spectUI.workSpace import psd_method_from_workspace

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Workspace helpers
# ---------------------------------------------------------------------------


_DEFAULT_COLORMAP = "RdYlBu_r"


def _spectrogram_settings_from_workspace(
    workspace: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return ``workspace["Spectrogram"]`` with sensible defaults.

    ``window (sec)`` and ``step (sec)`` carry the same meaning as on
    the Profile side, the per-window length in seconds and the slide
    between consecutive windows. ``show_respiration_overlay`` draws
    the per-window breathing-frequency trace on top of the heat map
    when a RespirationSeries is available for the epoch. ``colormap``
    is the matplotlib colormap name used by ``pcolormesh``.
    """
    if workspace is None:
        return {
            "window_s": 30.0,
            "step_s":   5.0,
            "show_respiration_overlay": True,
            "colormap": _DEFAULT_COLORMAP,
        }
    spec = workspace.get("Spectrogram", {}) or {}
    window_s = spec.get("window (sec)", spec.get("window_s", 30.0))
    step_s   = spec.get("step (sec)",   spec.get("step_s",   5.0))
    return {
        "window_s": float(window_s),
        "step_s":   float(step_s),
        "show_respiration_overlay":
            bool(spec.get("show_respiration_overlay", True)),
        "colormap": str(spec.get("colormap", _DEFAULT_COLORMAP)),
    }


# ---------------------------------------------------------------------------
# Pre-computed plot data
# ---------------------------------------------------------------------------


@dataclass
class _SpectrogramPlotData:
    """Everything needed to draw one epoch spectrogram tile."""

    label: str
    timestamps: np.ndarray              # (n_windows,), window-centre times
    freqs:      np.ndarray              # (n_freqs,), common frequency grid
    power_grid: np.ndarray              # (n_freqs, n_windows), per-window PSD
    unit: str
    method: str
    window_s: float
    step_s: float
    resp_freqs: Optional[np.ndarray] = None   # (n_windows,), NaN where missing
    error: Optional[str] = None


def _fetch_spectrogram(
    series,
    label: str,
    *,
    window_s: float,
    step_s: float,
    psd_method: Optional[PsdMethod] = None,
) -> _SpectrogramPlotData:
    """Compute the spectrogram grid for one cardio series, never raises.

    Failures (epoch too short, all-NaN PSDs, no PSD method) come back
    as a ``_SpectrogramPlotData`` with ``error`` populated and empty
    arrays, so the renderer can draw a placeholder tile instead of
    leaving an empty slot in the grid.

    Per-window PSDs are computed with the supplied ``psd_method``,
    the same method the band-power profile and PSD widgets use, so
    settings flow through uniformly.

    The respiration trace (one breathing-frequency value per window)
    is collected when available so the renderer can overlay it.
    """
    empty = _SpectrogramPlotData(
        label=label,
        timestamps=np.array([]),
        freqs=np.array([]),
        power_grid=np.empty((0, 0)),
        unit="",
        method="",
        window_s=window_s,
        step_s=step_s,
    )

    try:
        method = psd_method if psd_method is not None else _DEFAULT_PSD_METHOD
        # The CARSPAN profile path skips the resample-to-display-grid
        # step so the native frequency resolution survives, same trick
        # ProfilePlotWidget uses.
        per_window_method = replace(
            method,
            carspan=replace(method.carspan, resample_to_display_grid=False),
        )

        if series.times.size == 0:
            return replace(empty, error="Empty series")
        t0       = float(series.times[0])
        duration = float(series.times[-1]) - t0
        if duration < window_s:
            return replace(empty, error="Epoch shorter than window")

        n_windows = int((duration - window_s) / step_s) + 1
        if n_windows < 1:
            return replace(empty, error="No window fits")

        common_freqs: Optional[np.ndarray] = None
        psd_cache: dict = {}
        method_label = ""
        unit = ""

        for i in range(n_windows):
            win_start = t0 + i * step_s
            win_end   = win_start + window_s
            win_view  = series.view(win_start, win_end)
            if win_view.times.size < 4:
                continue
            try:
                psd_result = PSDEngine(win_view).for_band_power(per_window_method)
            except Exception as inner_exc:
                logger.debug(
                    "Spectrogram window %d skipped, %s", i, inner_exc,
                )
                continue
            psd_cache[i] = psd_result
            if common_freqs is None and psd_result.freqs.size:
                common_freqs = psd_result.freqs.copy()
                method_label = psd_result.method or ""
                unit = psd_result.unit or ""

        if common_freqs is None or common_freqs.size == 0:
            return replace(empty, error="No spectra computed")

        n_freqs = common_freqs.size
        grid = np.full((n_freqs, n_windows), np.nan, dtype=np.float64)
        for i, psd_result in psd_cache.items():
            if psd_result.freqs.size == 0:
                continue
            if np.array_equal(psd_result.freqs, common_freqs):
                grid[:, i] = psd_result.power
            else:
                # Different bin grid (e.g. shorter window at the tail),
                # interpolate to the common grid; extrapolation -> NaN.
                grid[:, i] = np.interp(
                    common_freqs, psd_result.freqs, psd_result.power,
                    left=np.nan, right=np.nan,
                )

        timestamps = np.array(
            [t0 + i * step_s + window_s / 2.0 for i in range(n_windows)],
            dtype=np.float64,
        )

        resp_freqs = _collect_resp_freqs(series, timestamps, window_s)

        return _SpectrogramPlotData(
            label=label,
            timestamps=timestamps,
            freqs=common_freqs,
            power_grid=grid,
            unit=unit,
            method=method_label,
            window_s=window_s,
            step_s=step_s,
            resp_freqs=resp_freqs,
        )

    except Exception as exc:
        return replace(empty, error=f"Spectrogram failed: {exc}")


def _collect_resp_freqs(
    series,
    timestamps: np.ndarray,
    window_s: float,
) -> Optional[np.ndarray]:
    """Per-window mean breathing frequency, when a RespirationSeries is around.

    Mirrors the resp-freq lookup in
    ``spectHR.analysis.profile.compute_band_power_profile``: pick the
    first RespirationSeries off ``series._pd.rsp_map``, slice a view
    spanning each window, hand the view to the free function
    ``mean_breath_frequency_hz``. Returns ``None`` if the dataset
    has no respiration channel or every window comes back NaN.
    """
    pd = getattr(series, "_pd", None)
    if pd is None:
        return None
    rsp_map = getattr(pd, "rsp_map", None) or {}
    if not rsp_map:
        return None
    rsp_series = next(iter(rsp_map.values()), None)
    if rsp_series is None:
        return None
    out = np.full(timestamps.shape, np.nan, dtype=np.float64)
    for i, centre in enumerate(timestamps):
        win_start = float(centre) - window_s / 2.0
        win_end   = float(centre) + window_s / 2.0
        try:
            rsp_view = rsp_series.view(win_start, win_end)
            rf = mean_breath_frequency_hz(rsp_view)
        except Exception as exc:
            logger.debug(
                "Spectrogram resp-freq window %d skipped, %s", i, exc,
            )
            continue
        if rf is None:
            continue
        out[i] = float(rf)
    if not np.any(np.isfinite(out)):
        return None
    return out


# ---------------------------------------------------------------------------
# Single-tile subwidget
# ---------------------------------------------------------------------------


class _SingleSpectrogramPlot(QWidget):
    """One matplotlib figure showing a single epoch spectrogram."""

    def __init__(
        self,
        data: _SpectrogramPlotData,
        parent: Optional[QWidget] = None,
        *,
        show_respiration_overlay: bool = True,
        colormap: str = _DEFAULT_COLORMAP,
    ) -> None:
        super().__init__(parent)
        self.canvas: FigureCanvas = FigureCanvas(
            Figure(figsize=(5, 4), facecolor="white")
        )
        self.ax: Axes = self.canvas.figure.add_subplot(111)
        self.ax.set_facecolor("white")
        self.setStyleSheet("background-color: white;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        SpectrogramPlotWidget.plot_on_axis(
            self.ax, data,
            show_respiration_overlay=show_respiration_overlay,
            colormap=colormap,
        )
        self.ax.set_title(f"{data.label}")
        self.canvas.draw()


# ---------------------------------------------------------------------------
# Container widget
# ---------------------------------------------------------------------------


class SpectrogramPlotWidget(PlotExportMixin, QWidget):
    """Grid of spectrogram plots, one per epoch.

    Parameters
    ----------
    series_list
        CardioSeriesView (or compatible) objects with ``.times`` and
        ``.view(t_start, t_end)``.
    labels
        Per-epoch plot titles.
    workspace
        Used to read ``Spectrogram`` settings, the PSD method via
        ``FrequencyAnalysis``, and the export directory.
    """

    _export_context = "Spectrogram"

    def __init__(
        self,
        series_list: List,
        labels: List[str],
        parent: Optional[QWidget] = None,
        *,
        workspace: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(parent)

        cfg = _spectrogram_settings_from_workspace(workspace)
        window_s: float = cfg["window_s"]
        step_s:   float = cfg["step_s"]
        show_resp: bool = cfg["show_respiration_overlay"]
        colormap:  str  = cfg["colormap"]

        psd_method: Optional[PsdMethod] = (
            psd_method_from_workspace(workspace) if workspace is not None else None
        )

        # ---- compute one spectrogram per series -----------------------
        plots: List[_SpectrogramPlotData] = [
            _fetch_spectrogram(
                series, label,
                window_s=window_s, step_s=step_s,
                psd_method=psd_method,
            )
            for series, label in zip(series_list, labels)
        ]

        self._labels: List[str] = list(labels)
        self._workspace: Optional[Dict[str, Any]] = workspace
        self._subplots: List[_SingleSpectrogramPlot] = []

        # ---- scroll area + 2-column grid ------------------------------
        self.setStyleSheet("background-color: white;")
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: white;")
        container = QWidget()
        container.setStyleSheet("background-color: white;")
        container_layout = QGridLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(5)

        for idx, data in enumerate(plots):
            tile = _SingleSpectrogramPlot(
                data,
                show_respiration_overlay=show_resp,
                colormap=colormap,
            )
            self._subplots.append(tile)
            row, col = divmod(idx, 2)
            container_layout.addWidget(tile, row, col)

        scroll_area.setWidget(container)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

        # ---- shortcuts -----------------------------------------------
        self.setFocusPolicy(Qt.StrongFocus)
        save_all = QShortcut(QKeySequence("Shift+Ctrl+P"), self)
        save_all.setContext(Qt.WidgetWithChildrenShortcut)
        save_all.activated.connect(self._save_all_plots)

    # ------------------------------------------------------------------
    # Pure plotting backend
    # ------------------------------------------------------------------

    @staticmethod
    def plot_on_axis(
        ax: Axes,
        data: _SpectrogramPlotData,
        *,
        show_respiration_overlay: bool = True,
        colormap: str = _DEFAULT_COLORMAP,
    ) -> Axes:
        """Draw a time-frequency spectrogram for one epoch.

        X-axis, time within the epoch (seconds, window-centre origin).
        Y-axis, frequency (Hz).
        Colour, per-window PSD power, normalised to [0, 1] across the
        epoch via the named matplotlib colormap (default ``RdYlBu_r``,
        blue at the minimum, red at the maximum). The colour scale is
        epoch-local so weak epochs still show the shape of their
        spectral distribution.

        When ``show_respiration_overlay`` is True and the data carry
        a per-window respiration trace, a dashed green line is drawn
        on top with a small legend.
        """
        if (
            data.power_grid.size == 0
            or data.freqs.size == 0
            or data.timestamps.size == 0
        ):
            ax.text(
                0.5, 0.5, data.error or "No spectrogram data",
                ha="center", va="center",
                transform=ax.transAxes, color="gray",
            )
            return ax

        finite = data.power_grid[np.isfinite(data.power_grid)]
        if finite.size < 2:
            ax.text(
                0.5, 0.5, "Insufficient spectrogram data",
                ha="center", va="center",
                transform=ax.transAxes, color="gray",
            )
            return ax

        p_min = float(np.nanmin(finite))
        p_max = float(np.nanmax(finite))
        if p_max <= p_min:
            p_max = p_min + 1.0
        norm_grid = (data.power_grid - p_min) / (p_max - p_min)

        # Epoch-relative time. Window centres in the data are absolute;
        # subtract the first window's left edge so the axis starts at 0.
        t0    = float(data.timestamps[0]) - data.window_s / 2.0
        t_rel = data.timestamps - t0

        pcm = ax.pcolormesh(
            t_rel, data.freqs, norm_grid,
            cmap=colormap, vmin=0.0, vmax=1.0,
            shading="nearest",
        )

        ax.set_xlabel("Time within epoch [s]")
        ax.set_ylabel("Frequency [Hz]")
        ax.set_xlim(data.window_s / 2.0, float(t_rel[-1]) + data.step_s * 0.5)
        ax.set_ylim(float(data.freqs[0]), float(data.freqs[-1]))

        if show_respiration_overlay and data.resp_freqs is not None:
            rf = np.asarray(data.resp_freqs).ravel()
            if rf.size == data.timestamps.size and np.any(np.isfinite(rf)):
                ax.plot(
                    t_rel, rf,
                    "g--", lw=2.0, alpha=0.5,
                    label="breath. freq.",
                    zorder=5,
                )
                ax.legend(loc="upper right", fontsize=7, framealpha=0.75)

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        if data.method:
            method_label = data.method.replace("_", " ").capitalize()
            ax.set_title(
                f"{method_label}",
                fontsize=8, loc="left", color="dimgray",
            )

        # Colourbar in an inset axes so matplotlib does not resize
        # or y-share the main axes when adding it.
        unit_str = f" [{data.unit}]" if data.unit else ""
        cax = ax.inset_axes([1.03, 0.0, 0.04, 1.0])
        cbar = ax.figure.colorbar(pcm, cax=cax)
        cbar.set_label(f"Power{unit_str}", fontsize=7)
        cbar.set_ticks([0.0, 0.5, 1.0])
        cbar.ax.set_yticklabels(["Low", "Active", "High"], fontsize=6)

        return ax
