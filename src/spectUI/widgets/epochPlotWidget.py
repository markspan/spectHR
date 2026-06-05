# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


import matplotlib.cm as cm
import matplotlib.patches as patches
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QInputDialog
from spectHR.DataSet.Epoch import Epoch

import numpy as np
from spectHR.Tools.Logger import logger

class EpochPlotWidget(QWidget):
    """
    Gantt-style editor for dataset.epochs (dict[str, Epoch]).

    Each epoch draws one horizontal bar:
        active=True   -> shown
        active=False  -> hidden
    """

    # Emitted whenever the user actually mutates an epoch (resize via drag,
    # rename, or delete). MainWindow connects this to mark the dataset
    # dirty, so plot caches are invalidated only on a real edit - merely
    # viewing this dock leaves them intact.
    dataEdited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.fig = Figure()
        self.ax  = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)

        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self.dataset = None
        self.rectangles = []  # holds dicts describing drawn epochs
        self._drag = None     # drag state struct

        self.setVisible(False)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def plotEpochs(self, dataset):
        """
        Render all active epochs in dataset.epochs.
        dataset.epochs : dict[str, Epoch]
        """
        self.dataset = dataset
        self.rectangles.clear()
        self.ax.clear()

        # Collect visible epochs (active=True)
        active_items = [(name, ep) for name, ep in dataset.epochs.items() if ep.active]
        active_items.sort(key=lambda x: x[1].start)

        if not active_items:
            self.setVisible(True)
            self.canvas.draw()
            return

        names = [name for name, _ in active_items]
        epochs = [ep for _, ep in active_items]

        cmap = cm.tab20(np.linspace(0, 1, len(names)))

        # Draw bars
        for i, (name, ep) in enumerate(zip(names, epochs)):
            rect = patches.Rectangle(
                (ep.start, i - 0.4),
                ep.end - ep.start,
                0.8,
                edgecolor="black",
                facecolor=cmap[i],
                alpha=0.5,
            )
            self.ax.add_patch(rect)

            start_text = self.ax.text(
                ep.start, i,
                f"{ep.start:.0f}",
                va="center", ha="left", fontsize=8, rotation="vertical"
            )
            end_text = self.ax.text(
                ep.end, i,
                f"{ep.end:.0f}",
                va="center", ha="right", fontsize=8, rotation="vertical"
            )

            self.rectangles.append(dict(
                name=name,
                ep=ep,
                rect=rect,
                start_text=start_text,
                end_text=end_text
            ))

        # Y ticks
        self.ax.set_yticks(range(len(names)))
        self.ax.set_yticklabels(names)

        # Make y-labels clickable
        for lbl in self.ax.get_yticklabels():
            lbl.set_picker(True)

        # X-limits = full ECG range
        if self.dataset.has_ecg:
           ecg = dataset["ecg"].timeseries
           self.ax.set_xlim(float(ecg.times.min()), float(ecg.times.max()))
           self.ax.set_ylim(-1, len(names))
        elif hasattr(self.dataset, "hrv") and self.dataset.hrv is not None:
            start_time = self.dataset.hrv.times[0]
            end_time = self.dataset.hrv.times[-1]
            self.ax.set_xlim(float(start_time), float(end_time))
            self.ax.set_ylim(-1, len(names))

        # Connect interaction
        self.canvas.mpl_connect("pick_event", self._on_label_pick)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)

        self.fig.tight_layout()
        self.setVisible(True)
        self.canvas.draw()

    # ------------------------------------------------------------------
    # Rectangle drag interactions
    # ------------------------------------------------------------------

    def _on_press(self, event):
        if event.inaxes != self.ax or event.xdata is None:
            return

        for item in self.rectangles:
            rect = item["rect"]
            contains, _ = rect.contains(event)
            if contains:
                x = event.xdata
                x0 = rect.get_x()
                x1 = x0 + rect.get_width()

                # Click near left or right edge?
                if abs(x - x0) < abs(x - x1):
                    side = "left"
                else:
                    side = "right"

                self._drag = dict(item=item, side=side)
                return

    def _on_motion(self, event):
        if not self._drag or event.inaxes != self.ax or event.xdata is None:
            return

        item = self._drag["item"]
        ep: Epoch = item["ep"]
        rect = item["rect"]
        side = self._drag["side"]

        if side == "left":
            new_start = event.xdata
            if new_start < ep.end:
                ep.start = float(new_start)
        else:
            new_end = event.xdata
            if new_end > ep.start:
                ep.end = float(new_end)

        # Update rect + labels
        rect.set_x(ep.start)
        rect.set_width(ep.end - ep.start)
        item["start_text"].set_position((ep.start, rect.get_y() + rect.get_height() / 2))
        item["end_text"].set_position((ep.end, rect.get_y() + rect.get_height() / 2))
        item["start_text"].set_text(f"{ep.start:.1f}")
        item["end_text"].set_text(f"{ep.end:.1f}")

        self.canvas.draw_idle()

    def _on_release(self, event):
        # Only a genuine resize drag (press landed on an epoch edge) counts
        # as an edit; a bare click that started no drag does not.
        if self._drag is not None:
            self._drag = None
            self.dataEdited.emit()

    # ------------------------------------------------------------------
    # Rename/delete epoch via clicking y-label
    # ------------------------------------------------------------------

    def _on_label_pick(self, event):
        lbl = event.artist
        if lbl not in self.ax.get_yticklabels():
            return

        old_name = lbl.get_text()
        new_name, ok = QInputDialog.getText(
            self, "Rename Epoch", "New name:", text=old_name
        )

        if not ok:
            return

        if new_name.strip() == "":
            # Delete epoch
            if old_name in self.dataset.epochs:
                del self.dataset.epochs[old_name]
            self.plotEpochs(self.dataset)
            self.dataEdited.emit()
            return

        if new_name in self.dataset.epochs:
            logger.info(f"Epoch '{new_name}' already exists.")
            return

        # Rename
        ep = self.dataset.epochs.pop(old_name)
        self.dataset.epochs[new_name] = ep

        self.plotEpochs(self.dataset)
        self.dataEdited.emit()
