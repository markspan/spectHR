"""
Welch PSD plotting widget for CardioSeriesView objects.

This module provides:
- A QWidget that embeds a Matplotlib figure
- A pure plotting backend for Welch PSD
- A static probing utility to normalize axes across multiple epochs

Design principles
-----------------
- The widget knows *nothing* about epochs or datasets
- Input is always a CardioSeriesView (or compatible interface)
- All frequency-domain logic lives in one place
"""

from __future__ import annotations

import warnings
from typing import Iterable, Tuple

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from scipy.interpolate import interp1d
from scipy.signal import welch

warnings.filterwarnings("ignore")


class WelchPSDPlotWidget(QWidget):
    """
    Qt widget for displaying a Welch Power Spectral Density (PSD) plot.

    The widget is intentionally lightweight:
    - It embeds a single Matplotlib Axes
    - It delegates all numerical work to static helper methods
    - It can be stacked vertically in a scroll area
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """
        Initialize the widget and its embedded Matplotlib canvas.
        """
        super().__init__(parent)

        # Create a standalone Matplotlib figure and axis
        self.canvas: FigureCanvas = FigureCanvas(Figure(figsize=(5, 3)))
        self.ax: Axes = self.canvas.figure.add_subplot(111)

        # Simple vertical layout: canvas only
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        # Important for scroll-area stacking:
        # width expands, height remains compact
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
        Determine global y-axis limits for multiple CardioSeriesView objects.

        Only axes that actually contain valid plotted data contribute
        to the global limits.
        """
        ymaxs: list[float] = []

        for series in series_list:
            fig = Figure(figsize=(5, 3))
            ax = fig.add_subplot(111)

            WelchPSDPlotWidget.plot_on_axis(ax, series, **plot_kwargs)

            # Force autoscaling after plotting
            ax.relim()
            ax.autoscale_view()

            y0, y1 = ax.get_ylim()

            # Skip default or invalid limits
            if not np.isfinite(y0) or not np.isfinite(y1):
                continue
            if y0 == 0.0 and y1 == 1.0:
                continue
            if y1 <= y0:
                continue

            ymaxs.append(y1)

        # Fallback if nothing valid was found
        if not ymaxs:
            return 0.0, 1.0

        return 0, max(ymaxs)

    # ------------------------------------------------------------------
    # Core plotting backend (pure function)
    # ------------------------------------------------------------------
    @staticmethod
    def plot_on_axis(
        ax: Axes,
        series,
        *,
        fs: float = 4.0,
        logscale: bool = False,
        **kwargs,
    ) -> Axes:
        
        freqs, power, ci_lo, ci_hi = series.welch_psd_with_ci(fs=fs, **kwargs)
        if freqs.size == 0:
            return ax

        ax.plot(freqs, power, "-k", lw=0.8, alpha=0.6)

        # Confidence intervals (dotted)
        ax.plot(freqs, ci_lo, "k:", lw=0.8, alpha=0.6)
        ax.plot(freqs, ci_hi, "k:", lw=0.8, alpha=0.6)

        bands = {
            "VLF": ((0.003, 0.04), "blue"),
            "LF":  ((0.04, 0.15), "green"),
            "HF":  ((0.15, 0.40), "red"),
        }

        for name, ((f0, f1), color) in bands.items():

            # Welch bins strictly inside the band
            mask = (freqs >= f0) & (freqs <= f1)

            # Interpolate PSD exactly at the band boundaries
            p0 = np.interp(f0, freqs, power)
            p1 = np.interp(f1, freqs, power)

            # Construct band polygon with exact boundaries
            f_band = np.concatenate(([f0], freqs[mask], [f1]))
            p_band = np.concatenate(([p0], power[mask], [p1]))

            band_power = np.trapezoid(p_band, f_band)

            ax.fill_between(
                f_band,
                0,
                p_band,
                color=color,
                alpha=0.3,
                label=f"{name}: {band_power:.4f}",
            )
            
        ax.set_xlim(0.0, 0.4)
        ax.set_ylim(bottom=0.0)
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel("PSD [ms²/Hz]")

        if logscale:
            ax.set_yscale("log")

        ax.legend(loc="upper right")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        return ax


    # ------------------------------------------------------------------
    # Instance-level convenience wrapper
    # ------------------------------------------------------------------
    def plot(self, series, **kwargs) -> None:
        """
        Clear the internal axis and plot a PSD for a given CardioSeriesView.
        """
        self.ax.clear()
        self.plot_on_axis(self.ax, series, **kwargs)
        self.canvas.draw()
