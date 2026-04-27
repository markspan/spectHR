"""
PSD plotting widget for multiple CardioSeriesView objects.

Design
------
- ``PSDPlotWidget`` is a container holding one ``_SinglePSDPlot`` per epoch.
- PSD values are computed by ``series.psd()`` / ``series.band_powers()`` —
  which internally call the refactored ``compute_*_psd`` functions.  All
  plotting-specific decisions (x-limits, y-limits, CI shading, band fills,
  legend, titles) live in this widget.
- A single y-limit is shared across all plots so epochs are comparable; the
  y-max is computed from the PSD arrays themselves (no matplotlib line
  introspection).
"""

from __future__ import annotations

import sys as _sys
import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QGridLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

warnings.filterwarnings("ignore")

# Y-axis scaling ignores frequencies below this cutoff so VLF peaks
# (typically dominated by slow drift) don't squash the LF/HF detail.
Y_SCALE_F_MIN: float = 0.05


def _cfm():
    """
    Return the CardioFrequencyMetricsMixin module at call time.

    Lazy lookup so that ``METHOD``, ``CI_ALPHA`` and ``HRV_FREQUENCY_BANDS``
    reflect the latest workspace configuration, even after reloads.
    """
    return _sys.modules["spectHR.DataSet.Series.CardioFrequencyMetricsMixin"]


# ---------------------------------------------------------------------------
# Pre-computed plot data
# ---------------------------------------------------------------------------


@dataclass
class _PlotData:
    """Everything needed to draw one epoch's PSD plot."""

    label: str
    freqs: np.ndarray
    power: np.ndarray
    ci_lower: Optional[np.ndarray]
    ci_upper: Optional[np.ndarray]
    unit: str
    method: str
    band_powers: Dict[str, float]
    error: Optional[str] = None  # set if PSD could not be computed


def _fetch(series, label: str) -> _PlotData:
    """Call ``series.psd()`` and ``series.band_powers()`` — never raises."""
    try:
        result = series.psd(with_ci=True)
    except Exception as e:
        return _PlotData(
            label=label,
            freqs=np.array([]),
            power=np.array([]),
            ci_lower=None,
            ci_upper=None,
            unit="",
            method="",
            band_powers={},
            error=f"PSD failed: {e}",
        )

    try:
        band_powers = series.band_powers()
        if not isinstance(band_powers, dict):
            band_powers = {}
    except Exception as e:
        print(f"Warning: band powers failed for {label}: {e}")
        band_powers = {}

    return _PlotData(
        label=label,
        freqs=np.asarray(result.freqs).ravel(),
        power=np.asarray(result.power).ravel(),
        ci_lower=(
            np.asarray(result.ci_lower).ravel() if result.ci_lower is not None else None
        ),
        ci_upper=(
            np.asarray(result.ci_upper).ravel() if result.ci_upper is not None else None
        ),
        unit=result.unit,
        method=result.method,
        band_powers=band_powers,
    )


def _band_bounds(bands: dict) -> Tuple[float, float, float, float]:
    """
    Return ``(x_min, x_max, scale_min, scale_max)`` for display and scaling.

    X-axis uses ``FullRange`` if defined, else the union of all bands.
    Scaling range excludes ``FullRange`` so a wide overview band doesn't
    dominate the y-limit.
    """
    if "FullRange" in bands:
        x_min = bands["FullRange"]["low"]
        x_max = bands["FullRange"]["high"]
    else:
        x_min = min(s["low"] for s in bands.values())
        x_max = max(s["high"] for s in bands.values())

    named = {k: v for k, v in bands.items() if k != "FullRange"}
    if named:
        scale_min = min(s["low"] for s in named.values())
        scale_max = max(s["high"] for s in named.values())
    else:
        scale_min, scale_max = x_min, x_max

    return x_min, x_max, scale_min, scale_max


def _y_max(data: _PlotData, scale_min: float, scale_max: float) -> float:
    """
    Maximum PSD value in the scaling band range.

    Includes the upper CI bound up to 3× the PSD peak — so tight CIs
    (Welch) are respected but wide CIs (Lomb-Scargle, short CARSPAN) don't
    blow up the axis.  Frequencies below ``Y_SCALE_F_MIN`` are excluded
    so VLF drift power doesn't dominate the y-limit.
    """
    if data.freqs.size == 0:
        return 0.0

    lo = max(scale_min, Y_SCALE_F_MIN)
    visible = (data.freqs >= lo) & (data.freqs <= scale_max)
    if not np.any(visible):
        return 0.0

    peak = float(np.max(data.power[visible]))
    if data.ci_upper is not None and peak > 0.0:
        ci_peak = float(np.max(data.ci_upper[visible]))
        peak = max(peak, min(ci_peak, peak * 3.0))
    return peak


# ---------------------------------------------------------------------------
# Single-plot subwidget
# ---------------------------------------------------------------------------


class _SinglePSDPlot(QWidget):
    """One matplotlib figure displaying a single epoch's PSD."""

    def __init__(
        self,
        data: _PlotData,
        x_min: float,
        x_max: float,
        y_top: float,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.canvas: FigureCanvas = FigureCanvas(Figure(figsize=(5, 4)))
        self.ax: Axes = self.canvas.figure.add_subplot(111)
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        PSDPlotWidget.plot_on_axis(self.ax, data, x_min, x_max)
        self.ax.set_title(f"PSD – {data.label}")
        self.ax.set_ylim(bottom=0.0, top=max(y_top, 1e-12))
        self.canvas.draw()


# ---------------------------------------------------------------------------
# Container widget
# ---------------------------------------------------------------------------


class PSDPlotWidget(QWidget):
    """
    Grid of PSD plots (one per epoch) sharing a uniform y-limit.

    Parameters
    ----------
    series_list : list
        CardioSeriesView (or compatible) objects exposing ``psd()`` and
        ``band_powers()``.
    labels : list of str
        Plot titles (e.g., epoch names).
    parent : QWidget, optional
    """

    def __init__(
        self,
        series_list: List,
        labels: List[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        cfm = _cfm()
        x_min, x_max, scale_min, scale_max = _band_bounds(cfm.HRV_FREQUENCY_BANDS)

        # One call to the PSD backends per series; compute y-max before drawing.
        plots: List[_PlotData] = [
            _fetch(series, label) for series, label in zip(series_list, labels)
        ]
        y_max = max((_y_max(p, scale_min, scale_max) for p in plots), default=0.0)
        y_top = y_max * 1.1 if y_max > 0 else 1.0

        # Build the scroll area + grid container.
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        container = QWidget()
        container_layout = QGridLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(5)

        for idx, data in enumerate(plots):
            subplot = _SinglePSDPlot(data, x_min, x_max, y_top)
            row, col = divmod(idx, 2)
            container_layout.addWidget(subplot, row, col)

        scroll_area.setWidget(container)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Pure plotting backend
    # ------------------------------------------------------------------

    @staticmethod
    def plot_on_axis(
        ax: Axes,
        data: _PlotData,
        x_min: float,
        x_max: float,
        *,
        logscale: bool = False,
    ) -> Axes:
        """
        Draw PSD, CI shading, and band fills for a single epoch.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            Target axes.
        data : _PlotData
            Pre-computed PSD values, CI bounds, and band powers.
        x_min, x_max : float
            X-axis range (Hz).
        logscale : bool
            If True, use a logarithmic y-axis.
        """
        cfm = _cfm()

        if data.error is not None or data.freqs.size == 0:
            msg = data.error or "Insufficient data"
            ax.text(
                0.5, 0.5, msg,
                ha="center", va="center",
                transform=ax.transAxes, color="gray",
            )
            return ax

        ax.set_xlim(x_min, x_max)
        ax.autoscale(enable=False, axis="x")

        # ---- Confidence-interval shading -------------------------------
        if data.ci_lower is not None and data.ci_upper is not None:
            ci_pct = int(round((1.0 - cfm.CI_ALPHA) * 100))
            ax.fill_between(
                data.freqs, data.ci_lower, data.ci_upper,
                color="gray", alpha=0.20,
                label=f"{ci_pct} % CI", zorder=1,
            )
            for ci_line in (data.ci_lower, data.ci_upper):
                ax.plot(
                    data.freqs, ci_line,
                    color="gray", lw=0.7, ls="--", alpha=0.55, zorder=2,
                )

        # ---- PSD line --------------------------------------------------
        ax.plot(data.freqs, data.power, "k", lw=1.0, alpha=0.85, zorder=3)

        # ---- Frequency-band fills + legend -----------------------------
        power_unit = "mMI²"
        draw_extents = _band_draw_extents(cfm.HRV_FREQUENCY_BANDS)
        for name, spec in cfm.HRV_FREQUENCY_BANDS.items():
            d_lo, d_hi = draw_extents[name]
            _draw_band_fill(ax, data, name, spec, power_unit, d_lo, d_hi)

        # ---- Axes decoration -------------------------------------------
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel(f"PSD [{data.unit}]")
        if logscale:
            ax.set_yscale("log")

        method_label = data.method.replace("_", " ").capitalize()
        ax.set_title(
            f"PSD ({method_label})",
            fontsize=8, loc="left", color="dimgray",
        )
        ax.legend(loc="upper right", fontsize=7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        return ax


def _band_draw_extents(bands: dict) -> Dict[str, Tuple[float, float]]:
    """
    Return ``{name: (draw_low, draw_high)}`` extending fills to neighbour midpoints.

    With CARSPAN-style gapped bands (e.g. 0.06→0.07, 0.14→0.15) the
    polygon's ``low`` and ``high`` are pushed to the midpoint with the
    adjacent band so the fills meet visually — but the band-power
    *integration* still uses the configured edges (handled by the
    mixin).  ``FullRange`` keeps its own range.
    """
    items = sorted(
        ((n, s) for n, s in bands.items() if n != "FullRange"),
        key=lambda kv: kv[1]["low"],
    )
    extents: Dict[str, Tuple[float, float]] = {}
    for i, (name, spec) in enumerate(items):
        draw_low = spec["low"]
        draw_high = spec["high"]
        if i > 0:
            draw_low = (items[i - 1][1]["high"] + spec["low"]) / 2.0
        if i < len(items) - 1:
            draw_high = (spec["high"] + items[i + 1][1]["low"]) / 2.0
        extents[name] = (draw_low, draw_high)
    if "FullRange" in bands:
        extents["FullRange"] = (bands["FullRange"]["low"], bands["FullRange"]["high"])
    return extents


def _draw_band_fill(
    ax: Axes,
    data: _PlotData,
    name: str,
    spec: dict,
    power_unit: str,
    draw_low: float,
    draw_high: float,
) -> None:
    """Fill one frequency band under the PSD curve + add a legend entry."""
    f0, f1 = spec["low"], spec["high"]
    color = spec.get("color", "gray")
    alpha = spec.get("alpha", 0.35)
    bp_val = data.band_powers.get(name, np.nan)
    label_val = f"{bp_val:.4f}" if np.isfinite(bp_val) else "n/a"

    # Point count uses the *configured* band (so it matches the integrated power).
    n_pts = int(np.sum((data.freqs >= f0) & (data.freqs <= f1)))

    # The drawn polygon spans [draw_low, draw_high] so adjacent fills meet.
    fill_mask = (data.freqs >= draw_low) & (data.freqs <= draw_high)
    p_lo = np.interp(draw_low, data.freqs, data.power)
    p_hi = np.interp(draw_high, data.freqs, data.power)
    f_band = np.concatenate(([draw_low], data.freqs[fill_mask], [draw_high]))
    p_band = np.concatenate(([p_lo], data.power[fill_mask], [p_hi]))

    ax.fill_between(
        f_band, 0, p_band,
        color=color, alpha=alpha,
        label=f"{name}: {label_val} {power_unit} ({n_pts})",
        zorder=4 if name != "FullRange" else 0,
    )
