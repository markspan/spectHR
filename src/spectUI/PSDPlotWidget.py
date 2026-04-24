"""
PSD plotting widget for multiple CardioSeriesView objects.

This module provides:
- A container QWidget with multiple Matplotlib figures (one per epoch)
- A pure plotting backend for the active PSD method
  (Welch, Lomb-Scargle, CARSPAN, or CARSPAN-strict)
- Automatic uniform y-axis scaling across all epochs

Design principles
-----------------
- PSDPlotWidget is a container holding multiple single-plot subwidgets
- Input is a list of CardioSeriesView objects (one per epoch)
- Each subwidget gets its own Matplotlib figure with auto-scaling
- All figures are then re-scaled uniformly based on the largest y-axis value
- Band definitions, frequency edges, colours, and PSD method are read from
  ``CardioFrequencyMetricsMixin`` — the single source of truth
"""

from __future__ import annotations

import warnings
import sys as _sys

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QScrollArea, QSizePolicy

from spectHR.DataSet.Series.CardioFrequencyMetricsMixin import (
    HRV_FREQUENCY_BANDS,
    METHOD,
    CI_ALPHA,
)

warnings.filterwarnings("ignore")


def _cfm():
    """
    Return the CardioFrequencyMetricsMixin module at call time.

    Accessing the module lazily (rather than caching the import) ensures
    that the module-level ``METHOD`` and ``CI_ALPHA`` values reflect the
    latest workspace configuration, even if the module was reloaded or
    the globals were updated after import.
    """
    return _sys.modules["spectHR.DataSet.Series.CardioFrequencyMetricsMixin"]


class _SinglePSDPlot(QWidget):
    """
    Internal widget for a single PSD plot.

    Parameters
    ----------
    series : CardioSeriesView
        The series to plot.
    label : str
        Label/title for this plot (e.g., epoch name).
    """

    def __init__(self, series, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas: FigureCanvas = FigureCanvas(Figure(figsize=(5, 3)))
        self.ax: Axes = self.canvas.figure.add_subplot(111)
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Plot the series
        PSDPlotWidget.plot_on_axis(self.ax, series)
        self.ax.set_title(f"PSD – {label}")

        # Ensure the axes have auto-scaled before we measure limits
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw()


class PSDPlotWidget(QWidget):
    """
    Container widget displaying multiple PSD plots with uniform y-axis scaling.

    Creates one plot per series/epoch, finds the maximum y-value across all plots,
    and applies uniform scaling so all epochs are visually comparable.

    Parameters
    ----------
    series_list : list
        CardioSeriesView objects to plot (one per epoch).
    labels : list
        Label strings for each series (e.g., epoch names).
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, series_list, labels, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Create scroll area to hold all plots
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        # Container for all plot widgets (2 columns if multiple subplots)
        container = QWidget()
        container_layout = QGridLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(5)

        # Pass 1: Create and plot all subwidgets
        subplots = []
        for idx, (series, label) in enumerate(zip(series_list, labels)):
            subplot = _SinglePSDPlot(series, label)
            subplots.append(subplot)
            # Add to grid: 2 columns, multiple rows
            row = idx // 2
            col = idx % 2
            container_layout.addWidget(subplot, row, col)

        # Pass 2: Find the maximum y-axis value within the named frequency bands
        # (Exclude FullRange band from scaling calculation)
        cfm = _cfm()

        # Get all bands except FullRange
        named_bands = {k: v for k, v in cfm.HRV_FREQUENCY_BANDS.items() if k != "FullRange"}

        if not named_bands:
            # Fallback if no named bands exist
            x_min = 0.0
            x_max = 0.5
        else:
            # Use the range of the named bands
            x_min = min(s["low"] for s in named_bands.values())
            x_max = max(s["high"] for s in named_bands.values())

        y_max = 0.0
        for i, subplot in enumerate(subplots):
            lines = subplot.ax.get_lines()
            main_line = None
            dashed_lines = []

            for line in lines:
                linestyle = line.get_linestyle()
                if linestyle in ('-', 'solid'):
                    # Solid black line → the PSD estimate itself.
                    if main_line is None:
                        main_line = line
                elif linestyle in ('--', 'dashed'):
                    # Dashed grey lines → CI boundary lines.
                    dashed_lines.append(line)

            # Fallback: identify PSD line by colour if linestyle search failed.
            if main_line is None:
                for line in lines:
                    color = line.get_color()
                    if color in ('black', 'k'):
                        main_line = line
                        break

            subplot_y_max = 0.0

            # --- Primary contribution: the PSD line itself ---
            if main_line is not None:
                freqs_data = main_line.get_xdata()
                power_data = main_line.get_ydata()
                visible_mask = (freqs_data >= x_min) & (freqs_data <= x_max)
                visible_power = power_data[visible_mask]
                if visible_power.size > 0:
                    subplot_y_max = float(np.max(visible_power))

            # --- Secondary contribution: CI upper bound (capped) ---
            # Include the upper CI line in the scaling so that tight CIs
            # (e.g. Welch with many segments) don't get clipped.  Wide CIs
            # (e.g. Lomb-Scargle, short CARSPAN) are capped at 3× the PSD
            # peak to prevent them from blowing out the y-axis.
            if dashed_lines and subplot_y_max > 0.0:
                ci_cap = subplot_y_max * 3.0  # Never scale beyond 3× the PSD peak.
                for dline in dashed_lines:
                    ci_freqs = dline.get_xdata()
                    ci_vals = dline.get_ydata()
                    ci_mask = (ci_freqs >= x_min) & (ci_freqs <= x_max)
                    ci_visible = ci_vals[ci_mask]
                    if ci_visible.size > 0:
                        ci_contribution = min(float(np.max(ci_visible)), ci_cap)
                        if ci_contribution > subplot_y_max:
                            subplot_y_max = ci_contribution

            if subplot_y_max > y_max:
                y_max = subplot_y_max

        # Pass 3: Apply uniform scaling with margin
        # Add 10% padding to the top (margins doesn't work well after set_ylim, so we calculate it)
        margin_factor = 0.1
        y_top = y_max * (1.0 + margin_factor)

        for subplot in subplots:
            subplot.ax.set_ylim(bottom=0.0, top=y_top)
            subplot.canvas.draw()

        scroll_area.setWidget(container)

        # Set up this widget's layout
        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Static plotting backend
    # ------------------------------------------------------------------

    @staticmethod
    def plot_on_axis(
        ax: Axes,
        series,
        *,
        logscale: bool = False,
        **kwargs,
    ) -> Axes:
        """
        Plot PSD with confidence-interval shading and frequency-band fills.

        The PSD estimate is obtained via ``series.psd()``, which returns a
        ``PSDResult`` already normalised to **mMI²/Hz** — regardless of
        the underlying method (Welch, Lomb-Scargle, CARSPAN, or
        CARSPAN-strict).  No method-specific conversion is needed here.

        Band-power values in the legend are computed via
        ``series.band_powers()``, which integrates the mMI²/Hz spectrum
        over each band using rectangular summation (CARSPAN Eq. 3.28).

        Confidence intervals are drawn as:
        - a light-grey ``fill_between`` shaded band
        - two thin dashed boundary lines for precise reading

        Band names, edges, and colours come from ``HRV_FREQUENCY_BANDS``.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            The target axes to draw on.
        series : CardioSeriesView (or compatible)
            Must provide ``psd()`` and ``band_powers()`` methods (inherited
            from ``CardioFrequencyMetricsMixin``).
        logscale : bool
            If True, use a logarithmic y-axis.
        **kwargs
            Currently unused; reserved for future options.

        Returns
        -------
        matplotlib.axes.Axes
            The axes that were drawn on.
        """
        cfm = _cfm()

        # ---- Fetch PSD (already in mMI²/Hz) ----------------------------
        result = series.psd(with_ci=True)

        freqs = np.asarray(result.freqs).ravel()
        power = np.asarray(result.power).ravel()

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

        # Unpack CI bounds (may be None if with_ci failed)
        has_ci = result.ci_lower is not None and result.ci_upper is not None
        if has_ci:
            ci_lo = np.asarray(result.ci_lower).ravel()
            ci_hi = np.asarray(result.ci_upper).ravel()

        # Unit labels — always mMI² from the mixin
        power_unit = "mMI²"
        psd_unit = result.unit  # "mMI²/Hz"

        # ---- X-axis: use the FullRange band if defined, else use band limits --
        if "FullRange" in cfm.HRV_FREQUENCY_BANDS:
            full_range = cfm.HRV_FREQUENCY_BANDS["FullRange"]
            x_min = full_range["low"]
            x_max = full_range["high"]
        else:
            x_min = min(s["low"] for s in cfm.HRV_FREQUENCY_BANDS.values())
            x_max = max(s["high"] for s in cfm.HRV_FREQUENCY_BANDS.values())
        ax.set_xlim(x_min, x_max)
        ax.autoscale(enable=False, axis="x")

        # ---- CI shading -------------------------------------------------
        if has_ci:
            ci_pct = int(round((1.0 - cfm.CI_ALPHA) * 100))
            ax.fill_between(
                freqs,
                ci_lo,
                ci_hi,
                color="gray",
                alpha=0.20,
                label=f"{ci_pct} % CI",
                zorder=1,
            )
            ax.plot(
                freqs,
                ci_lo,
                color="gray",
                lw=0.7,
                ls="--",
                alpha=0.55,
                zorder=2,
            )
            ax.plot(
                freqs,
                ci_hi,
                color="gray",
                lw=0.7,
                ls="--",
                alpha=0.55,
                zorder=2,
            )

        # ---- PSD line ---------------------------------------------------
        ax.plot(freqs, power, "k", lw=1.0, alpha=0.85, zorder=3)

        # ---- Frequency band fills and legend entries -----------------------
        # Compute all band powers in one call (mMI²)
        try:
            band_powers = series.band_powers()
            if not isinstance(band_powers, dict):
                band_powers = {}
        except Exception as e:
            # If band power computation fails, show legend without values
            print(f"Warning: Could not compute band powers: {e}")
            band_powers = {}

        for name, spec in cfm.HRV_FREQUENCY_BANDS.items():
            f0 = spec["low"]
            f1 = spec["high"]
            color = spec.get("color", "gray")
            alpha = spec.get("alpha", 0.35)  # Default alpha = 0.35, FullRange can override to 0.05
            bp_val = band_powers.get(name, np.nan)
            label_val = f"{bp_val:.4f}" if np.isfinite(bp_val) else "n/a"

            # Build the fill polygon for all bands (including FullRange with low alpha)
            mask = (freqs >= f0) & (freqs <= f1)

            # Number of PSD grid points that fall within this band's boundaries.
            # For CARSPAN this equals the display-grid point count reported by
            # the original CARSPAN output (e.g. 5 for Low, 8 for Mid, etc.).
            n_pts = int(np.sum(mask))

            p0 = np.interp(f0, freqs, power)
            p1 = np.interp(f1, freqs, power)
            f_band = np.concatenate(([f0], freqs[mask], [f1]))
            p_band = np.concatenate(([p0], power[mask], [p1]))

            ax.fill_between(
                f_band,
                0,
                p_band,
                color=color,
                alpha=alpha,
                label=f"{name}: {label_val} {power_unit} ({n_pts})",
                zorder=4 if name != "FullRange" else 0,  # FullRange behind other bands
            )

        # ---- Axes decoration --------------------------------------------
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel(f"PSD [{psd_unit}]")
        if logscale:
            ax.set_yscale("log")

        # Title reflects the active method
        method_label = result.method.replace("_", " ").capitalize()
        ax.set_title(
            f"PSD ({method_label})",
            fontsize=8,
            loc="left",
            color="dimgray",
        )
        ax.legend(loc="upper right", fontsize=7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        return ax
