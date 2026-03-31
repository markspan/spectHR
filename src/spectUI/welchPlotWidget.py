"""
PSD plotting widget for CardioSeriesView objects.

This module provides:
  - A QWidget that embeds a Matplotlib figure
  - A pure plotting backend for the active PSD method (Welch or Lomb-Scargle)
  - A static probing utility to normalise axes across multiple epochs

Design principles
-----------------
- The widget knows *nothing* about epochs or datasets
- Input is always a CardioSeriesView (or compatible interface)
- Band definitions (edges, names, colours) are read from HRV_FREQUENCY_BANDS
  in CardioMetricsMixin — the single source of truth for frequency analysis
- The PSD method (WELCH / LOMBSCARGLE) is read from the module-level METHOD
  constant in CardioMetricsMixin, which is set at startup from the workspace JSON
"""

from __future__ import annotations

import warnings
from typing import Iterable, Tuple

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy

from spectHR.DataSet.Series.CardioMetricsMixin import HRV_FREQUENCY_BANDS
import sys as _sys

warnings.filterwarnings("ignore")


class WelchPSDPlotWidget(QWidget):
    """
    Qt widget for displaying a Power Spectral Density (PSD) plot.

    The widget is intentionally lightweight:
      - It embeds a single Matplotlib Axes
      - It delegates all numerical work to static helper methods
      - It can be stacked vertically in a scroll area

    Band names, frequency edges, and fill colours are taken from
    HRV_FREQUENCY_BANDS (CardioMetricsMixin), populated at startup from the
    workspace JSON FrequencyAnalysis section.

    The PSD method (Welch / Lomb-Scargle) is determined by the module-level
    METHOD constant (also set from the workspace).  No extra configuration is
    needed in the widget itself.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas: FigureCanvas = FigureCanvas(Figure(figsize=(5, 3)))
        self.ax: Axes = self.canvas.figure.add_subplot(111)

        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # ------------------------------------------------------------------
    # Axis probing utility
    # ------------------------------------------------------------------

    @staticmethod
    def probe_limits(
        series_list: Iterable,
        **plot_kwargs,
    ) -> Tuple[float, float]:
        """
        Determine global y-axis limits across multiple CardioSeriesView objects.
        Only axes with valid plotted data contribute.
        """
        ymaxs: list[float] = []
        for series in series_list:
            fig = Figure(figsize=(5, 3))
            ax = fig.add_subplot(111)
            WelchPSDPlotWidget.plot_on_axis(ax, series, **plot_kwargs)
            ax.relim()
            ax.autoscale_view()
            y0, y1 = ax.get_ylim()
            if not np.isfinite(y0) or not np.isfinite(y1):
                continue
            if y0 == 0.0 and y1 == 1.0:
                continue
            if y1 <= y0:
                continue
            ymaxs.append(y1)

        if not ymaxs:
            return 0.0, 1.0
        return 0.0, max(ymaxs)

    # ------------------------------------------------------------------
    # Core plotting backend
    # ------------------------------------------------------------------

    @staticmethod
    def plot_on_axis(
        ax: Axes,
        series,
        *,
        fs: float = 100.0,
        logscale: bool = False,
        **kwargs,
    ) -> Axes:
        """
        Plot PSD with confidence-interval shading and frequency-band fills on ax.

        The PSD estimate is obtained via ``series.psd_with_ci()``, which
        dispatches to Welch or Lomb-Scargle according to the workspace-configured
        MODULE-level METHOD constant.

        Confidence intervals are drawn as:
          - a light-grey ``fill_between`` shaded band
          - two thin dashed boundary lines for precise reading

        Band names, edges, and colours come from HRV_FREQUENCY_BANDS.
        """
        freqs, power, ci_lo, ci_hi = series.psd_with_ci(fs=fs, **kwargs)

        # Ensure all arrays are 1-D (astropy LombScargle can return 2-D)
        freqs = np.asarray(freqs).ravel()
        power = np.asarray(power).ravel()
        ci_lo = np.asarray(ci_lo).ravel()
        ci_hi = np.asarray(ci_hi).ravel()

        if freqs.size == 0:
            ax.text(
                0.5,
                0.5,
                "Insufficient data",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color="gray",
            )
            return ax

        # ---- CI shading ------------------------------------------------
        _cm = _sys.modules["spectHR.DataSet.Series.CardioMetricsMixin"]
        ci_pct = int(round((1.0 - _cm.CI_ALPHA) * 100))
        ax.fill_between(
            freqs,
            ci_lo,
            ci_hi,
            color="gray",
            alpha=0.20,
            label=f"{ci_pct} % CI",
            zorder=1,
        )
        ax.plot(freqs, ci_lo, color="gray", lw=0.7, ls="--", alpha=0.55, zorder=2)
        ax.plot(freqs, ci_hi, color="gray", lw=0.7, ls="--", alpha=0.55, zorder=2)

        # ---- PSD line --------------------------------------------------
        ax.plot(freqs, power, "k", lw=1.0, alpha=0.85, zorder=3)

        # ---- Frequency band fills --------------------------------------
        x_max = 0.0
        for name, spec in HRV_FREQUENCY_BANDS.items():
            f0 = spec["low"]
            f1 = spec["high"]
            color = spec.get("color", "gray")
            x_max = max(x_max, f1)

            mask = (freqs >= f0) & (freqs <= f1)
            p0 = np.interp(f0, freqs, power)
            p1 = np.interp(f1, freqs, power)
            f_band = np.concatenate(([f0], freqs[mask], [f1]))
            p_band = np.concatenate(([p0], power[mask], [p1]))
            band_power = np.trapezoid(p_band, f_band)

            ax.fill_between(
                f_band,
                0,
                p_band,
                color=color,
                alpha=0.35,
                label=f"{name}: {band_power:.4f} ms²",
                zorder=4,
            )

        # ---- Axes decoration -------------------------------------------
        ax.set_xlim(0.0, x_max)
        ax.set_ylim(bottom=0.0)
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel("PSD [ms²/Hz]")

        if logscale:
            ax.set_yscale("log")

        _cm = _sys.modules["spectHR.DataSet.Series.CardioMetricsMixin"]
        ax.set_title(
            f"PSD  ({_cm.METHOD.capitalize()})", fontsize=8, loc="left", color="dimgray"
        )
        ax.legend(loc="upper right", fontsize=7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        return ax

    # ------------------------------------------------------------------
    # Instance-level convenience wrapper
    # ------------------------------------------------------------------

    def plot(self, series, **kwargs) -> None:
        """Clear the internal axis and plot a PSD for a CardioSeriesView."""
        self.ax.clear()
        self.plot_on_axis(self.ax, series, **kwargs)
        self.canvas.draw()
