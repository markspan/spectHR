# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
import mplcursors
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.patches import Ellipse
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import spectHR as cs
from spectHR.DataSet.PhysioData import PhysioData
from spectHR.analysis.time_metrics import sd1, sd2


class PoincarePlotWidget(QWidget):
    """
    Poincare plot widget with epoch-based visibility control.

    Each epoch is rendered as:
    - a scatter of IBI[n] vs IBI[n+1]
    - an SD1/SD2 ellipse

    Visibility is controlled by checkboxes and stored directly
    in `dataset.epochs[epoch_name].active`.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

        self.dataset: PhysioData | None = None
        self.scatter_handles: dict[str, Any] = {}
        self.ellipse_handles: dict[str, Ellipse] = {}
        self.epoch_checkboxes: dict[str, QCheckBox] = {}
        self.cursor = None

        # Matplotlib figure
        self.fig, self.ax = plt.subplots(figsize=(6, 6))
        plt.close(self.fig)  # prevent orphan figure window
        self.canvas = FigureCanvas(self.fig)

        # --- layout ----------------------------------------------------
        main_layout = QHBoxLayout(self)
        self.setLayout(main_layout)

        plot_frame = QFrame()
        plot_layout = QVBoxLayout(plot_frame)
        plot_layout.addWidget(self.canvas)
        main_layout.addWidget(plot_frame, stretch=3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.checkbox_container = QWidget()
        self.checkbox_layout = QVBoxLayout(self.checkbox_container)
        scroll.setWidget(self.checkbox_container)
        main_layout.addWidget(scroll, stretch=1)

        self.setVisible(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def poincarePlot(self, dataset: PhysioData) -> None:
        """
        Render the Poincare plot for the given dataset.
        """
        self.dataset = dataset
        self.setVisible(True)
        self.setFocus()

        self._clear_ui()
        self._draw_plot()
        self._build_checkboxes()
        self._configure_axes()
        self._setup_cursor()

        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _clear_ui(self) -> None:
        """Clear axes, checkboxes, and stored handles."""
        self.ax.clear()
        self.scatter_handles.clear()
        self.ellipse_handles.clear()
        self.epoch_checkboxes.clear()

        while self.checkbox_layout.count():
            w = self.checkbox_layout.takeAt(0).widget()
            if w is not None:
                w.setParent(None)

    # Labels that mark an IBI as artefactual. Matches the convention used
    # by CardioFrequencyMetricsMixin (``_BAD_LABELS = ("TL", "T")``): TL =
    # "too long" interval, T = technical artefact. Both must be excluded
    # from the Poincare scatter, otherwise a single dropped beat leaves
    # a pair of outliers (one too-long, one too-short) that completely
    # blow up the plot's autoscaling and ellipse fit.
    _BAD_LABELS: tuple[str, ...] = ("TL", "T")

    def _valid_ibi_mask(self, rt) -> np.ndarray:
        """Return a per-IBI bool mask: True where the IBI is finite and
        the beat is not labelled as an artefact.

        Falls back to a purely-numeric filter (finite + positive) when
        labels are missing or mis-aligned, so legacy datasets without
        label arrays still render.
        """
        ibi = np.asarray(rt.ibi, dtype=float)
        valid = np.isfinite(ibi) & (ibi > 0)

        labels = getattr(rt, "labels", None)
        if labels is not None:
            labels_arr = np.asarray(labels)
            if labels_arr.shape == ibi.shape:
                for bad in self._BAD_LABELS:
                    valid &= labels_arr != bad
        return valid

    def _draw_plot(self) -> None:
        """Draw scatter + ellipse for each epoch.

        IBIs labelled as artefacts (``TL`` / ``T``) are dropped from
        the scatter. Pairs ``(ibi[n], ibi[n+1])`` are kept only when
        **both** members are valid - bridging across a dropped beat
        would join non-consecutive intervals and lie about beat-to-beat
        dynamics.
        """
        assert self.dataset is not None

        for name, epoch in self.dataset.epochs.items():
            rt = self.dataset.hrv[name]

            if rt.ibi.size < 2:
                continue

            # Per-IBI validity, then pair-wise: both consecutive
            # intervals must be valid to participate in the scatter.
            valid = self._valid_ibi_mask(rt)
            pair_mask = valid[:-1] & valid[1:]
            x = rt.ibi[:-1][pair_mask]
            y = rt.ibi[1:][pair_mask]

            if x.size == 0:
                continue

            scatter = self.ax.scatter(x, y, alpha=0.25, label=name)
            scatter.epoch = name

            mean_ibi = float(np.mean(x))
            color = scatter.get_facecolor()

            ellipse = Ellipse(
                (mean_ibi, mean_ibi),
                sd1(rt) / 500.0,  # Be Aware
                sd2(rt) / 500.0,  # Be Aware
                angle=-45,
                facecolor=color,
                edgecolor="black",
                alpha=0.35,
                zorder=1,
            )
            self.ax.add_patch(ellipse)

            scatter.set_visible(epoch.active)
            ellipse.set_visible(epoch.active)

            self.scatter_handles[name] = scatter
            self.ellipse_handles[name] = ellipse

        # Identity line added after axis limits are set in _configure_axes.

    def _build_checkboxes(self) -> None:
        """Create one checkbox per epoch."""
        assert self.dataset is not None

        for name, epoch in self.dataset.epochs.items():
            cb = QCheckBox(name)
            cb.setChecked(epoch.active)
            cb.stateChanged.connect(self._on_checkbox_changed)
            self.checkbox_layout.addWidget(cb)
            self.epoch_checkboxes[name] = cb

    def _on_checkbox_changed(self) -> None:
        """Update epoch.active and visibility."""
        assert self.dataset is not None

        for name, cb in self.epoch_checkboxes.items():
            try:
                visible = cb.isChecked()
                self.dataset.epochs[name].active = visible
                if self.scatter_handles[name] is not None:
                    self.scatter_handles[name].set_visible(visible)
                self.ellipse_handles[name].set_visible(visible)
            except (KeyError, AttributeError):
                self.scatter_handles[name] = None
                self.ellipse_handles[name] = None

        self.canvas.draw_idle()

    def _configure_axes(self) -> None:
        """
        Configure axis limits and styling based on plotted Poincare points.

        This method is fully defensive:
        - Handles missing epochs
        - Handles empty scatters
        - Handles NaN / Inf values
        - Never raises due to invalid limits
        """

        if not self.scatter_handles:
            return

        all_x: list[np.ndarray] = []
        all_y: list[np.ndarray] = []

        for handle in self.scatter_handles.values():
            if handle is None:
                continue

            offsets = handle.get_offsets()
            if offsets.size == 0:
                continue

            x = offsets[:, 0]
            y = offsets[:, 1]

            # Keep only finite values
            finite = np.isfinite(x) & np.isfinite(y)
            if not np.any(finite):
                continue

            all_x.append(x[finite])
            all_y.append(y[finite])

        # If no valid data survived, do nothing
        if not all_x or not all_y:
            return

        x_all = np.concatenate(all_x)
        y_all = np.concatenate(all_y)

        # Absolute safety check
        if not np.all(np.isfinite(x_all)) or not np.all(np.isfinite(y_all)):
            return

        # Compute padding (avoid zero / NaN span)
        span = max(x_all.max() - x_all.min(), y_all.max() - y_all.min())
        if not np.isfinite(span) or span == 0:
            span = 1e-6

        pad = 0.05 * span

        x_lo = max(0.0, x_all.min() - pad)
        x_hi = x_all.max() + pad
        y_lo = max(0.0, y_all.min() - pad)
        y_hi = y_all.max() + pad
        self.ax.set_xlim(x_lo, x_hi)
        self.ax.set_ylim(y_lo, y_hi)

        self.ax.set_aspect("equal", adjustable="box")
        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)

        # Identity line spanning the full visible range
        lim_lo = min(x_lo, y_lo)
        lim_hi = max(x_hi, y_hi)
        self.ax.plot([lim_lo, lim_hi], [lim_lo, lim_hi], ":", color="gray", lw=1)


    def _setup_cursor(self) -> None:
        """mplcursors hover annotation."""
        if self.cursor is not None:
            self.cursor.remove()

        self.cursor = mplcursors.cursor(
            list(self.scatter_handles.values()),
            hover=False,
            multiple=True,
        )

        @self.cursor.connect("add")
        def _on_hover(sel):
            scatter = sel.artist
            epoch_name = scatter.epoch
            rt = self.dataset.hrv[epoch_name]

            x, y = scatter.get_offsets()[sel.index]
            idx = int(np.argmin(np.abs(rt.ibi[:-1] - x)))

            sel.annotation.set_text(
                f"{epoch_name}\n"
                f"IBI = {1000*x:.0f} → {1000*y:.0f} ms\n"
                f"Time = {rt.times[idx]:.1f} s"
            )
            sel.annotation.get_bbox_patch().set_alpha(0.5)
