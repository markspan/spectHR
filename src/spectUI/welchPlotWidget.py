"""
PSD plotting widget for CardioSeriesView objects.

This module provides:
- A QWidget that embeds a Matplotlib figure
- A pure plotting backend for the active PSD method
  (Welch, Lomb-Scargle, CARSPAN, or CARSPAN-strict)
- A static probing utility to normalise axes across multiple epochs

Design principles
-----------------
- The widget knows *nothing* about epochs or datasets.
- Input is always a CardioSeriesView (or compatible interface) that
  inherits from ``CardioFrequencyMetricsMixin``.
- Band definitions (edges, names, colours) are read from
  ``HRV_FREQUENCY_BANDS`` in ``CardioFrequencyMetricsMixin`` — the
  single source of truth for frequency analysis.
- The PSD method (welch / lombscargle / carspan / carspan_strict) is
  read from the module-level ``METHOD`` constant in
  ``CardioFrequencyMetricsMixin``, set at startup from the workspace JSON.
- All PSD results are returned as ``PSDResult`` objects in **mMI²/Hz** —
  the mixin handles unit conversion internally, so the plot code needs
  no method-specific normalisation logic.
"""

from __future__ import annotations

import warnings
from typing import Iterable, Tuple
import sys as _sys

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy

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


class WelchPSDPlotWidget(QWidget):
    """
    Qt widget for displaying a Power Spectral Density (PSD) plot.

    The widget is intentionally lightweight:
    - It embeds a single Matplotlib Axes.
    - It delegates all numerical work to the ``CardioFrequencyMetricsMixin``
      methods on the series object (``series.psd()`` and
      ``series.band_powers()``).
    - It can be stacked vertically in a scroll area.

    Band names, frequency edges, and fill colours are taken from
    ``HRV_FREQUENCY_BANDS`` (``CardioFrequencyMetricsMixin``), populated
    at startup from the workspace JSON ``FrequencyAnalysis`` section.

    The PSD method is determined by the module-level ``METHOD`` constant
    (also set from the workspace).  No extra configuration is needed in
    the widget itself.
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

        Creates throw-away Axes, plots each series, and collects the
        resulting y-limits.  Only axes with valid plotted data contribute.

        Parameters
        ----------
        series_list : Iterable
            CardioSeriesView (or compatible) objects.
        **plot_kwargs
            Forwarded to :meth:`plot_on_axis`.

        Returns
        -------
        tuple of (float, float)
            ``(y_min, y_max)`` suitable for ``ax.set_ylim()``.
        """
        ymaxs: list[float] = []

        for series in series_list:
            fig = Figure(figsize=(5, 3))
            ax = fig.add_subplot(111)
            WelchPSDPlotWidget.plot_on_axis(ax, series, **plot_kwargs)
            y0, y1 = ax.get_ylim()

            # Skip degenerate / uninitialised axes
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

        # ---- X-axis: span exactly the configured bands ------------------
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

        # ---- Frequency band fills ---------------------------------------
        # Compute all band powers in one call (mMI²)
        band_powers = series.band_powers()

        for name, spec in cfm.HRV_FREQUENCY_BANDS.items():
            f0 = spec["low"]
            f1 = spec["high"]
            color = spec.get("color", "gray")

            # Build the fill polygon for this band
            mask = (freqs >= f0) & (freqs <= f1)
            p0 = np.interp(f0, freqs, power)
            p1 = np.interp(f1, freqs, power)
            f_band = np.concatenate(([f0], freqs[mask], [f1]))
            p_band = np.concatenate(([p0], power[mask], [p1]))

            # Band-power label from the mixin (already in mMI²)
            bp_val = band_powers.get(name, np.nan)
            label_val = f"{bp_val:.4f}" if np.isfinite(bp_val) else "n/a"

            ax.fill_between(
                f_band,
                0,
                p_band,
                color=color,
                alpha=0.35,
                label=f"{name}: {label_val} {power_unit}",
                zorder=4,
            )

        # ---- Axes decoration --------------------------------------------
        ax.set_ylim(bottom=0.0)
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

    # ------------------------------------------------------------------
    # Instance-level convenience wrapper
    # ------------------------------------------------------------------

    def plot(self, series, **kwargs) -> None:
        """Clear the internal axis and plot a PSD for a CardioSeriesView."""
        self.ax.clear()
        self.plot_on_axis(self.ax, series, **kwargs)
        self.canvas.draw()
