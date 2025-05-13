import copy

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PySide6.QtWidgets import QVBoxLayout, QWidget

from spectHR.Tools.Logger import logger


class GanttPlotWidget(QWidget):
    """
    A QWidget that displays a Gantt chart of epochs from a dataset.
    Uses `dataset.active_epochs` to filter which epochs are shown if defined.
    
    Attributes:
        fig (matplotlib.figure.Figure): Matplotlib figure.
        ax (matplotlib.axes.Axes): Axes to plot on.
        canvas (FigureCanvas): Qt canvas for embedding matplotlib.
        color_dict (dict): Maps epoch names to matplotlib color values.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Epoch Gantt Chart')

        # Initialize matplotlib figure and canvas
        self.fig, self.ax = plt.subplots(figsize=(15, 7))
        self.canvas = FigureCanvas(self.fig)
        self.setVisible(False)
        # Set up the layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self.dataset = None
        self.color_dict = {}

    def plotGantt(self, dataset, labels=True):
        """
        Render the Gantt chart for the given dataset.

        Args:
            dataset: An object with RTops (DataFrame) and optionally active_epochs (dict).
            labels (bool): If True, displays start and end time annotations on the chart.
        """
        self.dataset = dataset
        self.setVisible(True)
        # Deep copy RTops to avoid modifying the original dataset
        RTops = copy.deepcopy(dataset.RTops)

        # Filter epochs to keep only those marked as visible
        if hasattr(dataset, 'active_epochs') and isinstance(dataset.active_epochs, dict):
            visible_epochs = {epoch: visible for epoch, visible in dataset.active_epochs.items() if visible}
        else:
            visible_epochs = {epoch: True for epoch in dataset.unique_epochs}

        logger.info(f'Visible epochs: {list(visible_epochs.keys())}')

        # Filter the RTops DataFrame: Keep rows containing at least one visible epoch
        RTops["filtered_epoch"] = RTops["epoch"].apply(
            lambda x: [e for e in x if e in visible_epochs] if x is not None else []
        )

        RTops = RTops[RTops["filtered_epoch"].str.len() > 0]  # Remove rows with no visible epochs

        # Flatten the filtered epochs list for easier plotting
        exploded = RTops.explode("filtered_epoch")
        # Calculate start and end times for each epoch
        epochs_gantt = (
            exploded.groupby("filtered_epoch")
            .agg(start=("time", "min"), end=("time", "max"))
            .reset_index()
        )
   
        # Sort epochs by start time (descending)
        epochs_gantt = epochs_gantt.sort_values(by="start", ascending=False).reset_index(drop=True)

        # Extract relevant columns for plotting
        epoch_names = epochs_gantt["filtered_epoch"]
        start_times = epochs_gantt["start"]
        durations = epochs_gantt["end"] - epochs_gantt["start"]

        # Generate unique colors for each epoch using a colormap
        colors = plt.cm.tab20(np.linspace(0, 1, len(epoch_names)))
        self.color_dict = dict(zip(epoch_names, colors))  # Map epoch names to specific colors

        # Plot horizontal bars for each epoch
        self.ax.clear()
        for i, epoch in enumerate(epoch_names):
            self.ax.barh(
                epoch,                      # Position on y-axis
                durations.iloc[i],          # Bar width (duration)
                left=start_times.iloc[i],   # Start time (left edge of bar)
                color=self.color_dict[epoch],  # Assigned color for the epoch
                edgecolor="black",          # Black border around bars
                alpha=0.5                   # Set transparency
            )

        # Customize y-axis ticks and labels
        self.ax.set_yticks(range(len(epoch_names)))
        self.ax.set_yticklabels([name.title() for name in epoch_names])  # Convert epoch names to title case

        # Add axis labels and grid
        self.ax.set_xlabel("Time")            # Label x-axis
        self.ax.set_ylabel("")                # No y-axis label
        self.ax.set_title("")                 # No chart title
        self.ax.grid(axis="y", linestyle="-", alpha=0.7)  # Add grid lines along the y-axis

        # Optionally annotate start and end times on each bar
        if labels:
            for i, row in epochs_gantt.iterrows():
                # Annotate start time
                self.ax.text(
                    row["start"], i, f"{round(row['start'])}",
                    va="center", ha="left", fontsize=8, rotation='vertical'
                )
                # Annotate end time
                self.ax.text(
                    row["end"], i, f"{round(row['end'])}",
                    va="center", ha="right", fontsize=8, rotation='vertical'
                )

        # Adjust layout to avoid clipping
        plt.tight_layout()

        # Redraw the canvas to display the updated plot
        self.canvas.draw()

