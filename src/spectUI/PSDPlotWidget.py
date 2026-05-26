# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
PSD plotting widget for multiple CardioSeriesView objects.

Design
------
- ``PSDPlotWidget`` is a container holding one ``_SinglePSDPlot`` per epoch.
- PSD values are computed by ``series.psd()`` / ``series.band_powers()`` -
  which internally call the refactored ``compute_*_psd`` functions.  All
  plotting-specific decisions (x-limits, y-limits, CI shading, band fills,
  legend, titles) live in this widget.
- A single y-limit is shared across all plots so epochs are comparable; the
  y-max is computed from the PSD arrays themselves (no matplotlib line
  introspection).
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from platformdirs import user_documents_path

from spectHR.Tools.Logger import logger
from spectHR.analysis.psd._config import PsdMethod
from spectHR.analysis.psd._engine import PSDEngine
from spectHR.analysis.psd._band_power import band_power_rectangular
from spectHR.analysis.psd._config import _DEFAULT_PSD_METHOD
from spectUI.workSpace import psd_method_from_workspace
from spectUI._plot_smoothing import smooth3
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

from spectUI._uitools import show_export_summary
from spectUI.workSpace import get_export_dir

warnings.filterwarnings("ignore")

# Y-axis scaling ignores frequencies below this cutoff so VLF peaks
# (typically dominated by slow drift) don't squash the LF/HF detail.
Y_SCALE_F_MIN: float = 0.08

# Multiplicative step used when the user resizes the y-axis with the
# arrow keys.  ``Up`` shrinks y-max by this factor (zooms in vertically),
# ``Down`` grows it by the reciprocal - chosen so the two are symmetric
# and a few presses give a noticeable but not jarring change.
_Y_ZOOM_STEP_UP:   float = 0.80   # Up arrow   → y-max × 0.80  (zoom in)
_Y_ZOOM_STEP_DOWN: float = 1.25   # Down arrow → y-max × 1.25  (zoom out)
# Floor that prevents y-max from collapsing to zero on long Up presses.
_Y_TOP_FLOOR:      float = 1e-12

# File formats produced when the user saves the plots via PrintScreen.
# Both are vector / lossless and suitable for print-ready figures; the
# user can pick whichever their downstream pipeline prefers.
_EXPORT_FORMATS: tuple[str, ...] = ("pdf",)
# Default location used when no workspace is supplied - mirrors the
# ``OutputDirectory`` default in ``spectUI.workSpace._DEFAULT_WORKSPACE``.
_DEFAULT_EXPORT_DIR: Path = user_documents_path() / "spectHR" / "export"
# Characters not allowed in filenames on Windows (and friends elsewhere).
_FILENAME_BAD_CHARS = re.compile(r'[\\/:*?"<>|\s]+')


def _bands_from_workspace(workspace: Optional[Dict[str, Any]]) -> Dict[str, dict]:
    """Return the workspace's bands dict (dict-of-dicts) for plotting.

    The plotting helpers (``_band_bounds``, ``_band_draw_extents``,
    ``_draw_band_fill``) work on this raw dict form. A separate
    :class:`PsdMethod` is built from the same data and passed explicitly
    to ``PSDEngine.compute`` for the compute path.
    """
    if workspace is None:
        return {}
    return dict(
        (workspace.get("FrequencyAnalysis", {}) or {}).get("bands", {}) or {}
    )


def _ci_alpha_from_workspace(workspace: Optional[Dict[str, Any]]) -> float:
    """Read ``confidence_interval_alpha`` from the workspace, default 0.05."""
    if workspace is None:
        return 0.05
    fa = workspace.get("FrequencyAnalysis", {}) or {}
    return float(fa.get("confidence_interval_alpha", 0.05))


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




def _wants_smoothing(series, psd_method: Optional[PsdMethod], method_name: str) -> bool:
    """Decide whether to apply the 3-MA to a CARSPAN spectrum.

    Only the CARSPAN methods carry a ``smooth_for_display`` setting
    (it's a knob on :class:`CarspanOptions`). For Welch / Lomb-Scargle
    this returns False unconditionally - the plot widget never smooths
    those.
    """
    if method_name not in ("carspan", "carspan_strict"):
        return False
    active = psd_method
    if active is None:
        return False
    return bool(getattr(active.carspan, "smooth_for_display", False))


def _fetch(
    series, label: str, psd_method: Optional[PsdMethod] = None
) -> _PlotData:
    """Compute PSD and band powers for one series - never raises.

    ``psd_method`` is passed explicitly. The series carries no UI state.

    If the active method is CARSPAN and ``smooth_for_display`` is True,
    the plot widget applies the CARSPAN 3-point moving-average smoother
    here, locally - the compute layer is left un-smoothed so band-power
    integration runs on the raw periodogram (which is what Pascal does
    via ``PDSin_BCK``).
    """
    method = psd_method if psd_method is not None else _DEFAULT_PSD_METHOD

    try:
        result = PSDEngine(series).compute(method, with_ci=True)
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
        bp_result = PSDEngine(series).for_band_power(method)
        band_powers = {
            name: band_power_rectangular(bp_result.freqs, bp_result.power, band.low, band.high)
            for name, band in method.bands.items()
        }
    except Exception as e:
        print(f"Warning: band powers failed for {label}: {e}")
        band_powers = {}

    power = np.asarray(result.power).ravel()
    ci_lower = (
        np.asarray(result.ci_lower).ravel() if result.ci_lower is not None else None
    )
    ci_upper = (
        np.asarray(result.ci_upper).ravel() if result.ci_upper is not None else None
    )

    # Plot-only display smoothing for the CARSPAN methods.
    if _wants_smoothing(series, psd_method, result.method):
        power = smooth3(power)
        ci_lower = smooth3(ci_lower) if ci_lower is not None else None
        ci_upper = smooth3(ci_upper) if ci_upper is not None else None

    return _PlotData(
        label=label,
        freqs=np.asarray(result.freqs).ravel(),
        power=power,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        unit=result.unit,
        method=result.method,
        band_powers=band_powers,
    )


def _strip_per_hz(unit: str) -> str:
    """
    Drop a ``/Hz`` suffix from a PSD unit string, returning the band-power unit.

    Band power is the PSD integrated over a frequency band, so its unit
    is the PSD unit divided by Hz (i.e. the PSD unit string with the
    ``/Hz`` removed). Falls back to the original string if no ``/Hz``
    is present, so unconventional unit labels round-trip cleanly.
    """
    if not unit:
        return ""
    stripped = unit.strip()
    for suffix in ("/Hz", "/hz", " /Hz", " /hz"):
        if stripped.endswith(suffix):
            return stripped[: -len(suffix)].rstrip()
    return stripped


def _sanitize_filename(name: str) -> str:
    """
    Replace whitespace and filesystem-unsafe characters in *name* with ``_``.

    Used to build cross-platform filenames from dataset and epoch labels -
    e.g. ``"a #1"`` becomes ``"a_1"``, ``"rest / sit"`` becomes
    ``"rest_sit"``.  Trailing underscores and leading dots (which would
    otherwise hide files on Unix) are stripped.
    """
    cleaned = _FILENAME_BAD_CHARS.sub("_", name).strip("._")
    return cleaned


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

    Includes the upper CI bound up to 3× the PSD peak - so tight CIs
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
        *,
        bands: Optional[Dict[str, dict]] = None,
        ci_alpha: float = 0.05,
    ) -> None:
        super().__init__(parent)
        # facecolor='white' forces a white figure regardless of the Qt
        # system theme; without this, matplotlib follows its rcParams
        # default which can pick up a light grey on some platforms.
        self.canvas: FigureCanvas = FigureCanvas(
            Figure(figsize=(5, 4), facecolor="white")
        )
        self.ax: Axes = self.canvas.figure.add_subplot(111)
        self.ax.set_facecolor("white")
        # The QWidget surrounding the canvas would otherwise show the
        # system palette colour around the figure margins (visible as a
        # light-grey border). Force its background to white so the
        # subplot looks like a single white tile.
        self.setStyleSheet("background-color: white;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        PSDPlotWidget.plot_on_axis(
            self.ax, data, x_min, x_max,
            bands=bands or {}, ci_alpha=ci_alpha,
        )
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
        *,
        workspace: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(parent)

        # Extract the PsdMethod from the workspace and pass it explicitly
        # to every compute call - the series objects carry no UI state.
        bands_dict = _bands_from_workspace(workspace)
        ci_alpha = _ci_alpha_from_workspace(workspace)
        x_min, x_max, scale_min, scale_max = _band_bounds(bands_dict)
        psd_method: Optional[PsdMethod] = (
            psd_method_from_workspace(workspace) if workspace is not None else None
        )

        # One call to the PSD backends per series; compute y-max before drawing.
        plots: List[_PlotData] = [
            _fetch(series, label, psd_method=psd_method)
            for series, label in zip(series_list, labels)
        ]
        y_max = max((_y_max(p, scale_min, scale_max) for p in plots), default=0.0)
        y_top = y_max * 1.1 if y_max > 0 else 1.0

        # Remember the inputs so the keyboard handlers can build filenames
        # and rescale the linked y-axes after construction.
        self._labels: List[str] = list(labels)
        self._series_list: List = list(series_list)
        self._workspace: Optional[Dict[str, Any]] = workspace
        self._bands_dict: Dict[str, dict] = bands_dict
        self._ci_alpha: float = ci_alpha
        self._subplots: List[_SinglePSDPlot] = []
        self._y_top: float = max(float(y_top), _Y_TOP_FLOOR)

        # Build the scroll area + grid container. Both get a white
        # background so the 5-pixel gaps between subplots and the
        # scroll-area margins don't show through as system grey. Setting
        # the stylesheet on this widget alone propagates to its
        # descendants, but we set it on each level explicitly to avoid
        # any platform-specific quirks where stylesheet inheritance is
        # broken by a non-default palette on a child widget.
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
            subplot = _SinglePSDPlot(
                data, x_min, x_max, y_top,
                bands=bands_dict, ci_alpha=ci_alpha,
            )
            self._subplots.append(subplot)
            row, col = divmod(idx, 2)
            container_layout.addWidget(subplot, row, col)

        scroll_area.setWidget(container)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

        # Accept keyboard focus so the widget participates in the focus
        # chain (the QShortcut registrations below need that to be true).
        self.setFocusPolicy(Qt.StrongFocus)

        # Up / Down arrows go through QShortcut rather than keyPressEvent
        # because the inner QScrollArea consumes arrow keys for scrolling
        # before they can bubble up.  ``WidgetWithChildrenShortcut`` lets
        # the shortcut fire whenever focus is anywhere inside this widget.
        zoom_in = QShortcut(QKeySequence(Qt.Key_Up), self)
        zoom_in.setContext(Qt.WidgetWithChildrenShortcut)
        zoom_in.activated.connect(self._zoom_in)

        zoom_out = QShortcut(QKeySequence(Qt.Key_Down), self)
        zoom_out.setContext(Qt.WidgetWithChildrenShortcut)
        zoom_out.activated.connect(self._zoom_out)

        # Ctrl+P → save every subplot as print-ready vector files
        # (PDF + SVG) into the configured export directory.  The bare
        # PrintScreen key is intentionally NOT used: every major desktop
        # (Windows clipboard capture, GNOME / KDE screenshot tools,
        # macOS where the key barely exists) consumes that key before Qt
        # receives it, so QShortcut never fires.  Ctrl+P is the universal
        # "Print" gesture and is reliable cross-platform.
        save_all = QShortcut(QKeySequence("Shift+Ctrl+P"), self)
        save_all.setContext(Qt.WidgetWithChildrenShortcut)
        save_all.activated.connect(self._save_all_plots)

    # ------------------------------------------------------------------
    # Keyboard interaction - linked y-axis zoom across all subplots
    # ------------------------------------------------------------------

    def _zoom_in(self) -> None:
        """Up arrow: shrink the shared y-max (zoom in vertically)."""
        self._set_y_top(self._y_top * _Y_ZOOM_STEP_UP)

    def _zoom_out(self) -> None:
        """Down arrow: grow the shared y-max (zoom out vertically)."""
        self._set_y_top(self._y_top * _Y_ZOOM_STEP_DOWN)

    def _set_y_top(self, new_y_top: float) -> None:
        """
        Apply ``new_y_top`` to every linked subplot and redraw.

        Clipped to ``_Y_TOP_FLOOR`` so repeated Up presses can't collapse
        the axis to a zero-height range.
        """
        new_y_top = max(float(new_y_top), _Y_TOP_FLOOR)
        self._y_top = new_y_top
        for subplot in self._subplots:
            subplot.ax.set_ylim(bottom=0.0, top=new_y_top)
            subplot.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Print-ready export - PrintScreen saves every plot as PDF + SVG
    # ------------------------------------------------------------------

    def _save_all_plots(self) -> None:
        """
        Save every subplot to the export directory in vector formats.

        Output files are written to ``workspace["Directories"]["OutputDirectory"]``
        when a workspace was supplied at construction; otherwise the
        platformdirs default (``Documents/spectHR/export``) is used.

        For each subplot we emit one file per format in ``_EXPORT_FORMATS``
        (currently PDF and SVG - both vector, both lossless).  Existing
        files with the same name are silently overwritten so re-pressing
        PrintScreen during interactive y-axis tuning keeps a single set
        of fresh exports.
        """
        export_dir = self._resolve_export_dir()
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            msg = f"PSD export: could not create {export_dir!s}: {exc}"
            logger.warning(msg)
            QMessageBox.warning(self, "PSD export failed", msg)
            return

        prefix = self._dataset_prefix()
        n_saved = 0
        failures: list[str] = []
        for label, subplot in zip(self._labels, self._subplots):
            stem = self._build_filename_stem(prefix, label)
            for fmt in _EXPORT_FORMATS:
                path = export_dir / f"{stem}.{fmt}"
                try:
                    # ``bbox_inches="tight"`` trims excess whitespace; the
                    # figure DPI is irrelevant for vector formats but
                    # we keep the canvas's native size so the on-screen
                    # aspect ratio is preserved in the saved file.
                    subplot.canvas.figure.savefig(
                        path,
                        format=fmt,
                        bbox_inches="tight",
                    )
                    n_saved += 1
                except (OSError, ValueError) as exc:
                    fail_msg = f"failed to write {path!s}: {exc}"
                    failures.append(fail_msg)
                    logger.warning(f"PSD export: {fail_msg}")

        # Compose the same summary message the user sees in the log and the
        # message box, so the log file and the dialog stay in sync.
        summary = (
            f"PSD export: saved {n_saved} file(s) "
            f"({len(self._subplots)} plot(s) × {len(_EXPORT_FORMATS)} format(s)) "
            f"to {export_dir!s}"
        )
        logger.info(summary)

        # Show the dialog via the shared helper so all three
        # export-capable widgets present the same look-and-feel.
        show_export_summary(
            self, context="PSD", summary=summary, failures=failures,
        )

    def _resolve_export_dir(self) -> Path:
        """Pick the output directory from the workspace, or fall back to default.

        Delegates to :func:`spectUI.workSpace.get_export_dir` so the
        export-capable widgets (PSD, Profile, Parameters) share the same
        accessor and fallback rule.
        """
        return get_export_dir(self._workspace, context="PSD")

    def _dataset_prefix(self) -> str:
        """Best-effort dataset name extracted from the first view's PhysioData."""
        for series in self._series_list:
            pd = getattr(series, "_pd", None)
            basename = getattr(pd, "basename", None)
            if basename:
                return _sanitize_filename(str(basename))
        return "PSD"

    @staticmethod
    def _build_filename_stem(prefix: str, label: str) -> str:
        """``{prefix}_PSD_{label}`` with filesystem-unsafe characters scrubbed."""
        clean_label = _sanitize_filename(label) or "epoch"
        return f"{prefix}_PSD_{clean_label}"

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
        bands: Optional[Dict[str, dict]] = None,
        ci_alpha: float = 0.05,
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
        bands : dict, optional
            Workspace bands dict (dict-of-dicts). Used to draw the
            named-band fills and their legend entries.
        ci_alpha : float
            Confidence-interval significance level used by the series'
            PSD computation; drives the ``"NN % CI"`` legend label.
        logscale : bool
            If True, use a logarithmic y-axis.
        """
        bands = bands or {}

        if data.error is not None or data.freqs.size == 0:
            msg = data.error or "Insufficient data"
            ax.text(
                0.5,
                0.5,
                msg,
                ha="center",
                va="center",
                transform=ax.transAxes,
                color="gray",
            )
            return ax

        ax.set_xlim(x_min, x_max)
        ax.autoscale(enable=False, axis="x")

        # ---- Confidence-interval shading -------------------------------
        if data.ci_lower is not None and data.ci_upper is not None:
            ci_pct = int(round((1.0 - ci_alpha) * 100))
            ax.fill_between(
                data.freqs,
                data.ci_lower,
                data.ci_upper,
                color="gray",
                alpha=0.20,
                label=f"{ci_pct} % CI",
                zorder=1,
            )
            for ci_line in (data.ci_lower, data.ci_upper):
                ax.plot(
                    data.freqs,
                    ci_line,
                    color="gray",
                    lw=0.7,
                    ls="--",
                    alpha=0.55,
                    zorder=2,
                )

        # ---- PSD line --------------------------------------------------
        ax.plot(data.freqs, data.power, "k", lw=1.0, alpha=0.85, zorder=3)

        # ---- Frequency-band fills + legend -----------------------------
        # Band power has the dimension of the PSD integrated over Hz, so
        # the unit is the PSD unit minus the "/Hz" suffix. ``data.unit``
        # already reflects the workspace ``plot_units`` choice ("mMI²/Hz"
        # or "ms²/Hz" for CARSPAN, the units workspace key for Welch /
        # Lomb-Scargle), so the legend stays in sync automatically.
        power_unit = _strip_per_hz(data.unit)
        draw_extents = _band_draw_extents(bands)
        for name, spec in bands.items():
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
    adjacent band so the fills meet visually - but the band-power
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
    label_val = f"{bp_val:.1f}" if np.isfinite(bp_val) else "n/a"

    # Point count uses the *configured* band (so it matches the integrated power).
    n_pts = int(np.sum((data.freqs >= f0) & (data.freqs <= f1)))

    # The drawn polygon spans [draw_low, draw_high] so adjacent fills meet.
    fill_mask = (data.freqs >= draw_low) & (data.freqs <= draw_high)
    p_lo = np.interp(draw_low, data.freqs, data.power)
    p_hi = np.interp(draw_high, data.freqs, data.power)
    f_band = np.concatenate(([draw_low], data.freqs[fill_mask], [draw_high]))
    p_band = np.concatenate(([p_lo], data.power[fill_mask], [p_hi]))

    ax.fill_between(
        f_band,
        0,
        p_band,
        color=color,
        alpha=alpha,
        label=f"{name}: {label_val} {power_unit} ({n_pts})",
        zorder=4 if name != "FullRange" else 0,
    )
