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


class PoincarePlotWidget(QWidget):
    """
    Poincaré plot widget with epoch-based visibility control.

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
        self.scatter_handles: dict[str, any] = {}
        self.ellipse_handles: dict[str, Ellipse] = {}
        self.epoch_checkboxes: dict[str, QCheckBox] = {}
        self.cursor = None

        # Matplotlib figure
        self.fig, self.ax = plt.subplots(figsize=(6, 6))
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
        Render the Poincaré plot for the given dataset.
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

    def _draw_plot(self) -> None:
        """Draw scatter + ellipse for each epoch."""
        assert self.dataset is not None

        for name, epoch in self.dataset.epochs.items():
            rt = self.dataset.hrv_map[self.dataset.active_band][name]

            if rt.ibi.size < 2:
                continue

            x = rt.ibi[:-1]
            y = rt.ibi[1:]

            scatter = self.ax.scatter(x, y, alpha=0.25, label=name)
            scatter.epoch = name

            mean_ibi = float(np.mean(x))
            color = scatter.get_facecolor()

            ellipse = Ellipse(
                (mean_ibi, mean_ibi),
                rt.sd1() / 500.0, # Be Aware
                rt.sd2() / 500.0, # Be Aware
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

        self.ax.plot([0,1], [0,1], ":", color="gray", lw=1)

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
        Configure axis limits and styling based on plotted Poincaré points.

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
        span = max(np.ptp(x_all), np.ptp(y_all))
        if not np.isfinite(span) or span == 0:
            span = 1e-6

        pad = 0.05 * span

        self.ax.set_xlim(0 - pad, x_all.max() + pad)
        self.ax.set_ylim(0 - pad, y_all.max() + pad)

        self.ax.set_aspect("equal", adjustable="box")
        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)


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
