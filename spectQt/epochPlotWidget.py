import copy

import matplotlib
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PySide6.QtWidgets import QInputDialog, QVBoxLayout, QWidget


class EpochPlotWidget(QWidget):
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

    def plotEpoch(self, dataset, labels=True):
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

        # Clear the previous plot
        self.ax.clear()

        # Store rectangles and their data
        self.rectangles = []
        
        # Plot rectangles for each epoch
        for i, epoch in enumerate(epoch_names):
            rect = patches.Rectangle(
                (start_times.iloc[i], i - 0.4),  # (x, y)
                durations.iloc[i],              # width
                0.8,                            # height
                fill=True,
                color=self.color_dict[epoch],
                edgecolor="black",
                alpha=0.5
            )
            self.ax.add_patch(rect)
            # Annotate start time
            start_text = self.ax.text(
                start_times.iloc[i], i, f"{round(start_times.iloc[i])}",
                va="center", ha="left", fontsize=8, rotation='vertical'
            )
            # Annotate end time
            end_text = self.ax.text(
                start_times.iloc[i] + durations.iloc[i], i, f"{round(start_times.iloc[i] + durations.iloc[i])}",
                va="center", ha="right", fontsize=8, rotation='vertical'
            )
            self.rectangles.append({
                'rect': rect,
                'epoch': epoch,
                'start': start_times.iloc[i],
                'stop': start_times.iloc[i] + durations.iloc[i],
                'start_text': start_text,
                'end_text': end_text
            })

        # Customize y-axis ticks and labels
        self.ax.set_yticks(range(len(epoch_names)))
        yticklabels = [name.title() for name in epoch_names]  # Convert epoch names to title case
        self.ax.set_yticklabels(yticklabels) 
        # Store yticklabels for reference
        self.yticklabels = yticklabels

        # Connect event handlers for y-axis label clicks
        self.canvas.mpl_connect('pick_event', self.on_label_click)

        # Make y-axis labels pickable
        for label in self.ax.get_yticklabels():
            label.set_picker(True)

        # Add axis labels and grid
        self.ax.set_xlabel("Time")            # Label x-axis
        self.ax.set_ylabel("")                # No y-axis label
        self.ax.set_title("")                 # No chart title
        self.ax.grid(axis="y", linestyle="-", alpha=0.7)  # Add grid lines along the y-axis
        # Set x-axis limits
        
        self.ax.set_xlim([start_times.min() - 1, epochs_gantt["end"].max() + 1])
        # Set y-axis limits to provide more vertical space
        self.ax.set_ylim([-1, len(epoch_names)])

        # Connect event handlers
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('button_release_event', self.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)

        # Adjust layout to avoid clipping
        plt.tight_layout()

        # Redraw the canvas
        self.canvas.draw()

    def on_press(self, event):
        """Handle mouse press event."""
        if event.inaxes != self.ax:
            return

        # Check if a rectangle was clicked
        for rect_data in self.rectangles:
            rect = rect_data['rect']
            contains, _ = rect.contains(event)
            if contains:
                self.dragged_rect = rect_data
                self.press_x = event.xdata
                rect_x, rect_y = rect.get_xy()
                rect_width = rect.get_width()

                # Determine if the left or right part of the rectangle is clicked
                if abs(event.xdata - rect_x) < rect_width / 2:
                    self.drag_side = 'left'  # Dragging the start time
                else:
                    self.drag_side = 'right'  # Dragging the end time
                return

    def on_motion(self, event):
        """Handle mouse motion event."""
        if event.inaxes != self.ax or not hasattr(self, 'dragged_rect'):
            return

        rect_data = self.dragged_rect
        rect = rect_data['rect']

        if self.drag_side == 'left':
            # Set the start time to the current cursor position
            new_start = event.xdata
            if new_start < rect_data['stop']:  # Ensure start time is before end time
                rect.set_x(new_start)
                rect_data['start'] = new_start
                # Adjust the width to keep the end time the same
                rect.set_width(rect_data['stop'] - new_start)
                rect_data['rect'] = rect
                # Update start time annotation
                rect_data['start_text'].set_position((new_start, rect.get_y() + rect.get_height() / 2))
                rect_data['start_text'].set_text(f"{round(new_start)}")
        elif self.drag_side == 'right':
            # Set the end time to the current cursor position
            new_end = event.xdata
            if new_end > rect_data['start']:  # Ensure end time is after start time
                rect.set_width(new_end - rect_data['start'])
                rect_data['stop'] = new_end
                rect_data['rect'] = rect
                # Update end time annotation
                rect_data['end_text'].set_position((new_end, rect.get_y() + rect.get_height() / 2))
                rect_data['end_text'].set_text(f"{round(new_end)}")

        # Redraw the canvas
        self.canvas.draw()

    def on_release(self, event):
        """Handle mouse release event."""
        if hasattr(self, 'dragged_rect'):
            # Update the dataset's RTops with the new epoch boundaries
            self.update_RTops_epochs()
            del self.dragged_rect
            if hasattr(self, 'drag_side'):
                del self.drag_side

    def update_RTops_epochs(self):
        """
        Update the RTops DataFrame to reflect the new epoch boundaries.
        """
        if self.dataset is None or self.dataset.RTops is None:
            return

        # Clear existing epoch assignments in RTops
        self.dataset.RTops['epoch'] = self.dataset.RTops['epoch'].apply(lambda x: [])

        # Loop through each epoch and update RTops
        for rect_data in self.rectangles:
            epoch = rect_data['epoch']
            start_time = rect_data['start']
            end_time = rect_data['stop']

            # Update RTops entries that fall within the epoch boundaries
            for idx in self.dataset.RTops.loc[(self.dataset.RTops['time'] >= start_time) & (self.dataset.RTops['time'] <= end_time)].index:
                self.dataset.RTops.at[idx, 'epoch'].append(epoch)

    def on_label_click(self, event):
        """Handle click event on y-axis labels."""
        if isinstance(event.artist, matplotlib.text.Text):
            label = event.artist
            current_text = label.get_text()
            # Use QInputDialog to get new label text
            new_text, ok = QInputDialog.getText(self, 'Rename Epoch', 'New name:', text=current_text)
            if ok:
                if new_text=='':
                    # If the new text is empty, delete the epoch
                    index = self.ax.get_yticks().tolist().index(label.get_position()[1])
                    old_epoch_name = self.yticklabels[index]

                    # Remove the epoch from the dataset
                    self.delete_epoch_from_dataset(old_epoch_name)
                else:
                    # update the label text
                    label.set_text(new_text)
                    print(label)
                    # Update the corresponding epoch name in the dataset
                    index = self.ax.get_yticks().tolist().index(label.get_position()[1])
                    old_epoch_name = self.yticklabels[index]
                    self.yticklabels[index] = new_text
                    
                    # Update the epoch name in the dataset
                    self.update_epoch_name_in_dataset(old_epoch_name, new_text)

                # Replot the figure to reflect the changes
                self.plotEpoch(self.dataset)

    def update_epoch_name_in_dataset(self, old_name, new_name):
        """
        Update the epoch name in the dataset.

        Args:
            old_name (str): The old epoch name.
            new_name (str): The new epoch name.
        """
        if self.dataset is None:
            return

        # Update the epoch name in the RTops DataFrame
        if self.dataset.RTops is not None:
            print('Rtops')
            self.dataset.RTops['epoch'] = self.dataset.RTops['epoch'].apply(
                lambda epochs: [new_name if epoch == old_name else epoch for epoch in epochs]
            )

        # Update the epoch name in the events DataFrame
        if self.dataset.events is not None:
            print('Events')
            self.dataset.events['label'] = self.dataset.events['label'].apply(
                lambda label: label.replace(old_name, new_name) if old_name in label else label
            )

        # Update the epoch name in the epoch series
        if hasattr(self.dataset, 'epoch'):
            print('epoch')
            self.dataset.epoch = self.dataset.epoch.apply(
                lambda epochs: [new_name if epoch == old_name else epoch for epoch in epochs]
            )

        # Update the unique epochs
        if hasattr(self.dataset, 'unique_epochs'):
            print('unique')
            self.dataset.unique_epochs = self.dataset.get_unique_epochs()

    def delete_epoch_from_dataset(self, epoch_name):
        """
        Delete an epoch from the dataset.

        Args:
            epoch_name (str): The name of the epoch to delete.
        """
        if self.dataset is None:
            return

        # Remove the start and stop events for the epoch
        if self.dataset.events is not None:
            self.dataset.events = self.dataset.events[
                ~self.dataset.events['label'].str.lower().str.startswith(f'start {epoch_name.lower()}') &
                ~self.dataset.events['label'].str.lower().str.startswith(f'stop {epoch_name.lower()}')
            ].reset_index(drop=True)

        # Update the epoch series to remove the epoch
        if hasattr(self.dataset, 'epoch'):
            self.dataset.epoch = self.dataset.epoch.apply(
                lambda epochs: [epoch for epoch in epochs if epoch != epoch_name]
            )

        # Update the unique epochs
        if hasattr(self.dataset, 'unique_epochs'):
            self.dataset.unique_epochs = self.dataset.get_unique_epochs()

        # Update the RTops DataFrame to reflect the changes
        if hasattr(self.dataset, 'RTops'):
            self.dataset.update_RTops_epochs()
