"""
PSD plotting widget for CardioSeriesView objects.

This module provides:
- A QWidget that embeds a Matplotlib figure
- A pure plotting backend for the active PSD method
  (Welch, Lomb-Scargle, or CARSPAN)
- A static probing utility to normalise axes across multiple epochs

Design principles
-----------------
- The widget knows *nothing* about epochs or datasets
- Input is always a CardioSeriesView (or compatible interface)
- Band definitions (edges, names, colours) are read from HRV_FREQUENCY_BANDS
  in CardioMetricsMixin — the single source of truth for frequency analysis
- The PSD method (welch / lombscargle / carspan) is read from the
  module-level METHOD constant in CardioMetricsMixin, set at startup from
  the workspace JSON

CARSPAN mode
------------
When METHOD == "carspan":
- The raw spectrum from psd_with_ci() is in ms²/Hz
- It is converted to mMI²/Hz for display by dividing by mean_IBI_ms²
  and multiplying by 1 000 000 (CARSPAN manual §3.3.4, formula 3.20)
- Band power labels and y-axis are annotated with "mMI²" accordingly
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

from spectHR.DataSet.Series.CardioMetricsMixin import HRV_FREQUENCY_BANDS

warnings.filterwarnings("ignore")


def _cm():
    """Return the CardioMetricsMixin module (avoids circular import)."""
    return _sys.modules["spectHR.DataSet.Series.CardioMetricsMixin"]


class WelchPSDPlotWidget(QWidget):
    """
    Qt widget for displaying a Power Spectral Density (PSD) plot.

    The widget is intentionally lightweight:
    - It embeds a single Matplotlib Axes
    - It delegates all numerical work to static helper methods
    - It can be stacked vertically in a scroll area

    Band names, frequency edges, and fill colours are taken from
    HRV_FREQUENCY_BANDS (CardioMetricsMixin), populated at startup from
    the workspace JSON FrequencyAnalysis section.

    The PSD method (welch / lombscargle / carspan) is determined by the
    module-level METHOD constant (also set from the workspace).
    No extra configuration is needed in the widget itself.
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
            ax  = fig.add_subplot(111)
            WelchPSDPlotWidget.plot_on_axis(ax, series, **plot_kwargs)
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
        logscale: bool = False,
        **kwargs,
    ) -> Axes:
        """
        Plot PSD with confidence-interval shading and frequency-band fills on ax.

        The PSD estimate is obtained via ``series.psd_with_ci()``, which
        dispatches to Welch, Lomb-Scargle, or CARSPAN according to the
        workspace-configured METHOD constant.

        When METHOD == "carspan", the spectrum (ms²/Hz) is scaled to
        mMI²/Hz for display using the CARSPAN normalisation:
            psd_display = psd_ms2 / mean_IBI_ms² × 1 000 000
        Band-power values in the legend are similarly in mMI².
        For all other methods, units remain ms²/Hz and ms² respectively.

        Confidence intervals are drawn as:
        - a light-grey ``fill_between`` shaded band
        - two thin dashed boundary lines for precise reading

        Band names, edges, and colours come from HRV_FREQUENCY_BANDS.
        """
        cm = _cm()

        # ---- Fetch spectrum (always in ms²/Hz) -------------------------
        # Note: only Welch accepts fs; drop it for other methods.
        welch_only_kwargs = {}
        if cm.METHOD == "welch":
            welch_only_kwargs = {k: v for k, v in kwargs.items() if k == "fs"}

        freqs, power, ci_lo, ci_hi = series.psd_with_ci(**welch_only_kwargs)

        freqs = np.asarray(freqs).ravel()
        power = np.asarray(power).ravel()
        ci_lo = np.asarray(ci_lo).ravel()
        ci_hi = np.asarray(ci_hi).ravel()

        if freqs.size == 0:
            ax.text(
                0.5, 0.5, "Insufficient data",
                ha="center", va="center",
                transform=ax.transAxes,
                color="gray",
            )
            return ax

        # ---- CARSPAN normalisation for display -------------------------
        # psd_with_ci() always returns ms²/Hz. For the CARSPAN method we
        # convert to mMI²/Hz here so the plot matches CARSPAN output.
        is_carspan = (cm.METHOD == "carspan")
        if is_carspan:
            ibi_ms = series._ibi_clean_ms()
            if ibi_ms.size > 0:
                mean_ibi_sec = float(np.mean(ibi_ms)) / 1000.0
                if mean_ibi_sec > 0:
                    # S'(fk) = S(fk) / mean_HR² * 1e6 = S(fk) * mean_IBI_sec² * 1e6
                    scale = (mean_ibi_sec ** 2) * 1_000_000.0
                    power = power * scale
                    ci_lo = ci_lo * scale
                    ci_hi = ci_hi * scale
            power_unit  = "mMI²"
            psd_unit    = "mMI²/Hz"
        else:
            power_unit  = "ms²"
            psd_unit    = "ms²/Hz"

        # Set x-axis to span exactly the band range — no empty space
        # before the first band or after the last.
        x_min = min(s["low"]  for s in HRV_FREQUENCY_BANDS.values())
        x_max = max(s["high"] for s in HRV_FREQUENCY_BANDS.values())
        ax.set_xlim(x_min, x_max)
        ax.autoscale(enable=False, axis="x")

        # ---- CI shading ------------------------------------------------
        ci_pct = int(round((1.0 - cm.CI_ALPHA) * 100))
        ax.fill_between(
            freqs, ci_lo, ci_hi,
            color="gray", alpha=0.20,
            label=f"{ci_pct} % CI",
            zorder=1,
        )
        ax.plot(freqs, ci_lo, color="gray", lw=0.7, ls="--", alpha=0.55, zorder=2)
        ax.plot(freqs, ci_hi, color="gray", lw=0.7, ls="--", alpha=0.55, zorder=2)

        # ---- PSD line --------------------------------------------------
        ax.plot(freqs, power, "k", lw=1.0, alpha=0.85, zorder=3)

        # ---- Frequency band fills --------------------------------------
        # Band-power values for the legend are obtained by calling the same
        # metric methods that parametersPlotWidget uses (via hrv_epoch_table).
        # This guarantees the legend values are always identical to the
        # parameter table, regardless of method or normalisation.
        band_metric_map = {
            name: getattr(series, name.lower() + "_power", None)
            for name in HRV_FREQUENCY_BANDS
        }

        for name, spec in HRV_FREQUENCY_BANDS.items():
            f0    = spec["low"]
            f1    = spec["high"]
            color = spec.get("color", "gray")

            mask   = (freqs >= f0) & (freqs <= f1)
            p0     = np.interp(f0, freqs, power)
            p1     = np.interp(f1, freqs, power)
            f_band = np.concatenate(([f0], freqs[mask], [f1]))
            p_band = np.concatenate(([p0], power[mask], [p1]))

            # Use the metric method for the label value — same as param table
            metric_fn  = band_metric_map.get(name)
            band_power = metric_fn() if callable(metric_fn) else np.nan
            label_val  = f"{band_power:.4f}" if np.isfinite(band_power) else "n/a"

            ax.fill_between(
                f_band, 0, p_band,
                color=color, alpha=0.35,
                label=f"{name}: {label_val} {power_unit}",
                zorder=4,
            )

        # ---- Axes decoration -------------------------------------------
        ax.set_ylim(bottom=0.0)
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel(f"PSD [{psd_unit}]")
        if logscale:
            ax.set_yscale("log")

        ax.set_title(
            f"PSD ({cm.METHOD.capitalize()})",
            fontsize=8, loc="left", color="dimgray",
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