"""
Spectral-profile plotting widget — sibling of :class:`PSDPlotWidget`.

A *profile* is the time course of a band-power measure inside one epoch
(CARSPAN manual §3.3.5): the configured PSD is recomputed in a sliding
window along the epoch, and each band integrates to one curve over
time. Where :class:`PSDPlotWidget` shows the spectrum of an epoch,
:class:`ProfilePlotWidget` shows how each band-power evolves *within*
the epoch.

Design
------
- Mirrors :class:`PSDPlotWidget` end-to-end: one ``_SingleProfilePlot``
  per epoch, shared y-limit, arrow-key zoom, Shift+Ctrl+P export.
- Compute happens once per series via ``view.band_power_profile(...)``;
  this widget never touches a PSD function directly.
- Display is filtered by ``workspace["Profiles"]["bands"]`` — the
  compute may produce every band, but only the user-picked subset is
  drawn. Stale band names (e.g. left behind after a band rename) are
  silently skipped.
- Each trace is plotted as a line + a ``fill_between(y, 0)`` polygon
  using the workspace's band colour with transparency, matching the
  PSD-plot aesthetic.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from platformdirs import user_documents_path

from spectHR.Tools.Logger import logger
from spectHR.DataSet.Series.CardioMetricsMixin import PsdMethod
from spectUI._plot_smoothing import ma3
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


# Y-axis zoom step and floor — identical contract to PSDPlotWidget so
# the keyboard interaction feels uniform across the two plot tabs.
_Y_ZOOM_STEP_UP:   float = 0.80   # Up    → y-max × 0.80   (zoom in)
_Y_ZOOM_STEP_DOWN: float = 1.25   # Down  → y-max × 1.25   (zoom out)
_Y_TOP_FLOOR:      float = 1e-12

# File formats produced when the user saves the plots via Shift+Ctrl+P.
_EXPORT_FORMATS: tuple[str, ...] = ("pdf",)
_DEFAULT_EXPORT_DIR: Path = user_documents_path() / "spectHR" / "export"
_FILENAME_BAD_CHARS = re.compile(r'[\\/:*?"<>|\s]+')


# ---------------------------------------------------------------------------
# Workspace helpers — kept local so this widget has no spectUI cross-deps
# ---------------------------------------------------------------------------


def _bands_from_workspace(workspace: Optional[Dict[str, Any]]) -> Dict[str, dict]:
    """Return the workspace's bands dict (band-name → ``{low, high, color, alpha}``).

    The compute layer cares about the frequency edges; the plot widget
    uses the same dict for colour / alpha lookups when drawing the
    per-band traces. Mirrors :func:`PSDPlotWidget._bands_from_workspace`.
    """
    if workspace is None:
        return {}
    return dict(
        (workspace.get("FrequencyAnalysis", {}) or {}).get("bands", {}) or {}
    )


def _profile_settings_from_workspace(
    workspace: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return ``workspace["Profiles"]`` with sensible defaults.

    ``bands`` defaults to the *non-FullRange* named bands; ``window_s``
    and ``step_s`` come from the CARSPAN manual's typical profile
    settings; ``smooth_for_display`` defaults to ``False`` (the
    Delphi-faithful behaviour — the reference profile view plots the
    raw band-power-per-window line). Flip to ``True`` in Profile
    Settings for a softened curve.

    Workspace JSON exposes the time fields as the user-facing
    ``"window (sec)"`` / ``"step (sec)"`` keys (so the Edit-Parameters
    dialog labels them in a way researchers recognise from the CARSPAN
    manual). The old snake_case ``"window_s"`` / ``"step_s"`` spellings
    are still accepted as a fallback so older workspace JSON files
    don't blow up after upgrade.
    """
    if workspace is None:
        return {
            "window_s": 30.0, "step_s": 5.0, "bands": [],
            "smooth_for_display": False,
        }
    profs = workspace.get("Profiles", {}) or {}
    window_s = profs.get("window (sec)", profs.get("window_s", 30.0))
    step_s   = profs.get("step (sec)",   profs.get("step_s",   5.0))
    return {
        "window_s": float(window_s),
        "step_s":   float(step_s),
        "bands":    list(profs.get("bands", []) or []),
        "smooth_for_display": bool(profs.get("smooth_for_display", False)),
    }


def _sanitize_filename(name: str) -> str:
    """Same as ``PSDPlotWidget._sanitize_filename`` — kept local to avoid coupling."""
    return _FILENAME_BAD_CHARS.sub("_", name).strip("._")


# ---------------------------------------------------------------------------
# Pre-computed plot data
# ---------------------------------------------------------------------------


@dataclass
class _ProfilePlotData:
    """Everything needed to draw one epoch's profile plot."""

    label: str
    timestamps: np.ndarray            # shape (n_windows,)
    band_names: List[str]             # length n_bands
    band_power: np.ndarray            # shape (n_bands, n_windows)
    unit: str
    method: str
    window_s: float
    step_s: float
    error: Optional[str] = None


def _fetch_profile(
    series,
    label: str,
    *,
    window_s: float,
    step_s: float,
    psd_method: Optional[PsdMethod] = None,
    smooth: bool = False,
) -> _ProfilePlotData:
    """Call ``series.band_power_profile()`` — never raises.

    Failures (epoch too short, no PSD method set, etc.) come back as a
    ``_ProfilePlotData`` with ``error`` populated so the renderer can
    show a placeholder instead of leaving an empty tile in the grid.

    When ``smooth`` is True, the same Pascal-faithful 3-point MA the
    PSD widget applies to spectra is applied here along the *time*
    axis of each band's profile. The smoother lives in the plot layer
    only — the compute returns un-smoothed values so band-power
    statistics over the profile (mean, peak time, etc.) computed by
    downstream code keep their actual numerical values.
    """
    try:
        result = series.band_power_profile(
            window_s=window_s,
            step_s=step_s,
            psd_method=psd_method,
        )
    except Exception as e:
        return _ProfilePlotData(
            label=label,
            timestamps=np.array([]),
            band_names=[],
            band_power=np.empty((0, 0)),
            unit="",
            method="",
            window_s=window_s,
            step_s=step_s,
            error=f"Profile failed: {e}",
        )

    band_power = np.asarray(result.band_power)
    if smooth and band_power.size:
        # Apply ``ma3`` per band row (along the time axis). NaN windows
        # in the raw profile would otherwise propagate through the
        # rolling mean; replacing NaN with 0 before smoothing trades
        # a small bias at the gap for a continuous-looking curve.
        # Same trade-off the CARSPAN spectrum smoother makes.
        smoothed = np.empty_like(band_power, dtype=np.float64)
        for i in range(band_power.shape[0]):
            row = band_power[i]
            row_clean = np.where(np.isfinite(row), row, 0.0)
            smoothed[i] = ma3(row_clean)
        band_power = smoothed

    return _ProfilePlotData(
        label=label,
        timestamps=np.asarray(result.timestamps).ravel(),
        band_names=list(result.band_names),
        band_power=band_power,
        unit=result.unit,
        method=result.method,
        window_s=float(result.window_s),
        step_s=float(result.step_s),
    )


# Band-power profiles are notoriously spiky — one outlier window inside
# a CARSPAN-strict epoch can be 10×+ the typical peak. Scaling the
# y-axis to the absolute max therefore squashes the bulk of the curve
# into a flat band along the bottom of the plot. We use a high
# percentile across the plotted bands instead, with a small headroom
# factor on top. The user can still ↓-arrow to zoom out and see the
# outliers, or ↑-arrow to zoom further in.
_AUTOSCALE_PERCENTILE: float = 97.0
_AUTOSCALE_HEADROOM:   float = 1.20


def _y_max(data: _ProfilePlotData, bands_to_plot: List[str]) -> float:
    """Robust y-max estimate across the plotted bands (for shared y-limit).

    Returns the *97th-percentile* band-power value (across every
    plotted-band window in the epoch) — a sensible default that shows
    the bulk of the curve without an outlier window dominating the
    axis. Excludes bands not in *bands_to_plot* so the y-scale tracks
    the user's actual selection.

    The caller applies a headroom multiplier (``_AUTOSCALE_HEADROOM``)
    on top of this value so the curve doesn't graze the top of the
    plot area.
    """
    if data.band_power.size == 0:
        return 0.0
    rows = [
        data.band_power[data.band_names.index(name)]
        for name in bands_to_plot
        if name in data.band_names
    ]
    if not rows:
        return 0.0
    arr = np.concatenate(rows)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0
    # Single-value series shouldn't blow up; np.percentile handles it,
    # but make the intent explicit so degenerate epochs (constant-value
    # band) still get a sensible y_top.
    if finite.size == 1:
        return float(finite[0])
    return float(np.percentile(finite, _AUTOSCALE_PERCENTILE))


# ---------------------------------------------------------------------------
# Single-plot subwidget
# ---------------------------------------------------------------------------


class _SingleProfilePlot(QWidget):
    """One matplotlib figure showing a single epoch's profile."""

    def __init__(
        self,
        data: _ProfilePlotData,
        y_top: float,
        parent: Optional[QWidget] = None,
        *,
        bands: Optional[Dict[str, dict]] = None,
        bands_to_plot: Optional[List[str]] = None,
    ) -> None:
        super().__init__(parent)
        # Same white-figure / white-widget combo as PSDPlotWidget so the
        # two grids match visually.
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

        ProfilePlotWidget.plot_on_axis(
            self.ax,
            data,
            bands=bands or {},
            bands_to_plot=bands_to_plot or [],
        )
        self.ax.set_title(f"Profile – {data.label}")
        self.ax.set_ylim(bottom=0.0, top=max(y_top, _Y_TOP_FLOOR))
        self.canvas.draw()


# ---------------------------------------------------------------------------
# Container widget
# ---------------------------------------------------------------------------


class ProfilePlotWidget(QWidget):
    """Grid of profile plots (one per epoch) sharing a uniform y-limit.

    Parameters
    ----------
    series_list : list
        CardioSeriesView (or compatible) objects exposing
        ``band_power_profile()``.
    labels : list of str
        Plot titles (epoch names).
    workspace : dict, optional
        Used to read profile settings (``Profiles.window_s / step_s /
        bands``), band display attributes (``FrequencyAnalysis.bands``),
        and the export directory (``Directories.OutputDirectory``).
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

        # ---- workspace-driven configuration ---------------------------
        bands_dict = _bands_from_workspace(workspace)
        prof_cfg = _profile_settings_from_workspace(workspace)
        window_s: float = prof_cfg["window_s"]
        step_s:   float = prof_cfg["step_s"]
        smooth:   bool  = prof_cfg["smooth_for_display"]
        # Bands the user picked in Profile Settings, filtered against
        # the live universe so stale names from a band rename are dropped.
        bands_to_plot: List[str] = [
            name for name in prof_cfg["bands"] if name in bands_dict
        ]

        # ---- compute one profile per series ---------------------------
        plots: List[_ProfilePlotData] = [
            _fetch_profile(
                series, label,
                window_s=window_s, step_s=step_s, smooth=smooth,
            )
            for series, label in zip(series_list, labels)
        ]
        # Shared y-limit across all epoch subplots — keeps band-power
        # magnitudes directly comparable across epochs, which is the
        # whole point of plotting them side-by-side. The scale itself
        # is autoscaled to the cross-epoch 97th percentile (see
        # ``_y_max``) rather than the absolute max, so a single outlier
        # window in one epoch doesn't squash the rest. The ↑/↓ keys
        # remain available for manual fine-tuning.
        y_max = max(
            (_y_max(p, bands_to_plot) for p in plots), default=0.0,
        )
        y_top = y_max * _AUTOSCALE_HEADROOM if y_max > 0 else 1.0

        # Remember inputs for keyboard handlers and save-all path.
        self._labels: List[str] = list(labels)
        self._series_list: List = list(series_list)
        self._workspace: Optional[Dict[str, Any]] = workspace
        self._bands_dict: Dict[str, dict] = bands_dict
        self._bands_to_plot: List[str] = bands_to_plot
        self._subplots: List[_SingleProfilePlot] = []
        self._y_top: float = max(float(y_top), _Y_TOP_FLOOR)

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
            subplot = _SingleProfilePlot(
                data, y_top,
                bands=bands_dict, bands_to_plot=bands_to_plot,
            )
            self._subplots.append(subplot)
            row, col = divmod(idx, 2)
            container_layout.addWidget(subplot, row, col)

        scroll_area.setWidget(container)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

        # ---- keyboard interaction (same shortcuts as PSDPlotWidget) ---
        self.setFocusPolicy(Qt.StrongFocus)

        zoom_in = QShortcut(QKeySequence(Qt.Key_Up), self)
        zoom_in.setContext(Qt.WidgetWithChildrenShortcut)
        zoom_in.activated.connect(self._zoom_in)

        zoom_out = QShortcut(QKeySequence(Qt.Key_Down), self)
        zoom_out.setContext(Qt.WidgetWithChildrenShortcut)
        zoom_out.activated.connect(self._zoom_out)

        save_all = QShortcut(QKeySequence("Shift+Ctrl+P"), self)
        save_all.setContext(Qt.WidgetWithChildrenShortcut)
        save_all.activated.connect(self._save_all_plots)

    # ------------------------------------------------------------------
    # Keyboard — shared y-axis zoom
    # ------------------------------------------------------------------

    def _zoom_in(self) -> None:
        """Up arrow: shrink the shared y-max (zoom in)."""
        self._set_y_top(self._y_top * _Y_ZOOM_STEP_UP)

    def _zoom_out(self) -> None:
        """Down arrow: grow the shared y-max (zoom out)."""
        self._set_y_top(self._y_top * _Y_ZOOM_STEP_DOWN)

    def _set_y_top(self, new_y_top: float) -> None:
        """Apply ``new_y_top`` to every linked subplot and redraw."""
        new_y_top = max(float(new_y_top), _Y_TOP_FLOOR)
        self._y_top = new_y_top
        for subplot in self._subplots:
            subplot.ax.set_ylim(bottom=0.0, top=new_y_top)
            subplot.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Export — Shift+Ctrl+P writes every plot to the output directory
    # ------------------------------------------------------------------

    def _save_all_plots(self) -> None:
        export_dir = self._resolve_export_dir()
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            msg = f"Profile export: could not create {export_dir!s}: {exc}"
            logger.warning(msg)
            show_export_summary(
                self, context="Profile", summary=msg, failures=(msg,),
            )
            return

        prefix = self._dataset_prefix()
        n_saved = 0
        failures: list[str] = []
        for label, subplot in zip(self._labels, self._subplots):
            stem = self._build_filename_stem(prefix, label)
            for fmt in _EXPORT_FORMATS:
                path = export_dir / f"{stem}.{fmt}"
                try:
                    subplot.canvas.figure.savefig(
                        path, format=fmt, bbox_inches="tight",
                    )
                    n_saved += 1
                except (OSError, ValueError) as exc:
                    fail_msg = f"failed to write {path!s}: {exc}"
                    failures.append(fail_msg)
                    logger.warning(f"Profile export: {fail_msg}")

        summary = (
            f"Profile export: saved {n_saved} file(s) "
            f"({len(self._subplots)} plot(s) × {len(_EXPORT_FORMATS)} format(s)) "
            f"to {export_dir!s}"
        )
        logger.info(summary)
        show_export_summary(
            self, context="Profile", summary=summary, failures=failures,
        )

    def _resolve_export_dir(self) -> Path:
        """Delegated to ``workSpace.get_export_dir`` for cross-widget parity."""
        return get_export_dir(self._workspace, context="Profile")

    def _dataset_prefix(self) -> str:
        for series in self._series_list:
            pd = getattr(series, "_pd", None)
            basename = getattr(pd, "basename", None)
            if basename:
                return _sanitize_filename(str(basename))
        return "Profile"

    @staticmethod
    def _build_filename_stem(prefix: str, label: str) -> str:
        clean_label = _sanitize_filename(label) or "epoch"
        return f"{prefix}_Profile_{clean_label}"

    # ------------------------------------------------------------------
    # Pure plotting backend
    # ------------------------------------------------------------------

    @staticmethod
    def plot_on_axis(
        ax: Axes,
        data: _ProfilePlotData,
        *,
        bands: Optional[Dict[str, dict]] = None,
        bands_to_plot: Optional[List[str]] = None,
    ) -> Axes:
        """Draw one epoch's profile: filled traces for each chosen band.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            Target axes.
        data : _ProfilePlotData
            Pre-computed profile values for one epoch.
        bands : dict, optional
            Workspace bands dict (``{name: {color, alpha, low, high}}``).
            Drives the trace colour and fill alpha; missing entries fall
            back to a sensible default.
        bands_to_plot : list[str], optional
            Subset of ``data.band_names`` to draw. Empty / ``None`` ⇒
            draw every band the profile carries.
        """
        bands = bands or {}
        if not bands_to_plot:
            bands_to_plot = list(data.band_names)

        # Error / empty path — show a centred placeholder.
        if data.error is not None or data.timestamps.size == 0:
            msg = data.error or "No profile data"
            ax.text(
                0.5, 0.5, msg,
                ha="center", va="center",
                transform=ax.transAxes, color="gray",
            )
            return ax

        # X-axis — measure time from the start of the epoch (the
        # ``timestamps`` array carries absolute R-peak times, but the
        # plot is easier to read in epoch-relative seconds).
        t0 = float(data.timestamps[0]) - data.window_s / 2.0
        t_rel = data.timestamps - t0
        ax.set_xlim(0.0, float(t_rel[-1] + data.window_s / 2.0))

        # ---- per-band traces: line + fill_between to y=0 -------------
        for name in bands_to_plot:
            if name not in data.band_names:
                continue
            row = data.band_power[data.band_names.index(name)]
            spec = bands.get(name, {})
            color = spec.get("color", "gray")
            # ``alpha`` is used for the fill only; the line itself stays
            # opaque so peaks are still legible when bands overlap.
            fill_alpha = float(spec.get("alpha", 0.35))
            ax.fill_between(
                t_rel, 0.0, np.where(np.isfinite(row), row, 0.0),
                color=color, alpha=fill_alpha, zorder=2,
            )
            ax.plot(
                t_rel, row,
                color=color, lw=1.2, alpha=0.95,
                label=name, zorder=3,
            )

        # ---- axes decoration ----------------------------------------
        ax.set_xlabel("Time within epoch [s]")
        ax.set_ylabel(
            f"Band power [{data.unit}]" if data.unit else "Band power",
        )

        # Subtitle carries only the PSD method that drove the per-window
        # band-power integration — the window / step parameters are
        # workspace settings the user already controls explicitly, no
        # need to repeat them in every subplot annotation.
        method_label = data.method.replace("_", " ").capitalize()
        ax.set_title(
            f"Profile ({method_label})",
            fontsize=8, loc="left", color="dimgray",
        )
        ax.legend(loc="upper right", fontsize=7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        return ax
