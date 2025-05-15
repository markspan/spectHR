import matplotlib.pyplot as plt
import mplcursors
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
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
        self.setFocusPolicy(Qt.StrongFocus)
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
        self.cursor = None
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(checkbox_container)
        self.main_layout.addWidget(scroll, stretch=1)
        self.setVisible(False)

    def poincarePlot(self, dataset):
        """
        Plot the Poincaré graph based on the provided dataset, grouped by epoch.

        Args:
            dataset: A dataset object with `RTops`, `ibi`, and `unique_epochs` attributes.
        """
        self.dataset = dataset
        self.setVisible(True)
        self.setFocus()  # Ensure the widget gets focus

        # Ensure active_epochs is a dictionary
        active_epochs = getattr(dataset, "active_epochs", {})
        if isinstance(active_epochs, set):
            active_epochs = {epoch: True for epoch in active_epochs}

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
            scatter.epoch = epoch  # Store epoch in scatter for hover function

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

            visible = active_epochs.get(epoch, True)  # default to True if not stored
            scatter.set_visible(visible)
            ellipse.set_visible(visible)

            # Create checkbox for this epoch
            checkbox = QCheckBox(epoch)
            checkbox.setChecked(visible)
            checkbox.stateChanged.connect(self.update_visibility)
            self.epoch_checkboxes[epoch] = checkbox
            self.checkbox_layout.addWidget(checkbox)

        # Configure plot appearance
        self.ax.set_title('')
        self.ax.set_xlabel('IBI (ms)', fontsize=12)
        self.ax.set_ylabel('Next IBI (ms)', fontsize=12)
        self.ax.axline((0, 0), slope=1, color='gray', linestyle='--', linewidth=0.7)
        self.ax.grid(True)

        # Only include visible entries in legend
        if hasattr(self.dataset, 'active_epochs'):
            handles_labels = [
                (h, h.get_label()) for e, h in self.scatter_handles.items()
                if self.dataset.active_epochs.get(e, True)  # True if missing
            ]
        else:
            handles_labels = self.scatter_handles.items()

        if handles_labels:
            handles, labels = zip(*handles_labels)
            self.ax.legend(
                handles, labels,
                loc='upper left',
                bbox_to_anchor=(-0.5, 1.0),
                borderaxespad=0.,
                frameon=False
            )
        self.fig.subplots_adjust(left=0.3)  # Make room on the left for the legend
        self.ax.set_aspect('equal', adjustable='datalim')
        self.ax.set_box_aspect(1)
        self.filtered_by_epoch = {}

        # Step 2: create the sets
        for unique_epoch in dataset.unique_epochs:
            # Create a mask for the current epoch
            mask = [unique_epoch in sublist if sublist is not None else False for sublist in dataset.RTops.epoch]
            # Subset dataset.RTops for the current epoch
            self.filtered_by_epoch[unique_epoch] = dataset.RTops[mask]

        # Add mplcursors hover annotations
        # Remove existing cursor if present
        if hasattr(self, 'cursor') and self.cursor is not None:
            self.cursor.remove()
        # Create a new cursor
        self.cursor = mplcursors.cursor([scatter for scatter in self.scatter_handles.values()], hover=False, multiple=True)

        @self.cursor.connect("add")
        def on_hover(sel):
            scatter = sel.artist
            epoch = getattr(scatter, 'epoch', 'Unknown')  # or use scatter.get_gid()
            x_value = scatter.get_offsets()[sel.index, 0]
            y_value = scatter.get_offsets()[sel.index, 1]

            data = self.filtered_by_epoch[epoch]
            ibi_idx = (np.abs(data.ibi - x_value)).argmin()
            time_value = data.time.iloc[ibi_idx]

            sel.annotation.set_text(
                f"{epoch.title()}:\n"
                f"IBI = {1000*x_value:.0f}–{1000*y_value:.0f} ms\n"
                f"Time = {time_value:.1f} s"
            )            
            sel.annotation.get_bbox_patch().set_alpha(0.5)
            sel.annotation.get_bbox_patch().set_facecolor(scatter.get_facecolor())  
        self.canvas.draw()
            
    def update_visibility(self):
        """
        Toggle visibility of each epoch's plot elements based on checkbox state,
        and store the visibility state in dataset.active_epochs.
        """
        self.dataset.active_epochs = {}  # Initialize or update
        for epoch, checkbox in self.epoch_checkboxes.items():
            visible = checkbox.isChecked()
            self.dataset.active_epochs[epoch] = visible  # Store state
            if epoch in self.scatter_handles:
                self.scatter_handles[epoch].set_visible(visible)
            if epoch in self.ellipse_handles:
                self.ellipse_handles[epoch].set_visible(visible)
                
        self.canvas.draw()
