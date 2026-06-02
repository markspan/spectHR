# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
3-D spectrogram plotting widget.

Renders the same sliding-window PSD grid as :mod:`spectrogramPlotWidget`
but as an interactive 3-D surface: time on the x-axis, frequency on the
y-axis, and spectral power as height on the z-axis, coloured by the same
normalised power value.

The user can orbit the surface with the mouse (left-drag to rotate,
right-drag or scroll to zoom) because the underlying ``Axes3D`` from
``mpl_toolkits.mplot3d`` is interactive inside the Qt canvas.

Design notes
------------
- The *entire* compute path is shared with the 2-D widget via
  :mod:`_spectrogram_compute`.  This widget imports
  :func:`~_spectrogram_compute.fetch_spectrogram`,
  :func:`~_spectrogram_compute.normalise_grid`,
  :func:`~_spectrogram_compute.epoch_relative_times`, and
  :func:`~_spectrogram_compute.downsample_for_surface`.  No PSD engine
  call is made inside this file.
- ``plot_on_axis`` accepts a plain ``Axes3D`` (created with
  ``projection="3d"``) so it is testable without any Qt context, just
  like the 2-D sibling.
- The respiration overlay becomes a 3-D line at the floor of the z-axis
  (z = 0) so it does not visually compete with the surface peaks.
- Dense grids are downsampled before surface construction to keep the
  polygon count inside the 6 400-cell budget (see
  :data:`~_spectrogram_compute.MAX_SURFACE_BINS`).
- The default view angle (elevation 35°, azimuth −60°) is chosen so
  the LF and HF peaks are immediately visible on a typical HRV
  spectrogram; users can orbit freely after construction.
"""
from __future__ import annotations

from typing import Any

import numpy as np

# mpl_toolkits.mplot3d ships as part of matplotlib and is available
# wherever matplotlib is installed.  The explicit import of Axes3D is
# required before passing ``projection="3d"`` to add_subplot.
from mpl_toolkits.mplot3d import Axes3D   # noqa: F401 — registers the projection
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
    MAX_SURFACE_BINS,
    SpectrogramData,
    downsample_for_surface,
    epoch_relative_times,
    fetch_spectrogram,
    normalise_grid,
)
from spectUI.workSpace import (
    psd_method_from_workspace,
    spectrogram_settings_from_workspace,
)


# Default view angles for the 3-D surface.  Elevation 35° keeps the
# z-scale readable; azimuth −60° puts the time axis running left-to-right
# and the frequency axis running back-to-front, which matches the visual
# intuition of the 2-D heat map laid flat and then tilted toward the viewer.
_DEFAULT_ELEVATION_DEG: float = 35.0
_DEFAULT_AZIMUTH_DEG:   float = -60.0

# Shared default colormap, kept in sync with the 2-D sibling.
_DEFAULT_COLORMAP = "RdYlBu_r"

# Alpha of the surface polygons.  A value below 1.0 lets the frequency-band
# walls (if added in future) show through, and also softens the visual
# weight of the surface when multiple epochs are visible in a floating dock.
_SURFACE_ALPHA: float = 0.90


# ---------------------------------------------------------------------------
# Single-tile sub-widget
# ---------------------------------------------------------------------------


class _SingleSpectrogram3DPlot(QWidget):
    """One matplotlib figure showing a 3-D spectrogram surface for one epoch.

    Constructed once per epoch by :class:`Spectrogram3DPlotWidget`.
    The surface is drawn immediately in ``__init__``; the ``Axes3D``
    remains interactive (the user can orbit with the mouse) until the
    widget is destroyed.

    Parameters
    ----------
    data : SpectrogramData
        Pre-computed spectrogram data from :func:`fetch_spectrogram`.
    parent : QWidget or None
        Optional Qt parent.
    show_respiration_overlay : bool
        Draw the per-window breathing-frequency trace at the floor
        of the z-axis when available.
    colormap : str
        Matplotlib colormap name for the surface.
    elevation_deg : float
        Initial camera elevation in degrees.
    azimuth_deg : float
        Initial camera azimuth in degrees.
    """

    def __init__(
        self,
        data: SpectrogramData,
        parent: QWidget | None = None,
        *,
        show_respiration_overlay: bool = True,
        colormap: str = _DEFAULT_COLORMAP,
        elevation_deg: float = _DEFAULT_ELEVATION_DEG,
        azimuth_deg:   float = _DEFAULT_AZIMUTH_DEG,
    ) -> None:
        super().__init__(parent)

        # A slightly taller figure than the 2-D tile (5 × 5 vs 5 × 4)
        # to give the z-axis room without squashing the base.
        figure  = Figure(figsize=(5, 5), facecolor="white")
        self.canvas: FigureCanvas = FigureCanvas(figure)

        # projection="3d" requires that Axes3D has been imported first
        # (the import at the top of this file registers it with matplotlib).
        self.ax: Axes3D = figure.add_subplot(111, projection="3d")
        self.setStyleSheet("background-color: white;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Delegate all drawing to the pure static method.
        Spectrogram3DPlotWidget.plot_on_axis(
            self.ax, data,
            show_respiration_overlay=show_respiration_overlay,
            colormap=colormap,
            elevation_deg=elevation_deg,
            azimuth_deg=azimuth_deg,
        )
        self.ax.set_title(data.label, pad=12)
        self.canvas.draw()


# ---------------------------------------------------------------------------
# Container widget
# ---------------------------------------------------------------------------


class Spectrogram3DPlotWidget(PlotExportMixin, QWidget):
    """Grid of 3-D spectrogram surface tiles, one per active epoch.

    Drop-in companion to :class:`~spectrogramPlotWidget.SpectrogramPlotWidget`.
    Both widgets read from the same workspace chapter (``Spectrogram``)
    and call the same :func:`~_spectrogram_compute.fetch_spectrogram`
    function, so they always display the same underlying data.

    Parameters
    ----------
    series_list : list
        ``CardioSeriesView`` objects, one per active epoch.
    labels : list of str
        Per-epoch tile titles.
    parent : QWidget or None
        Optional Qt parent.
    workspace : dict or None
        Workspace configuration dict.  The ``Spectrogram`` chapter
        (window, step, colormap, respiration overlay) and the
        ``FrequencyAnalysis`` chapter (PSD method) are both read here.
    """

    # Used by PlotExportMixin to build the export filename prefix.
    _export_context = "Spectrogram3D"

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
        # Re-use the same reader as the 2-D widget so both views always
        # have the same window / step / colormap unless the user creates
        # a separate "Spectrogram3D" workspace chapter in a future
        # extension.
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
        # This is identical to SpectrogramPlotWidget.__init__: both widgets
        # call fetch_spectrogram with the same arguments, so the data is
        # the same object shape.  They differ only in how they render it.
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
        self._subplots: list[_SingleSpectrogram3DPlot] = build_epoch_grid(
            self, plots,
            lambda data: _SingleSpectrogram3DPlot(
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
        ax: "Axes3D",
        data: SpectrogramData,
        *,
        show_respiration_overlay: bool = True,
        colormap: str = _DEFAULT_COLORMAP,
        elevation_deg: float = _DEFAULT_ELEVATION_DEG,
        azimuth_deg:   float = _DEFAULT_AZIMUTH_DEG,
    ) -> "Axes3D":
        """Draw a 3-D spectrogram surface on *ax*.

        This is a pure function: it draws on ``ax`` and returns it.
        No Qt objects are touched, so it can be called from tests,
        notebooks, or any other matplotlib context that provides an
        ``Axes3D`` instance.

        The surface is constructed as follows:

        1. The raw ``power_grid`` is normalised to [0, 1] epoch-locally
           (see :func:`~_spectrogram_compute.normalise_grid`).
        2. If the grid is larger than :data:`~_spectrogram_compute.MAX_SURFACE_BINS`
           on either axis, it is downsampled with uniform strides via
           :func:`~_spectrogram_compute.downsample_for_surface`.
        3. ``numpy.meshgrid`` creates the (T, F) coordinate arrays that
           ``plot_surface`` expects.
        4. The normalised power drives both the z-height *and* the face
           colour through the supplied ``colormap``, giving the viewer
           two redundant channels to read power magnitude.
        5. The respiration trace (when present) is drawn as a 3-D line
           at z = 0 so it floats at the base of the surface without
           obscuring the peaks.

        Parameters
        ----------
        ax : mpl_toolkits.mplot3d.Axes3D
            The 3-D axes to draw on.  Must be created with
            ``projection="3d"``.
        data : SpectrogramData
            Pre-computed epoch spectrogram from :func:`fetch_spectrogram`.
        show_respiration_overlay : bool
            Draw the per-window breathing-frequency trace at z = 0.
        colormap : str
            Matplotlib colormap name.
        elevation_deg : float
            Camera elevation in degrees for ``ax.view_init``.
        azimuth_deg : float
            Camera azimuth in degrees for ``ax.view_init``.

        Returns
        -------
        mpl_toolkits.mplot3d.Axes3D
            The same ``ax`` that was passed in.
        """
        # ---- guard: empty or failed data -----------------------------
        if (
            data.power_grid.size == 0
            or data.freqs.size == 0
            or data.timestamps.size == 0
        ):
            # Axes3D does not support transform=ax.transAxes, so we
            # place the placeholder text at the centre of data coordinates.
            ax.text2D(
                0.5, 0.5,
                data.error or "No spectrogram data",
                ha="center", va="center",
                transform=ax.transAxes, color="gray",
            )
            return ax

        finite = data.power_grid[np.isfinite(data.power_grid)]
        if finite.size < 2:
            ax.text2D(
                0.5, 0.5,
                "Insufficient spectrogram data (fewer than 2 finite cells)",
                ha="center", va="center",
                transform=ax.transAxes, color="gray",
            )
            return ax

        # ---- normalise -----------------------------------------------
        norm_grid = normalise_grid(data.power_grid)

        # ---- epoch-relative time axis --------------------------------
        t_rel = epoch_relative_times(data)

        # ---- downsample if needed ------------------------------------
        # plot_surface polygon count = n_freqs × n_windows, which can
        # be large for dense Welch grids.  Downsample before constructing
        # the meshgrid so the mesh arrays are never oversized.
        ds_grid, ds_freqs, ds_timestamps = downsample_for_surface(
            norm_grid, data.freqs, t_rel,
        )

        # ---- build coordinate mesh -----------------------------------
        # meshgrid produces (n_freqs × n_windows) arrays matching the
        # shape expected by plot_surface: first axis = rows = frequency,
        # second axis = columns = time.
        T, F = np.meshgrid(ds_timestamps, ds_freqs)

        # Replace any remaining NaN in the downsampled grid with 0 so
        # plot_surface does not leave holes in the mesh.  Holes appear
        # where windows had too few beats; the user can identify them as
        # flat regions at z = 0 in the surface.
        ds_grid_clean = np.where(np.isfinite(ds_grid), ds_grid, 0.0)

        # ---- surface plot --------------------------------------------
        surf = ax.plot_surface(
            T, F, ds_grid_clean,
            cmap=colormap,
            vmin=0.0, vmax=1.0,
            alpha=_SURFACE_ALPHA,
            # rstride=1, cstride=1 forces matplotlib to draw every row and
            # column of the mesh.  After downsampling the mesh is already
            # small enough that skipping rows (the default is 10) would
            # visibly degrade the shape.
            rstride=1, cstride=1,
            linewidth=0,           # hide the mesh wire to keep the surface clean
            antialiased=True,
        )

        # ---- axis labels ---------------------------------------------
        ax.set_xlabel("Time within epoch [s]", labelpad=8)
        ax.set_ylabel("Frequency [Hz]",        labelpad=8)
        ax.set_zlabel("Power (normalised)",     labelpad=6)

        ax.set_xlim(float(ds_timestamps[0]),   float(ds_timestamps[-1]))
        ax.set_ylim(float(ds_freqs[0]),        float(ds_freqs[-1]))
        ax.set_zlim(0.0, 1.0)

        # ---- respiration overlay at z = 0 ----------------------------
        # Drawing the line at the base of the surface (z = 0) avoids
        # visual ambiguity: it is clearly a floor annotation rather than
        # a floating line inside the surface.
        if show_respiration_overlay and data.resp_freqs is not None:
            rf = np.asarray(data.resp_freqs).ravel()
            # Downsample the respiration trace with the same time stride
            # used for the surface so the x-coordinates align.
            _, _, ds_t_resp = downsample_for_surface(
                norm_grid, data.freqs, t_rel,
            )
            # Recompute the time stride to slice rf consistently.
            time_stride = max(1, len(t_rel) // MAX_SURFACE_BINS)
            rf_ds = rf[::time_stride]

            # Only draw the trace where at least one value is finite and
            # the slice length matches the downsampled time axis.
            if (
                rf_ds.size == ds_t_resp.size
                and np.any(np.isfinite(rf_ds))
            ):
                # Replace NaN with 0 so the line does not have gaps.
                rf_ds_clean = np.where(np.isfinite(rf_ds), rf_ds, 0.0)
                # Constant z = 0: the trace lies flat on the base plane.
                z_floor = np.zeros_like(rf_ds_clean)
                ax.plot(
                    ds_t_resp, rf_ds_clean, z_floor,
                    "g--", lw=1.5, alpha=0.7,
                    label="breath. freq.",
                    zorder=5,
                )
                ax.legend(loc="upper right", fontsize=7)

        # ---- colourbar -----------------------------------------------
        # ``ax.figure`` is the parent Figure shared across all subplots
        # when tiles are built via build_epoch_grid.  Using a small inset
        # fraction keeps the bar tight to this specific subplot.
        unit_str = f" [{data.unit}]" if data.unit else ""
        cbar = ax.figure.colorbar(
            surf,
            ax=ax,
            shrink=0.55,    # fraction of subplot height to occupy
            aspect=12,      # height / width of the colour strip
            pad=0.12,       # gap between surface and colourbar
        )
        cbar.set_label(f"Power{unit_str}", fontsize=7)
        cbar.set_ticks([0.0, 0.5, 1.0])
        cbar.ax.set_yticklabels(["Low", "Active", "High"], fontsize=6)

        # ---- method subtitle -----------------------------------------
        if data.method:
            method_label = data.method.replace("_", " ").capitalize()
            # ax.set_title is the main epoch label (set by the tile
            # __init__); use ax.text2D for the smaller method subtitle.
            ax.text2D(
                0.02, 0.97,
                method_label,
                transform=ax.transAxes,
                fontsize=8, color="dimgray",
                va="top",
            )

        # ---- initial camera angle ------------------------------------
        ax.view_init(elev=elevation_deg, azim=azimuth_deg)

        return ax
