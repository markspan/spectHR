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
    ----------
    fig : matplotlib.figure.Figure
        Matplotlib figure.
    ax : matplotlib.axes.Axes
        Axes to plot on.
    canvas : FigureCanvas
        Qt canvas for embedding matplotlib.
    color_dict : dict
        Maps epoch names to matplotlib color values.
    dataset : object
        The dataset object containing epoch information.
    rectangles : list
        Stores rectangles and their data.
    yticklabels : list
        Stores y-axis tick labels.
    """

    def __init__(self, parent=None):
        """
        Initialize the EpochPlotWidget and its layout components.

        Args:
            parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)
        self.setWindowTitle('Epoch Gantt Chart')

        # Initialize matplotlib figure and canvas
        # self.fig, self.ax = plt.subplots(figsize=(15, 7))
        self.fig = plt.figure()
        self.ax = plt.gca()
        self.canvas = FigureCanvas(self.fig)
        # Close the figure to prevent it from displaying immediately
        plt.close(self.fig)
        self.setVisible(False)

        # Set up the layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self.dataset = None
        self.color_dict = {}
        self.rectangles = []
        self.yticklabels = []
        self.dataset = None

    def plotEpoch(self, dataset, labels=True):
        """
        Render the Gantt chart for the given dataset.

        Args:
            dataset: An object with RTops (DataFrame) and optionally active_epochs (dict).
            labels (bool): If True, displays start and end time annotations on the chart.
        """

        self.rectangles = []
        self.dataset = dataset
        self.setVisible(False)

        # Extract relevant columns for plotting
        active_epochs = {epoch: active for epoch,
                         active in dataset.active_epochs.items() if active}

        # Use the keys of the filtered dictionary to select rows from the DataFrame
        visuals = dataset.epochs.loc[dataset.epochs['label'].isin(
            active_epochs.keys())]
        epoch_names = visuals["label"].tolist()
        start_times = visuals["starttime"].tolist()
        durations = (visuals["endtime"] - visuals["starttime"]).tolist()
        end_times = visuals["endtime"].tolist()

        # Generate unique colors for each epoch using a colormap
        colors = plt.cm.tab20(np.linspace(0, 1, len(epoch_names)))
        self.color_dict = dict(zip(epoch_names, colors))

        # Clear the previous plot
        self.ax.clear()

        # Plot rectangles for each epoch
        for i, epoch in enumerate(epoch_names):
            rect = patches.Rectangle(
                (start_times[i], i - 0.4),
                durations[i],
                0.8,
                fill=True,
                color=self.color_dict[epoch],
                edgecolor="black",
                alpha=0.5
            )
            self.ax.add_patch(rect)

            # Annotate start time
            start_text = self.ax.text(
                start_times[i], i, f"{round(start_times[i])}",
                va="center", ha="left", fontsize=8, rotation='vertical'
            )

            # Annotate end time
            end_text = self.ax.text(
                start_times[i] +
                durations[i], i, f"{round(start_times[i] + durations[i])}",
                va="center", ha="right", fontsize=8, rotation='vertical'
            )

            self.rectangles.append({
                'rect': rect,
                'epoch': epoch,
                'start': start_times[i],
                'stop': start_times[i] + durations[i],
                'start_text': start_text,
                'end_text': end_text
            })

        # Customize y-axis ticks and labels
        self.ax.set_yticks(range(len(epoch_names)))
        yticklabels = [name.title() for name in epoch_names]
        self.ax.set_yticklabels(yticklabels)
        self.yticklabels = yticklabels

        # Connect event handlers for y-axis label clicks
        self.canvas.mpl_connect('pick_event', self.on_label_click)

        # Make y-axis labels pickable
        for label in self.ax.get_yticklabels():
            label.set_picker(True)

        # Add axis labels and grid
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("")
        self.ax.set_title("")
        self.ax.grid(axis="y", linestyle="-", alpha=0.7)

        # Set x-axis limits
        #self.ax.set_xlim([min(start_times) - 1, max(end_times) + 1])
        self.ax.set_xlim(dataset.ecg.time.iloc[0], dataset.ecg.time.iloc[-1])
        self.ax.set_ylim([-1, len(epoch_names)])

        # Connect event handlers
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('button_release_event', self.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)

        # Adjust layout to avoid clipping
        plt.tight_layout()

        # Redraw the canvas
        self.setVisible(True)
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
            if new_start < rect_data['stop']:
                rect.set_x(new_start)
                rect_data['start'] = new_start
                rect.set_width(rect_data['stop'] - new_start)
                rect_data['rect'] = rect
                # Update start time annotation
                rect_data['start_text'].set_position(
                    (new_start, rect.get_y() + rect.get_height() / 2))
                rect_data['start_text'].set_text(f"{round(new_start)}")

        elif self.drag_side == 'right':
            # Set the end time to the current cursor position
            new_end = event.xdata
            if new_end > rect_data['start']:
                rect.set_width(new_end - rect_data['start'])
                rect_data['stop'] = new_end
                rect_data['rect'] = rect
                # Update end time annotation
                rect_data['end_text'].set_position(
                    (new_end, rect.get_y() + rect.get_height() / 2))
                rect_data['end_text'].set_text(f"{round(new_end)}")

        # Redraw the canvas
        self.canvas.draw()

    def on_release(self, event):
        """Handle mouse release event."""
        if hasattr(self, 'dragged_rect'):
            rect_data = self.dragged_rect
            epoch = rect_data['epoch']
            # Update the dataset's RTops with the new epoch boundaries
            df = self.dataset.epochs
            df.loc[df['label'] == epoch, 'starttime'] = rect_data['start']
            df.loc[df['label'] == epoch, 'endtime'] = rect_data['stop']
            del self.dragged_rect
            self.update_epochs()
            if hasattr(self, 'drag_side'):
                del self.drag_side

    def update_epochs(self):
        """
        Update the RTops filtered by epoch DataFrame to reflect the new epoch boundaries.
        """
        # Filter RTops data by epoch

        self.dataset.filtered_by_epoch = {}

        for _, epoch in self.dataset.epochs.iterrows():
            unique_epoch = epoch['label']
            start_time = epoch['starttime']
            end_time = epoch['endtime']

            # Filter RTops data for the current epoch
            mask = (self.dataset.RTops['time'] >= start_time) & (
                self.dataset.RTops['time'] <= end_time)
            filtered_data = self.dataset.RTops[mask]

            # Store the filtered data in the dictionary
            self.dataset.filtered_by_epoch[unique_epoch] = filtered_data

    def on_label_click(self, event):
        """Handle click event on y-axis labels."""
        if isinstance(event.artist, matplotlib.text.Text):
            label = event.artist
            current_text = label.get_text()

            # Use QInputDialog to get new label text
            new_text, ok = QInputDialog.getText(
                self, 'Rename Epoch', 'New name:', text=current_text)
            if ok:
                if new_text == '':
                    # If the new text is empty, delete the epoch
                    index = self.ax.get_yticks().tolist().index(
                        label.get_position()[1])
                    old_epoch_name = self.yticklabels[index]
                    self.delete_epoch_from_dataset(old_epoch_name)
                else:
                    # Update the label text
                    if new_text.lower() in self.dataset.epochs['label'].str.lower().values:
                        # If the new name already exists, show a warning
                        print(
                            f"Epoch name '{new_text}' already exists. Please choose a different name.")
                        return
                    label.set_text(new_text)
                    index = self.ax.get_yticks().tolist().index(
                        label.get_position()[1])
                    old_epoch_name = self.yticklabels[index]
                    self.yticklabels[index] = new_text
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

        # Update the epoch name in the events DataFrame
        if self.dataset.events is not None:
            self.dataset.events['label'] = self.dataset.events['label'].apply(
                lambda label: label.replace(old_name, new_name.lower(
                )) if old_name.lower() in label.lower() else label.lower()
            )

        # Update the epoch name in the epoch series
        if hasattr(self.dataset, 'epochs'):
            self.dataset.epochs = self.dataset.epochs.apply(
                lambda epochs: [new_name.lower() if epoch ==
                                old_name.lower() else epoch for epoch in epochs]
            )

        # Update the active epochs
        if hasattr(self.dataset, 'active_epochs'):
            isactive = self.dataset.active_epochs[old_name.lower()]
            del self.dataset.active_epochs[old_name.lower()]
            self.dataset.active_epochs[new_name.lower()] = isactive

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
                ~self.dataset.events['label'].str.lower().str.startswith(
                    f'stop {epoch_name.lower()}')
            ].reset_index(drop=True)

        # Update the epoch series to remove the epoch
        if hasattr(self.dataset, 'epoch'):
            self.dataset.epoch = self.dataset.epoch.apply(
                lambda epochs: [
                    epoch.lower() for epoch in epochs if epoch.lower() != epoch_name.lower()]
            )
            # Update the active epochs
        if hasattr(self.dataset, 'active_epochs'):
            del self.dataset.active_epochs[epoch_name.lower()]
