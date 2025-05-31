import math

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import qtawesome as qta
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import MultipleLocator
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from spectHR.ui.LineHandler import LineHandler


class PrepPlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Set up the Matplotlib figure and canvas
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        self.setVisible(False)
        # Initialize attributes
        self.data = None
        self.line_handler = None
        self.RTopColors = {
            "N": "blue",
            "L": "cyan",
            "S": "magenta",
            "TL": "orange",
            "SL": "turquoise",
            "SNS": "lightseagreen",
        }
        self.ax_ecg = None
        self.ax_overview = None
        self.ax_br = None
        self.positional_patch = None
        self.drag_mode = None
        self.initial_xmin = None
        self.initial_xmax = None
        # Create a combo box for selecting the edit mode
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["Drag", "Add", "Remove"])
        self.mode_selector.setFixedWidth(120)  # Set width to 200 pixels
        self.mode_selector.currentTextChanged.connect(self.set_edit_mode)

        # Create navigation buttons
        self.navigation_bar = self.create_navigation_bar()

        # Layout to embed the canvas, combo box, and navigation bar
        self.layout = QVBoxLayout()
        self.layout.addWidget(self.mode_selector)
        self.layout.addWidget(self.canvas)
        self.layout.addWidget(self.navigation_bar)
        self.setLayout(self.layout)

    def create_navigation_bar(self):
        """
        Create a navigation bar with icons and labels, and attach callbacks.
        """
        def make_btn(icon_name=None, text=None, callback=None, rotate=False, tooltip=None):
            btn = QPushButton()
            if icon_name:
                # icon = self.style().standardIcon(getattr(QStyle, icon_name))
                icon = qta.icon(icon_name)
                if rotate:
                    pixmap = icon.pixmap(QSize(48, 48))
                    # Rotate the pixmap by 90 degrees
                    transform = QTransform().rotate(rotate)
                    rotated_pixmap = pixmap.transformed(transform)
                    # Create a new icon from the rotated pixmap
                    icon = QIcon(rotated_pixmap)
                btn.setIcon(icon)
                btn.setIconSize(QSize(48, 48))
            if text:
                btn.setText(text)
            # Set the button to be flat and square
            btn.setFlat(True)
            btn.setStyleSheet("""
                QPushButton {
                    margin: 4px;
                    width: 56px;
                    height: 56px;
                    border: none;
                }
            """)
            if callback:
                btn.clicked.connect(callback)
            if tooltip is not None:
                btn.setToolTip(tooltip)
            return btn

        # Button definitions with standard Qt icons or custom icons
        begin = make_btn('fa6s.right-to-bracket', None,
                         self.go_to_start, 180, 'Goto Start')
        left = make_btn('fa6s.backward', None,
                        self.pan_left, False, 'Pan Left')
        prev = make_btn('fa6s.square-caret-left', None,
                        self.prev, False, 'Previous Non-Normal R-top')
        wider = make_btn('ei.zoom-out', None, self.zoom_out, False, 'Zoom Out')
        zoom = make_btn('ei.zoom-in', None, self.zoom_in, False, 'Zoom In')
        next = make_btn('fa6s.square-caret-right', None,
                        self.next, False, 'Next Non-Normal R-top')
        right = make_btn('fa6s.forward', None,
                         self.pan_right, False, 'Pan Right')
        end = make_btn('fa6s.right-to-bracket', None,
                       self.go_to_end, False, 'Goto End')

        # Layout to hold buttons
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        for btn in [begin, left, prev, zoom, wider, next, right, end]:
            nav_layout.addWidget(btn)

        # Container widget for the navigation buttons
        nav_widget = QWidget()
        nav_widget.setLayout(nav_layout)
        nav_widget.setFixedHeight(50)  # Fixed height for the navigation bar

        return nav_widget

    def set_edit_mode(self, mode):
        self.mode_selector.setCurrentText(mode)
        self.edit_mode = mode
        self.line_handler.update_mode(mode)

    def zoom_in(self):
        x_range = (self.data.x_max - self.data.x_min) / 3
        middle = (self.data.x_max + self.data.x_min) / 2
        self.data.x_min = middle - x_range
        self.data.x_max = middle + x_range
        self.update_view()

    def zoom_out(self):
        x_range = (self.data.x_max - self.data.x_min) / 1.5
        middle = (self.data.x_max + self.data.x_min) / 2
        self.data.x_min = max(middle - x_range, self.data.ecg.time.iat[0])
        self.data.x_max = min(
            self.data.x_min + (2 * x_range), self.data.ecg.time.iat[-1])
        self.update_view()

    def pan_left(self):
        x_range = self.data.x_max - self.data.x_min
        self.data.x_min = max(
            self.data.ecg.time.iat[0], self.data.x_min - x_range)
        self.data.x_max = self.data.x_min + x_range
        self.update_view()

    def pan_right(self):
        x_range = self.data.x_max - self.data.x_min
        self.data.x_min = min(
            self.data.ecg.time.iat[-1] - x_range, self.data.x_min + x_range)
        self.data.x_max = self.data.x_min + x_range
        self.update_view()

    def go_to_start(self):
        x_range = self.data.x_max - self.data.x_min
        self.data.x_min = self.data.ecg.time.iat[0]
        self.data.x_max = self.data.x_min + x_range
        self.update_view()

    def go_to_end(self):
        x_range = self.data.x_max - self.data.x_min
        self.data.x_max = self.data.ecg.time.iat[-1]
        self.data.x_min = self.data.x_max - x_range
        self.update_view()

    def next(self):
        x_range = self.data.x_max - self.data.x_min
        idx = (self.data.RTops["ID"] != "N") & (
            self.data.RTops["time"] > self.data.x_max)
        center = self.data.RTops.loc[idx,
                                     "time"].iloc[0] if idx.any() else None

        if center is not None:
            self.data.x_min = center - (0.5 * x_range)
            self.data.x_max = self.data.x_min + x_range

        self.update_view()

    def prev(self):
        x_range = self.data.x_max - self.data.x_min
        idx = (self.data.RTops["ID"] != "N") & (
            self.data.RTops["time"] < self.data.x_min)
        center = self.data.RTops.loc[idx,
                                     "time"].iloc[-1] if idx.any() else None

        if center is not None:
            self.data.x_min = center - (0.5 * x_range)
            self.data.x_max = self.data.x_min + x_range

        self.update_view()

    def update_plot(self):
        """
        Redraw the ECG plot, R-top times, and breathing rate (if available).
        This function also adjusts the plot properties for the selected x-axis limits.
        """
        self.plot_ecg_signal(self.ax_ecg, self.data.ecg.time,
                             self.data.ecg.level)  # type: ignore
        # Plot R-top times if available in the data
        if hasattr(self.data, "RTops"):
            # Plot only R-tops within x_min and x_max
            visibles = self.data.RTops[
                (self.data.RTops["time"] >= self.data.x_min -
                 1) & (self.data.RTops["time"] <= self.data.x_max + 1)
            ]

            if len(visibles) < 100:
                self.plot_rtop_times(
                    self.ax_ecg, visibles, self.line_handler
                )  # Plot VLines in the current view, if there are less than 100
                self.ax_ecg.set_ylim(self.ax_ecg.get_ylim()[
                                     0], self.ax_ecg.get_ylim()[1] * 1.2)

            self.set_ecg_plot_properties(
                self.ax_ecg, self.data.x_min, self.data.x_max)

            # Plot the breathing rate if available in the data
            if self.ax_br is not None and self.data.br is not None:
                self.plot_breathing_rate(
                    self.ax_br, self.data.br.time, self.data.br.level, self.data.x_min, self.data.x_max, self.line_handler
                )
                self.set_br_plot_properties(
                    self.ax_br, self.data.x_min, self.data.x_max)

            self.ax_overview.figure.canvas.draw()
            self.fig.canvas.draw_idle()

    def on_press(self, event):
        """
        Handles the mouse press event on the overview plot to initiate dragging.
        Determines the area (left, right, or center) that is clicked for zoom adjustment.
        """
        if event.inaxes == self.ax_overview:  # If click is on the overview plot
            # Check if the press is within the draggable region (x_min, x_max)
            if self.data.x_min <= event.xdata <= self.data.x_max:
                self.initial_xmin, self.initial_xmax = self.data.x_min, self.data.x_max
                dist = self.data.x_max - self.data.x_min
                # Determine drag mode based on proximity to the edges of the zoom box
                if abs(event.xdata - self.data.x_min) < 0.3 * dist:
                    self.drag_mode = "left"
                elif abs(event.xdata - self.data.x_max) < 0.3 * dist:
                    self.drag_mode = "right"
                else:
                    self.drag_mode = "center"
        elif self.edit_mode == "Add":
            if event.inaxes == self.ax_ecg:
                datapoint = pd.DataFrame(
                    [{"time": event.xdata, "ID": "N", "epoch": None, "ibi": float("nan")}])
                self.data.RTops = pd.concat(
                    [self.data.RTops, datapoint], ignore_index=True)
                self.sort_rtop()
                self.update_plot()

    def on_drag(self, event):
        """
        Handles the dragging event for adjusting the zoom region based on the drag mode.
        Adjusts the x_min and x_max limits depending on where the mouse is dragged.
        """
        if event.inaxes == self.ax_overview:  # If click is on the overview plot
            # Adjust the zoom limits based on drag mode (left, right, or center)
            if self.drag_mode == "left":
                self.data.x_min = min(event.xdata, self.data.x_max - 0.1)
            elif self.drag_mode == "right":
                self.data.x_max = max(event.xdata, self.data.x_min + 0.1)
            elif self.drag_mode == "center":
                dx = event.xdata - 0.5 * \
                    (self.initial_xmin + self.initial_xmax)
                self.data.x_min = self.initial_xmin + dx
                self.data.x_max = self.initial_xmax + dx
            # Update the zoom box position
            self.positional_patch.set_x(self.data.x_min)
            self.positional_patch.set_width(self.data.x_max - self.data.x_min)
            self.fig.canvas.draw_idle()

    def on_release(self, event):
        """
        Resets the dragging mode upon mouse release.
        """
        if event.inaxes == self.ax_overview:
            self.drag_mode = None
            self.update_plot()
            self.fig.canvas.draw_idle()

    def calculate_figsize(self):
        """
        Helper to get figure dimensions in inches.
        """
        return (15, 3)

    def create_figure_axes(self, data):
        """
        Create and return figure and axes for ECG and optional breathing data.
        Parameters:
        - data (object): Contains ECG and optional breathing data.
        Returns:
        - fig (Figure): Matplotlib figure containing all plots.
        - ax_ecg (Axes): Axis for the ECG signal plot.
        - ax_overview (Axes): Axis for the overview plot.
        - ax_br (Axes, optional): Axis for breathing rate if data is available.
        """
        figsize = self.calculate_figsize()
        if data.br is not None:
            fig, (ax_ecg, ax_br, ax_overview) = plt.subplots(3, 1,
                                                             figsize=figsize, sharex=False, gridspec_kw={"height_ratios": [6, 1, 1]})
        else:
            fig, (ax_ecg, ax_overview) = plt.subplots(2, 1,
                                                      figsize=figsize, sharex=False, gridspec_kw={"height_ratios": [4, 1]})
            ax_br = None

        # self.canvas.setParent(None)  # Remove old canvas from layout
        # self.canvas = FigureCanvas(self.fig)
        # self.layout.insertWidget(1, self.canvas)  # Insert new canvas in correct position

        return fig, ax_ecg, ax_overview, ax_br

    def plot_overview(self, ax, ecg_time, ecg_level, x_min, x_max):
        """
        Plots the ECG signal on an overview plot with a shaded rectangle indicating the zoom region.
        """
        ax.clear()
        ax.plot(ecg_time, ecg_level, linewidth=0.25, alpha=0.5, color="green")
        ax.set_title("")
        # Initialize a draggable patch for the overview plot
        positional_patch = patches.Rectangle(
            (x_min, ax.get_ylim()[0]),
            x_max - x_min,
            ax.get_ylim()[1] - ax.get_ylim()[0],
            color="blue",
            alpha=0.2,
            animated=False,
        )
        ax.add_patch(positional_patch)
        ax.set_yticks([])
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        return positional_patch

    def plot_rtop_times(self, ax, visibles, line_handler):
        """
        Plots vertical lines and arrows for each R-top time with labels indicating the IBI value.
        """
        h = ax.get_ylim()[1] + (0.05 * (ax.get_ylim()[1] - ax.get_ylim()[0]))
        line_handler.clear()
        for rtop in visibles.itertuples():
            line_handler.add_line(rtop.time, color=self.RTopColors[rtop.ID])
            if rtop.ibi != 0:
                # Draw a double-sided arrow from the current R-top to the next
                arrow = FancyArrowPatch(
                    (rtop.time, h),
                    (rtop.time + rtop.ibi, h),
                    arrowstyle="<->",
                    color="blue",
                    mutation_scale=5,
                    linewidth=0.5,
                )
                ax.add_patch(arrow)
                ax.text(
                    rtop.time + (0.5 * rtop.ibi),
                    h,  # Offset above the plot
                    f"{1000 * rtop.ibi:.0f}",
                    fontsize=6,
                    rotation=0,
                    horizontalalignment="center",
                    verticalalignment="bottom",
                    color="blue",
                    bbox=dict(
                        facecolor=ax.get_facecolor(),
                        edgecolor=ax.get_facecolor(),
                        alpha=0.4,
                    ),
                )

    def set_ecg_plot_properties(self, ax, x_min, x_max):
        """
        Configure ECG plot properties.
        """
        tdisp = round(math.log10(x_max - x_min), 0)
        ax.set_title("")
        ax.set_xlabel("Time (seconds)")
        ax.set_xlim(x_min, x_max)
        ax.xaxis.set_major_locator(MultipleLocator(
            math.pow(10, tdisp - 1)))  # Major ticks every 1 second
        # Minor ticks every 0.2 seconds
        ax.xaxis.set_minor_locator(
            MultipleLocator(math.pow(10, tdisp - 1) / 5))
        ax.get_yaxis().set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["top"].set_visible(False)
        if self.ax_br is not None:
            ax.get_xaxis().set_visible(False)
            ax.spines["bottom"].set_visible(False)
            ax.set_xlabel("")

    def set_br_plot_properties(self, ax, x_min, x_max):
        """
        Configure ECG plot properties.
        """
        tdisp = round(math.log10(x_max - x_min), 0)
        ax.set_title("")
        ax.set_xlabel("Time (seconds)")
        ax.set_xlim(x_min, x_max)
        ax.xaxis.set_major_locator(MultipleLocator(
            math.pow(10, tdisp - 1)))  # Major ticks every 1 second
        # Minor ticks every 0.2 seconds
        ax.xaxis.set_minor_locator(
            MultipleLocator(math.pow(10, tdisp - 1) / 5))
        ax.get_yaxis().set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["top"].set_visible(False)

    def plot_ecg_signal(self, ax, ecg_time, ecg_level):
        """
        Plot the ECG signal on the provided axis.
        """
        ax.clear()
        ax.plot(ecg_time, ecg_level, label="ECG Signal",
                color="red", linewidth=0.8, alpha=1)
        ax.set_xlim(self.data.x_min, self.data.x_max)

    def plot_breathing_rate(self, ax, br_time, br_level, x_min, x_max, line_handler):
        """
        Plot breathing rate data on a separate axis.
        """
        ax.clear()
        ax.plot(br_time, br_level, label="Breathing Signal",
                color="green", linewidth=0.8, alpha=1)
        ax.set_xlim(x_min, x_max)

    def update_view(self):
        """
        Updates the plot view by replotting data and adjusting the positional patch.
        """
        self.update_plot()
        self.positional_patch.set_x(self.data.x_min)
        self.positional_patch.set_width(self.data.x_max - self.data.x_min)

        self.ax_overview.figure.canvas.draw()
        self.fig.canvas.draw_idle()

    # Callback to update R-top times upon dragging a line
    def update_rtop(self, old_x, new_x):
        """
        Update the position of an R-top time after dragging.
        This function updates the 'RTops' series.
        Args:
            old_x (float): Original value of the dragged r-top.
            new_x (float): The new R-top time to update to.
        """
        # Find the index of the R-top time closest to the original position
        closest_idx = (self.data.RTops["time"] - old_x).abs().idxmin()
        # Update the R-top time at the closest index with the new value
        self.data.RTops.at[closest_idx, "time"] = new_x
        self.sort_rtop()

    def remove_rtop(self, old_x, new_x):
        """
        Removes an R-top time.
        This function updates the 'RTops' series.
        Args:
            old_x (float): Original value of the to-be removed r-top.
        """
        closest_idx = (self.data.RTops["time"] - new_x).abs().idxmin()
        self.data.RTops = self.data.RTops.drop(index=closest_idx)
        self.sort_rtop()

    def sort_rtop(self):
        """
        Sort the R-top times in ascending order and reset the index.
        This function updates the 'RTops' series and recalculates the IBI series.
        """
        self.data.RTops = self.data.RTops.sort_values(by="time")
        IBI = np.append(np.diff(self.data.RTops["time"]), float("nan"))
        self.data.RTops["ibi"] = IBI
        self.update_plot()

    def prepPlot(self, data, fig=None, x_min=None, x_max=None):
        """
        Plot and preprocess the ibi data with interactive features for zooming,
        dragging lines, and selecting modes for adding, removing, or finding R-top times.

        Parameters:
        - data (object): A data object containing ECG and optional breathing (br) data.
        - x_min (float, optional): Minimum x-axis value for the ECG plot. Defaults to the minimum in data.
        - x_max (float, optional): Maximum x-axis value for the ECG plot. Defaults to the maximum in data.

        Interactive Features:
        - Draggable lines for R-top times (ECG peaks).
        - Adjustable zoom region using the overview plot.
        - Mode selection for dragging, adding, finding, or removing R-top times.
        """
        self.data = data
        self.setVisible(True)
        # Main Plot: Configure theme
        plt.ioff()
        plt.title("")

        # Initialize x-axis limits based on input or data

        x_min = x_min if x_min is not None else self.data.ecg.time.min()
        x_max = x_max if x_max is not None else self.data.ecg.time.max()

        if not hasattr(self.data, 'x_min'):
            self.data.x_min = x_min
            self.data.x_max = x_max
        self.data.x_min = self.data.x_min if self.data.x_min is not None else x_min
        self.data.x_max = self.data.x_max if self.data.x_max is not None else x_max

        # Create figure and axis handles
        if fig is None:
            self.fig, self.ax_ecg, self.ax_overview, self.ax_br = self.create_figure_axes(
                data)
        else:
            self.ax_ecg = self.fig.axes[0]
            self.ax_overview = self.fig.axes[1]
            if len(self.fig.axes) > 2:
                self.ax_br = self.fig.axes[2]

        self.fig.canvas.toolbar_visible = False
        self.fig.canvas.header_visible = False
        self.fig.tight_layout()

        self.line_handler = LineHandler(
            self.ax_ecg, callback_drag=self.update_rtop, callback_remove=self.remove_rtop)
        self.positional_patch = self.plot_overview(
            self.ax_overview, data.ecg.time, data.ecg.level, self.data.x_min, self.data.x_max)
        # State variables for dragging
        self.edit_mode = 'Drag'
        self.line_handler.update_mode('Drag')

        self.initial_xmin, self.initial_xmax = self.data.x_min, self.data.x_max

        self.update_plot()

        # Connect the patch dragging events
        bpe = self.fig.canvas.mpl_connect("button_press_event", self.on_press)
        bod = self.fig.canvas.mpl_connect('motion_notify_event', self.on_drag)
        bor = self.fig.canvas.mpl_connect(
            'button_release_event', self.on_release)
        self.canvas.setParent(None)  # Remove old canvas from layout
        self.canvas = FigureCanvas(self.fig)
        # Insert new canvas in correct position
        self.layout.insertWidget(1, self.canvas)

        if self.mode_selector.currentText() is None:
            self.mode_selector.setCurrentText("Drag")

        self.set_edit_mode(self.mode_selector.currentText()
                           )  # Default edit mode

        self.canvas.draw()

        return self.fig
