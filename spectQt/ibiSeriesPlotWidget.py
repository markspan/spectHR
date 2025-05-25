import math

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
import qtawesome as qta

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import MultipleLocator
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QTransform
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spectHR import TimeSeries
from spectHR.ui.LineHandler import LineHandler


class IBISeriesPlotWidget(QWidget):
    """
    A widget for plotting and interacting with heart rate data.
    This widget provides functionalities for zooming, panning, and navigating through heart rate data.
    """

    def __init__(self, parent=None):
        """
        Initialize the IBISeriesPlotWidget.

        Parameters:
        - parent (QWidget, optional): The parent widget. Defaults to None.
        """
        super().__init__(parent)

        # Set up the Matplotlib figure and canvas
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)

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
        self.ax_heartrate = None
        self.ax_overview = None
        self.positional_patch = None
        self.drag_mode = None
        self.initial_xmin = None
        self.initial_xmax = None

        # Create navigation buttons
        self.navigation_bar = self.create_navigation_bar()

        # Layout to embed the canvas, combo box, and navigation bar
        self.layout = QVBoxLayout()
        self.layout.addWidget(self.canvas)
        self.layout.addWidget(self.navigation_bar)
        self.setLayout(self.layout)

    def create_navigation_bar(self):
        """
        Create a navigation bar with icons and labels, and attach callbacks.

        Returns:
        - QWidget: A widget containing the navigation bar.
        """
        def make_btn(icon_name=None, text=None, callback=None, rotate=False):
            """
            Helper function to create a button with an icon and optional text.

            Parameters:
            - icon_name (str, optional): The name of the icon. Defaults to None.
            - text (str, optional): The text to display on the button. Defaults to None.
            - callback (function, optional): The function to call when the button is clicked. Defaults to None.
            - rotate (int, optional): The angle to rotate the icon. Defaults to False.

            Returns:
            - QPushButton: The created button.
            """
            btn = QPushButton()
            if icon_name:
                icon = qta.icon(icon_name)
                if rotate:
                    pixmap = icon.pixmap(QSize(48, 48))
                    transform = QTransform().rotate(rotate)
                    rotated_pixmap = pixmap.transformed(transform)
                    icon = QIcon(rotated_pixmap)
                btn.setIcon(icon)
                btn.setIconSize(QSize(48, 48))
            if text:
                btn.setText(text)
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
            return btn

        # Button definitions with standard Qt icons or custom icons
        begin = make_btn('fa6s.right-to-bracket', None, self.go_to_start, 180)
        left = make_btn('fa6s.backward', None, self.pan_left)
        prev = make_btn('fa6s.square-caret-left', None, self.prev)
        wider = make_btn('ei.zoom-out', None, self.zoom_out)
        zoom = make_btn('ei.zoom-in', None, self.zoom_in)
        next = make_btn('fa6s.square-caret-right', None, self.next)
        right = make_btn('fa6s.forward', None, self.pan_right)
        end = make_btn('fa6s.right-to-bracket', None, self.go_to_end)

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

    def zoom_in(self):
        """
        Zoom in on the heart rate data.
        """
        x_range = (self.data.x_max - self.data.x_min) / 3
        middle = (self.data.x_max + self.data.x_min) / 2
        self.data.x_min = middle - x_range
        self.data.x_max = middle + x_range
        self.update_view()

    def zoom_out(self):
        """
        Zoom out of the heart rate data.
        """
        x_range = (self.data.x_max - self.data.x_min) / 1.5
        middle = (self.data.x_max + self.data.x_min) / 2
        self.data.x_min = max(middle - x_range, self.data.heartrate.time.iat[0])
        self.data.x_max = min(self.data.x_min + (2 * x_range), self.data.heartrate.time.iat[-1])
        self.update_view()

    def pan_left(self):
        """
        Pan the view to the left.
        """
        x_range = self.data.x_max - self.data.x_min
        self.data.x_min = max(self.data.heartrate.time.iat[0], self.data.x_min - x_range)
        self.data.x_max = self.data.x_min + x_range
        self.update_view()

    def pan_right(self):
        """
        Pan the view to the right.
        """
        x_range = self.data.x_max - self.data.x_min
        self.data.x_min = min(self.data.heartrate.time.iat[-1] - x_range, self.data.x_min + x_range)
        self.data.x_max = self.data.x_min + x_range
        self.update_view()

    def go_to_start(self):
        """
        Move the view to the start of the data.
        """
        x_range = self.data.x_max - self.data.x_min
        self.data.x_min = self.data.heartrate.time.iat[0]
        self.data.x_max = self.data.x_min + x_range
        self.update_view()

    def go_to_end(self):
        """
        Move the view to the end of the data.
        """
        x_range = self.data.x_max - self.data.x_min
        self.data.x_max = self.data.heartrate.time.iat[-1]
        self.data.x_min = self.data.x_max - x_range
        self.update_view()

    def next(self):
        """
        Move the view to the next significant point in the data.
        """
        x_range = self.data.x_max - self.data.x_min
        idx = (self.data.RTops["ID"] != "N") & (self.data.RTops["time"] > self.data.x_max)
        center = self.data.RTops.loc[idx, "time"].iloc[0] if idx.any() else None

        if center is not None:
            self.data.x_min = center - (0.5 * x_range)
            self.data.x_max = self.data.x_min + x_range

        self.update_view()

    def prev(self):
        """
        Move the view to the previous significant point in the data.
        """
        x_range = self.data.x_max - self.data.x_min
        idx = (self.data.RTops["ID"] != "N") & (self.data.RTops["time"] < self.data.x_min)
        center = self.data.RTops.loc[idx, "time"].iloc[-1] if idx.any() else None

        if center is not None:
            self.data.x_min = center - (0.5 * x_range)
            self.data.x_max = self.data.x_min + x_range

        self.update_view()

    def update_plot(self):
        """
        Redraw the heart rate plot and R-top times.
        This function also adjusts the plot properties for the selected x-axis limits.
        """
        self.plot_heartrate_signal(self.ax_heartrate, self.data.heartrate.time, self.data.heartrate.level)
        if hasattr(self.data, "RTops"):
            visibles = self.data.RTops[
                (self.data.RTops["time"] >= self.data.x_min - 1) & (self.data.RTops["time"] <= self.data.x_max + 1)
            ]

            if len(visibles) < 100:
                self.plot_rtop_times(
                    self.ax_heartrate, visibles, self.line_handler
                )
                self.ax_heartrate.set_ylim(self.ax_heartrate.get_ylim()[0], self.ax_heartrate.get_ylim()[1] * 1.2)

            self.set_heartrate_plot_properties(self.ax_heartrate, self.data.x_min, self.data.x_max)

            self.ax_overview.figure.canvas.draw()
            self.fig.canvas.draw_idle()

    def on_press(self, event):
        """
        Handles the mouse press event on the overview plot to initiate dragging.
        Determines the area (left, right, or center) that is clicked for zoom adjustment.
        """
        if event.inaxes == self.ax_overview:
            if self.data.x_min <= event.xdata <= self.data.x_max:
                self.initial_xmin, self.initial_xmax = self.data.x_min, self.data.x_max
                dist = self.data.x_max - self.data.x_min
                if abs(event.xdata - self.data.x_min) < 0.3 * dist:
                    self.drag_mode = "left"
                elif abs(event.xdata - self.data.x_max) < 0.3 * dist:
                    self.drag_mode = "right"
                else:
                    self.drag_mode = "center"
                self.update_plot()

    def on_drag(self, event):
        """
        Handles the dragging event for adjusting the zoom region based on the drag mode.
        Adjusts the x_min and x_max limits depending on where the mouse is dragged.
        """
        if event.inaxes == self.ax_overview:
            if self.drag_mode == "left":
                self.data.x_min = min(event.xdata, self.data.x_max - 0.1)
            elif self.drag_mode == "right":
                self.data.x_max = max(event.xdata, self.data.x_min + 0.1)
            elif self.drag_mode == "center":
                dx = event.xdata - 0.5 * (self.initial_xmin + self.initial_xmax)
                self.data.x_min = self.initial_xmin + dx
                self.data.x_max = self.initial_xmax + dx
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

        Returns:
        - tuple: The figure dimensions (width, height) in inches.
        """
        return (15, 3)

    def create_figure_axes(self, data):
        """
        Create and return figure and axes for heart rate data.

        Parameters:
        - data (object): Contains heart rate data.

        Returns:
        - fig (Figure): Matplotlib figure containing all plots.
        - ax_heartrate (Axes): Axis for the heart rate signal plot.
        - ax_overview (Axes): Axis for the overview plot.
        """
        figsize = self.calculate_figsize()
        fig, (ax_heartrate, ax_overview) = plt.subplots(2, 1,
            figsize=figsize, sharex=False, gridspec_kw={"height_ratios": [4, 1]})

        return fig, ax_heartrate, ax_overview

    def plot_overview(self, ax, heartrate_time, heartrate_level, x_min, x_max):
        """
        Plots the heart rate signal on an overview plot with a shaded rectangle indicating the zoom region.

        Parameters:
        - ax (Axes): The axis to plot on.
        - heartrate_time (array-like): The time values for the heart rate data.
        - heartrate_level (array-like): The heart rate levels.
        - x_min (float): The minimum x-value for the zoom region.
        - x_max (float): The maximum x-value for the zoom region.

        Returns:
        - positional_patch (Rectangle): The patch indicating the zoom region.
        """
        ax.clear()
        ax.plot(heartrate_time, heartrate_level, linewidth=0.25, alpha=0.5, color="green")
        ax.set_title("")
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

        Parameters:
        - ax (Axes): The axis to plot on.
        - visibles (DataFrame): The visible R-top times.
        - line_handler (LineHandler): The line handler for managing lines.
        """
        h = ax.get_ylim()[1] + (0.05 * (ax.get_ylim()[1] - ax.get_ylim()[0]))
        line_handler.clear()
        for rtop in visibles.itertuples():
            line_handler.add_line(rtop.time, color=self.RTopColors[rtop.ID])
            if rtop.ibi != 0:
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
                    h,
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

    def set_heartrate_plot_properties(self, ax, x_min, x_max):
        """
        Configure heart rate plot properties.

        Parameters:
        - ax (Axes): The axis to configure.
        - x_min (float): The minimum x-value.
        - x_max (float): The maximum x-value.
        """
        tdisp = round(math.log10(x_max - x_min), 0)
        ax.set_title("")
        ax.set_xlabel("Time (seconds)")
        ax.set_xlim(x_min, x_max)
        ax.xaxis.set_major_locator(MultipleLocator(math.pow(10, tdisp - 1)))
        ax.xaxis.set_minor_locator(MultipleLocator(math.pow(10, tdisp - 1) / 5))
        ax.get_yaxis().set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["top"].set_visible(False)

    def plot_heartrate_signal(self, ax, heartrate_time, heartrate_level):
        """
        Plot the heart rate signal on the provided axis.

        Parameters:
        - ax (Axes): The axis to plot on.
        - heartrate_time (array-like): The time values for the heart rate data.
        - heartrate_level (array-like): The heart rate levels.
        """
        ax.clear()
        ax.plot(heartrate_time, heartrate_level, label="HeartRate", color="red", linewidth=0.8, alpha=1)
        ax.set_xlim(self.data.x_min, self.data.x_max)

    def update_view(self):
        """
        Updates the plot view by replotting data and adjusting the positional patch.
        """
        self.update_plot()
        self.positional_patch.set_x(self.data.x_min)
        self.positional_patch.set_width(self.data.x_max - self.data.x_min)

        self.ax_overview.figure.canvas.draw()
        self.fig.canvas.draw_idle()

    def plotIBISeries(self, data, fig=None, x_min=None, x_max=None):
        """
        Plot the inter-beat interval (IBI) series.

        Parameters:
        - data (object): The data containing heart rate information.
        - fig (Figure, optional): The figure to plot on. Defaults to None.
        - x_min (float, optional): The minimum x-value. Defaults to None.
        - x_max (float, optional): The maximum x-value. Defaults to None.

        Returns:
        - fig (Figure): The figure containing the plot.
        """
        self.data = data
        heartrate_timestamps = data.RTops['time']
        heartrate_levels = data.RTops['ibi']

        self.data.heartrate = TimeSeries(heartrate_timestamps, heartrate_levels)
        plt.ioff()
        plt.title("")

        x_min = x_min if x_min is not None else self.data.heartrate.time.min()
        x_max = x_max if x_max is not None else self.data.heartrate.time.max()

        if not hasattr(self.data, 'x_min'):
            self.data.x_min = x_min
            self.data.x_max = x_max
        self.data.x_min = self.data.x_min if self.data.x_min is not None else x_min
        self.data.x_max = self.data.x_max if self.data.x_max is not None else x_max

        if fig is None:
            self.fig, self.ax_heartrate, self.ax_overview = self.create_figure_axes(data)
        else:
            self.ax_heartrate = self.fig.axes[0]
            self.ax_overview = self.fig.axes[1]

        self.fig.canvas.toolbar_visible = False
        self.fig.canvas.header_visible = False
        self.fig.tight_layout()

        self.line_handler = LineHandler(self.ax_heartrate, callback_drag=None, callback_remove=None)
        self.positional_patch = self.plot_overview(self.ax_overview, data.heartrate.time, data.heartrate.level, self.data.x_min, self.data.x_max)

        self.initial_xmin, self.initial_xmax = self.data.x_min, self.data.x_max

        self.update_plot()

        bpe = self.fig.canvas.mpl_connect("button_press_event", self.on_press)
        bod = self.fig.canvas.mpl_connect('motion_notify_event', self.on_drag)
        bor = self.fig.canvas.mpl_connect('button_release_event', self.on_release)
        
         # Remove the old canvas from the layout
        if self.canvas is not None:
            self.layout.removeWidget(self.canvas)
            self.canvas.setParent(None)
            self.canvas.deleteLater()  # Optional: Delete the old canvas to free up resources
            
        self.canvas = FigureCanvas(self.fig)
        self.layout.insertWidget(0, self.canvas)
        self.canvas.draw()

        return self.canvas
