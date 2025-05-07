import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QScrollArea, QFrame
)
from matplotlib.patches import Ellipse
import numpy as np
import spectHR as cs
import mplcursors  

class PoincarePlotWidget(QWidget):
    """
    A QWidget that displays a Poincaré plot with interactive checkboxes
    to toggle the visibility of epoch-specific data series.

    Attributes:
        fig (matplotlib.figure.Figure): The matplotlib Figure object.
        ax (matplotlib.axes.Axes): The plotting area for the Poincaré plot.
        canvas (FigureCanvas): The Qt canvas embedding the matplotlib figure.
        epoch_checkboxes (dict): Dictionary mapping epoch names to their QCheckBox widgets.
        scatter_handles (dict): Dictionary mapping epoch names to scatter plot handles.
        ellipse_handles (dict): Dictionary mapping epoch names to ellipse patch handles.
        filtered_by_epoch (dict): Dictionary of filtered RTops data per epoch.
    """

    def __init__(self, parent=None):
        """
        Initialize the Poincaré plot widget and its layout components.

        Args:
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.setWindowTitle('Poincaré Plot')

        # Create matplotlib figure and canvas
        self.fig, self.ax = plt.subplots(figsize=(6, 6))
        self.canvas = FigureCanvas(self.fig)

        # Set up main horizontal layout
        self.main_layout = QHBoxLayout(self)
        self.setLayout(self.main_layout)

        # === Left side: Plot area ===
        self.plot_layout = QVBoxLayout()
        self.plot_layout.addWidget(self.canvas)

        plot_frame = QFrame()
        plot_frame.setLayout(self.plot_layout)
        self.main_layout.addWidget(plot_frame, stretch=3)

        # === Right side: Scrollable checkbox area ===
        self.checkbox_layout = QVBoxLayout()
        self.epoch_checkboxes = {}

        checkbox_container = QWidget()
        checkbox_container.setLayout(self.checkbox_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(checkbox_container)
        self.main_layout.addWidget(scroll, stretch=1)

    def plot_poincare(self, dataset):
        """
        Plot the Poincaré graph based on the provided dataset, grouped by epoch.

        Args:
            dataset: A dataset object with `RTops`, `ibi`, and `unique_epochs` attributes.
        """
        self.dataset = dataset

        # Clear any existing checkboxes from the layout
        for i in reversed(range(self.checkbox_layout.count())):
            widget = self.checkbox_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # Filter RTops data by epoch
        self.filtered_by_epoch = {}
        for unique_epoch in dataset.unique_epochs:
            mask = [unique_epoch in sublist if sublist is not None else False
                    for sublist in dataset.RTops.epoch]
            self.filtered_by_epoch[unique_epoch] = dataset.RTops[mask]

        # Clear existing plot
        self.ax.clear()
        self.scatter_handles = {}
        self.ellipse_handles = {}

        # Plot data for each epoch
        for epoch in sorted(dataset.unique_epochs):
            data = self.filtered_by_epoch[epoch]
            x = data.ibi[:-1].reset_index(drop=True)
            y = data.ibi[1:].reset_index(drop=True)

            # Plot scatter for IBI vs next IBI
            scatter = self.ax.scatter(x, y, label=epoch, alpha=0.2)
            ibm = np.mean(x)
            col = scatter.get_facecolor()

            # Add ellipse representing SD1 and SD2
            ellipse = Ellipse(
                (ibm, ibm),
                cs.sd1(data.ibi) / 500,
                cs.sd2(data.ibi) / 500,
                angle=-45,
                linewidth=1,
                zorder=1,
                facecolor=col,
                edgecolor='k',
                alpha=0.35
            )
            self.ax.add_artist(ellipse)

            # Store handles for visibility toggling
            self.scatter_handles[epoch] = scatter
            self.ellipse_handles[epoch] = ellipse

            # Create checkbox for this epoch
            checkbox = QCheckBox(epoch)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(self.update_visibility)
            self.epoch_checkboxes[epoch] = checkbox
            self.checkbox_layout.addWidget(checkbox)

        # Configure plot appearance
        self.ax.set_title('')
        self.ax.set_xlabel('IBI (ms)', fontsize=12)
        self.ax.set_ylabel('Next IBI (ms)', fontsize=12)
        self.ax.axline((0, 0), slope=1, color='gray', linestyle='--', linewidth=0.7)
        self.ax.grid(True)
        self.ax.legend()
        self.ax.set_aspect('equal', adjustable='datalim')
        self.ax.set_box_aspect(1)

        # Add mplcursors hover annotations
        all_scatters = list(self.scatter_handles.values())
        cursor = mplcursors.cursor(all_scatters, hover=True)

        @cursor.connect("add")
        def on_add(sel):
            for epoch, scatter in self.scatter_handles.items():
                if sel.artist == scatter:
                    ind = sel.index
                    data = self.filtered_by_epoch[epoch]
                    if ind < len(data):
                        time = data.index[ind]  # assuming time is in the index
                        sel.annotation.set(text=f"{epoch}\nTime: {time}")
                    else:
                        sel.annotation.set(text=f"{epoch}\nIndex: {ind}")
                    break

        # Redraw canvas
        self.canvas.draw()

    def update_visibility(self):
        """
        Toggle visibility of each epoch's plot elements based on checkbox state.
        """
        for epoch, checkbox in self.epoch_checkboxes.items():
            visible = checkbox.isChecked()
            if epoch in self.scatter_handles:
                self.scatter_handles[epoch].set_visible(visible)
            if epoch in self.ellipse_handles:
                self.ellipse_handles[epoch].set_visible(visible)
        self.canvas.draw()
