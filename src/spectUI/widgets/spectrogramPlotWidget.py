# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
2-D spectrogram plotting widget.

Renders the per-epoch sliding-window PSD as a ``pcolormesh`` heat map:
x-axis time, y-axis frequency, colour-encoded power.

This module is now a thin rendering shell over the shared compute layer
in ``_spectrogram_compute``.  All sliding-window PSD calculation lives
there so neither this module nor :mod:`spectrogram3dPlotWidget` duplicates
any computation code.

Design notes
------------
- Mirrors ``ProfilePlotWidget``'s container shape: one tile per epoch,
  2-column scrollable grid, ``Shift+Ctrl+P`` export.
- Uses only ``PlotExportMixin``, not ``YZoomMixin``: the y-axis carries
  frequency, not a zoomed power scale.
- The static ``plot_on_axis`` method contains the entire matplotlib
  drawing logic.  It is called by the tile sub-widget and can also be
  called directly from tests or notebooks without any Qt context.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from matplotlib.axes import Axes
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from spectHR.analysis.psd._config import PsdMethod
from spectUI.common import PlotExportMixin, build_epoch_grid
from spectUI.widgets._spectrogram_compute import (
    SpectrogramData,
    epoch_relative_times,
    fetch_spectrogram,
    normalise_grid,
)
from spectUI.workSpace import (
    psd_method_from_workspace,
    spectrogram_settings_from_workspace,
)


# Default colormap shared with the 3-D widget so both views look
# consistent without extra configuration.  Users can override this
# per-workspace via ``Spectrogram.colormap``.
_DEFAULT_COLORMAP = "RdYlBu_r"


# ---------------------------------------------------------------------------
# Single-tile sub-widget
# ---------------------------------------------------------------------------


class _SingleSpectrogram2DPlot(QWidget):
    """One matplotlib figure showing a 2-D spectrogram for a single epoch.

    Constructed once per epoch by :class:`SpectrogramPlotWidget`.
    The figure is drawn immediately in ``__init__`` and never redrawn;
    re-drawing requires the parent container to rebuild the whole grid.

    Parameters
    ----------
    data : SpectrogramData
        Pre-computed spectrogram data from :func:`fetch_spectrogram`.
    parent : QWidget or None
        Optional Qt parent.
    show_respiration_overlay : bool
        Draw the per-window breathing-frequency trace when available.
    colormap : str
        Matplotlib colormap name for the ``pcolormesh`` call.
    """

    def __init__(
        self,
        data: SpectrogramData,
        parent: QWidget | None = None,
        *,
        show_respiration_overlay: bool = True,
        colormap: str = _DEFAULT_COLORMAP,
    ) -> None:
        super().__init__(parent)

        # The figure is sized to (5, 4) inches at screen DPI.  The
        # FigureCanvas fills horizontal space because the parent grid
        # has Expanding horizontal size policy.
        figure  = Figure(figsize=(5, 4), facecolor="white")
        self.canvas: FigureCanvas = FigureCanvas(figure)
        self.ax: Axes = figure.add_subplot(111)
        self.ax.set_facecolor("white")
        self.setStyleSheet("background-color: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Delegate all drawing to the pure static method so it can be
        # exercised without a Qt event loop in tests.
        SpectrogramPlotWidget.plot_on_axis(
            self.ax, data,
            show_respiration_overlay=show_respiration_overlay,
            colormap=colormap,
        )
        # Epoch label as the tile title.  The method label (carspan /
        # welch / …) is written inside the axes by plot_on_axis itself.
        self.ax.set_title(data.label)
        self.canvas.draw()


# ---------------------------------------------------------------------------
# Container widget
# ---------------------------------------------------------------------------


class SpectrogramPlotWidget(PlotExportMixin, QWidget):
    """Grid of 2-D spectrogram tiles, one per active epoch.

    Replacing the inner plot widget on every :meth:`show_spectrogram_plot`
    call is handled by the ``MainWindow._swap_in_epoch_plot`` helper, not
    here.  This widget is purely stateless after construction.

    Parameters
    ----------
    series_list : list
        ``CardioSeriesView`` objects, one per active epoch.  Must expose
        ``.times`` and ``.view(t_start, t_end)``.
    labels : list of str
        Per-epoch tile titles.  Length must match ``series_list``.
    parent : QWidget or None
        Optional Qt parent.
    workspace : dict or None
        Workspace configuration dict.  Used to read the ``Spectrogram``
        chapter (window, step, colormap, respiration overlay) and the
        ``FrequencyAnalysis`` chapter (PSD method).
    """

    # Used by PlotExportMixin to build the export filename prefix.
    _export_context = "Spectrogram"

    def __init__(
        self,
        series_list: list,
        labels: list[str],
        parent: QWidget | None = None,
        *,
        workspace: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)

        # ---- read workspace configuration ----------------------------
        cfg = spectrogram_settings_from_workspace(workspace)
        window_s:        float = cfg["window_s"]
        step_s:          float = cfg["step_s"]
        show_resp:       bool  = cfg["show_respiration_overlay"]
        colormap:        str   = cfg["colormap"]
        adaptive_source: str   = cfg["adaptive_source"]

        psd_method: PsdMethod | None = (
            psd_method_from_workspace(workspace) if workspace is not None else None
        )

        # ---- compute one SpectrogramData per epoch -------------------
        # All PSD work happens here, in the shared compute layer.
        # The rendering sub-widgets below receive only the pre-computed
        # data objects and never touch the engine directly.
        plots: list[SpectrogramData] = [
            fetch_spectrogram(
                series, label,
                window_s=window_s,
                step_s=step_s,
                psd_method=psd_method,
                adaptive_source=adaptive_source,
            )
            for series, label in zip(series_list, labels)
        ]

        # ---- build the 2-column scrollable tile grid -----------------
        # build_epoch_grid handles the QScrollArea / QGridLayout
        # boilerplate and returns the list of tile sub-widgets so
        # PlotExportMixin can iterate them for Shift+Ctrl+P.
        self._subplots: list[_SingleSpectrogram2DPlot] = build_epoch_grid(
            self, plots,
            lambda data: _SingleSpectrogram2DPlot(
                data,
                show_respiration_overlay=show_resp,
                colormap=colormap,
            ),
        )

    # ------------------------------------------------------------------
    # Static drawing backend
    # ------------------------------------------------------------------

    @staticmethod
    def plot_on_axis(
        ax: Axes,
        data: SpectrogramData,
        *,
        show_respiration_overlay: bool = True,
        colormap: str = _DEFAULT_COLORMAP,
    ) -> Axes:
        """Draw a 2-D time-frequency spectrogram on *ax*.

        This is a pure function: it draws on ``ax`` and returns it.  No
        Qt objects are touched, so it can be called from tests, notebooks,
        or any other matplotlib context.

        The colour scale is epoch-local (normalised across the full grid)
        so epochs with low absolute power still reveal the shape of their
        spectral distribution.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            The axes to draw on.  Will be modified in place.
        data : SpectrogramData
            Pre-computed epoch spectrogram from :func:`fetch_spectrogram`.
        show_respiration_overlay : bool
            When ``True`` and ``data.resp_freqs`` is not ``None``, draw
            the per-window breathing-frequency trace as a dashed green
            line.
        colormap : str
            Matplotlib colormap name.  Any name accepted by
            ``plt.get_cmap`` is valid.

        Returns
        -------
        matplotlib.axes.Axes
            The same ``ax`` that was passed in.
        """
        # ---- guard: empty or failed data -----------------------------
        if (
            data.power_grid.size == 0
            or data.freqs.size == 0
            or data.timestamps.size == 0
        ):
            ax.text(
                0.5, 0.5,
                data.error or "No spectrogram data",
                ha="center", va="center",
                transform=ax.transAxes, color="gray",
            )
            return ax

        finite = data.power_grid[np.isfinite(data.power_grid)]
        if finite.size < 2:
            ax.text(
                0.5, 0.5,
                "Insufficient spectrogram data (fewer than 2 finite cells)",
                ha="center", va="center",
                transform=ax.transAxes, color="gray",
            )
            return ax

        # ---- normalise and compute epoch-relative time ---------------
        norm_grid = normalise_grid(data.power_grid)
        t_rel     = epoch_relative_times(data)

        # ---- main heat map -------------------------------------------
        pcm = ax.pcolormesh(
            t_rel, data.freqs, norm_grid,
            cmap=colormap, vmin=0.0, vmax=1.0,
            shading="nearest",
        )

        ax.set_xlabel("Time within epoch [s]")
        ax.set_ylabel("Frequency [Hz]")
        ax.set_xlim(
            data.window_s / 2.0,
            float(t_rel[-1]) + data.step_s * 0.5,
        )
        ax.set_ylim(float(data.freqs[0]), float(data.freqs[-1]))

        # ---- respiration overlay (optional) --------------------------
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

        # ---- cosmetic spine cleanup ----------------------------------
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        # ---- method label (small, left-anchored subtitle) -----------
        if data.method:
            method_label = data.method.replace("_", " ").capitalize()
            ax.set_title(
                method_label,
                fontsize=8, loc="left", color="dimgray",
            )

        # ---- colourbar in an inset axes ------------------------------
        # Placing the colourbar in an inset_axes prevents matplotlib
        # from shrinking the main axes or creating a y-linked twin when
        # it is added to the figure.
        unit_str = f" [{data.unit}]" if data.unit else ""
        cax  = ax.inset_axes([1.03, 0.0, 0.04, 1.0])
        cbar = ax.figure.colorbar(pcm, cax=cax)
        cbar.set_label(f"Power{unit_str}", fontsize=7)
        cbar.set_ticks([0.0, 0.5, 1.0])
        cbar.ax.set_yticklabels(["Low", "Active", "High"], fontsize=6)

        return ax
