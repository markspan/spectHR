import matplotlib.patches as patches
from matplotlib.ticker import MultipleLocator
from matplotlib.patches import FancyArrowPatch
import matplotlib.pyplot as plt
import matplotlib
import ipyvuetify as v

import ipywidgets as widgets
import math

from spectHR.ui.LineHandler import LineHandler
from spectHR.Tools.Logger import logger
from spectHR.Plots.Poincare import poincare

import numpy as np
import pandas as pd


def prepPlot(data, x_min=None, x_max=None, plot_poincare=False):
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
    # Local Functions:
    logger.info(f"Created a prepPlot")
    RTopColors = {
        "N": "blue",
        "L": "cyan",
        "S": "magenta",
        "TL": "orange",
        "SL": "turquoise",
        "SNS": "lightseagreen",
    }

    def update_plot(x_min, x_max):
        """
        Redraw the ECG plot, R-top times, and breathing rate (if available).
        This function also adjusts the plot properties for the selected x-axis limits.

        Parameters:
        - x_min (float): Minimum x-axis limit for the zoomed view.
        - x_max (float): Maximum x-axis limit for the zoomed view.
        """
        plot_ecg_signal(ax_ecg, data.ecg.time, data.ecg.level)
        # Plot R-top times if available in the data
        if hasattr(data, "RTops"):
            # Plot only R-tops within x_min and x_max
            visibles = data.RTops[
                (data.RTops["time"] >= x_min - 1) & (data.RTops["time"] <= x_max + 1)
            ]

            if len(visibles) < 100:
                plot_rtop_times(
                    ax_ecg, visibles, line_handler
                )  # Plot VLines in the current view, if there are less then 100

            ax_ecg.set_ylim(ax_ecg.get_ylim()[0], ax_ecg.get_ylim()[1] * 1.2)

        set_ecg_plot_properties(ax_ecg, x_min, x_max)

        # Plot the breathing rate if available in the data
        if ax_br is not None and data.br is not None:
            plot_breathing_rate(
                ax_br, data.br.time, data.br.level, x_min, x_max, line_handler
            )
            set_br_plot_properties(ax_br, x_min, x_max)
            
        data.x_min = x_min
        data.x_max = x_max
        fig.canvas.draw_idle()

    def on_press(event):
        """
        Handles the mouse press event on the overview plot to initiate dragging.
        Determines the area (left, right, or center) that is clicked for zoom adjustment.
        """
        nonlocal drag_mode, initial_xmin, initial_xmax
        if event.inaxes == ax_overview:  # If click is on the overview plot
            # Check if the press is within the draggable region (x_min, x_max)
            if x_min <= event.xdata <= x_max:
                initial_xmin, initial_xmax = x_min, x_max
                dist = x_max - x_min
                # Determine drag mode based on proximity to the edges of the zoom box
                if abs(event.xdata - x_min) < 0.3 * dist:
                    drag_mode = "left"
                elif abs(event.xdata - x_max) < 0.3 * dist:
                    drag_mode = "right"
                else:
                    drag_mode = "center"

        elif edit_mode == "Add":
            if event.inaxes == ax_ecg:
                if edit_mode == "Add":
                    datapoint = pd.DataFrame([{"time": event.xdata, "ID": "N", "epoch": None,"ibi": float("nan")}])
                    data.RTops = pd.concat([data.RTops, datapoint], ignore_index=True)
                    sort_rtop()
                    update_plot(x_min, x_max)

    def on_drag(event):
        """
        Handles the dragging event for adjusting the zoom region based on the drag mode.
        Adjusts the x_min and x_max limits depending on where the mouse is dragged.
        """
        nonlocal x_min, x_max, drag_mode, initial_xmin, initial_xmax
        if event.inaxes == ax_overview:  # If click is on the overview plot
            # Adjust the zoom limits based on drag mode (left, right, or center)
            if drag_mode == "left":
                x_min = min(event.xdata, x_max - 0.1)
            elif drag_mode == "right":
                x_max = max(event.xdata, x_min + 0.1)
            elif drag_mode == "center":
                dx = event.xdata - 0.5 * (initial_xmin + initial_xmax)
                x_min = initial_xmin + dx
                x_max = initial_xmax + dx
            # Update the zoom box position
            positional_patch.set_x(x_min)
            positional_patch.set_width(x_max - x_min)
            fig.canvas.draw_idle()

    def on_release(event):
        """
        Resets the dragging mode upon mouse release.
        """
        nonlocal drag_mode
        if event.inaxes == ax_overview: 
            drag_mode = None
            update_plot(x_min, x_max)
            fig.canvas.draw_idle()

    # Helper to get figure dimensions in inches
    def calculate_figsize():
        dpi = matplotlib.rcParams["figure.dpi"]  # Get the current DPI setting
        return (13,5)

    def create_figure_axes(data):
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

        figsize = calculate_figsize()

        if data.br is not None:
            fig, (ax_ecg, ax_br, ax_overview) = plt.subplots(3, 1,
                figsize=figsize, sharex=False, gridspec_kw={"height_ratios": [6, 1, 1]})
        else:
            fig, (ax_ecg, ax_overview) = plt.subplots(2, 1,
                figsize=figsize, sharex=False, gridspec_kw={"height_ratios": [4, 1]})
            ax_br = None
        return fig, ax_ecg, ax_overview, ax_br

    def plot_overview(ax, ecg_time, ecg_level, x_min, x_max):
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

    def plot_rtop_times(ax, visibles, line_handler):
        """
        Plots vertical lines and arrows for each R-top time with labels indicating the IBI value.
        """
        h = ax.get_ylim()[1] + (0.05 * (ax.get_ylim()[1] - ax.get_ylim()[0]))
        line_handler.clear()
        for rtop in visibles.itertuples():
            line_handler.add_line(rtop.time, color=RTopColors[rtop.ID])
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

    def set_ecg_plot_properties(ax, x_min, x_max):
        """
        Configure ECG plot properties.
        """
        tdisp = round(math.log10(x_max - x_min), 0)

        ax.set_title("")
        ax.set_xlabel("Time (seconds)")
        ax.set_xlim(x_min, x_max)
        ax.xaxis.set_major_locator(MultipleLocator(math.pow(10, tdisp - 1)))  # Major ticks every 1 second
        ax.xaxis.set_minor_locator(MultipleLocator(math.pow(10, tdisp - 1) / 5))  # Minor ticks every 0.2 seconds
        ax.get_yaxis().set_visible(False)
        ax.spines[["right", "left", "top"]].set_visible(False)
        if ax_br is not None:
            ax.get_xaxis().set_visible(False)
            ax.spines[["bottom"]].set_visible(False)
            ax.set_xlabel("")
        
    def set_br_plot_properties(ax, x_min, x_max):
        """
        Configure ECG plot properties.
        """
        tdisp = round(math.log10(x_max - x_min), 0)

        ax.set_title("")
        ax.set_xlabel("Time (seconds)")
        ax.set_xlim(x_min, x_max)
        ax.xaxis.set_major_locator(MultipleLocator(math.pow(10, tdisp - 1)))  # Major ticks every 1 second
        ax.xaxis.set_minor_locator(MultipleLocator(math.pow(10, tdisp - 1) / 5))  # Minor ticks every 0.2 seconds
        ax.get_yaxis().set_visible(False)
        ax.spines[["right", "left", "top"]].set_visible(False)

    def plot_ecg_signal(ax, ecg_time, ecg_level):
        """
        Plot the ECG signal on the provided axis.
        """
        ax.clear()
        ax.plot(ecg_time, ecg_level, label="ECG Signal", color="red", linewidth=.8, alpha=1)
        ax.set_xlim(x_min, x_max)

    def plot_breathing_rate(ax, br_time, br_level, x_min, x_max, line_handler):
        """
        Plot breathing rate data on a separate axis.
        """
        ax.clear()
        ax.plot(br_time, br_level, label="Breathing Signal", color="green", linewidth=.8, alpha=1)
        ax.set_xlim(x_min, x_max)

    def update_view():
        """
        Updates the plot view by replotting data and adjusting the positional patch.
        """
        nonlocal x_min, x_max
        update_plot(x_min, x_max)
        positional_patch.set_x(x_min)
        positional_patch.set_width(x_max - x_min)
        fig.canvas.draw_idle()

    """
    definitions of the callbacks for the navigation buttons
    """
    def on_begin_clicked(button, e, d):
        """
        Moves the view to the start of the dataset.
        """
        nonlocal x_min, x_max
        x_range = x_max - x_min
        x_min = data.ecg.time.iat[0]
        x_max = x_min + x_range
        update_view()

    def on_left_clicked(button, e, d):
        """
        Moves the view one range-width to the left.
        """
        nonlocal x_min, x_max
        x_range = x_max - x_min
        x_min = max(data.ecg.time.iat[0], x_min - x_range)
        x_max = x_min + x_range
        update_view()

    def on_prev_clicked(button, e, d):
        """
        Moves the view to center on the previous R-top with a specific label.
        """
        nonlocal x_min, x_max
        x_range = x_max - x_min
        idx = (data.RTops["ID"] != "N") & (data.RTops["time"] < x_min)
        center = data.RTops.loc[idx, "time"].iloc[-1] if idx.any() else None

        if center is not None:
            x_min = center - (0.5 * x_range)
            x_max = x_min + x_range
        update_view()

    def on_wider_clicked(button, e, d):
        """
        Increases the view width by 1.5 times.
        """
        nonlocal x_min, x_max
        x_range = (x_max - x_min) / 1.5
        middle = (x_max + x_min) / 2
        x_min = max(middle - x_range, data.ecg.time.iat[0])
        x_max = min(x_min + (2 * x_range), data.ecg.time.iat[-1])
        update_view()

    def on_zoom_clicked(button, e, d):
        """
        Decreases the view width by 1/3 for zooming in.
        """
        nonlocal x_min, x_max
        x_range = (x_max - x_min) / 3
        middle = (x_max + x_min) / 2
        x_min = middle - x_range
        x_max = middle + x_range
        update_view()

    def on_nex_clicked(button, e, d):
        """
        Moves the view to center on the next R-top with a specific label.
        """
        nonlocal x_min, x_max
        x_range = x_max - x_min
        idx = (data.RTops["ID"] != "N") & (data.RTops["time"] > x_max)
        center = data.RTops.loc[idx, "time"].iloc[0] if idx.any() else None

        if center is not None:
            x_min = center - (0.5 * x_range)
            x_max = x_min + x_range
        update_view()

    def on_right_clicked(button, e, d):
        """
        Moves the view one range-width to the right.
        """
        nonlocal x_min, x_max
        x_range = x_max - x_min
        x_min = min(data.ecg.time.iat[-1] - x_range, x_min + x_range)
        x_max = x_min + x_range
        update_view()

    def on_end_clicked(button, e, d):
        """
        Moves the view to the end of the dataset.
        """
        nonlocal x_min, x_max
        x_range = x_max - x_min
        x_max = data.ecg.time.iat[-1]
        x_min = x_max - x_range
        update_view()

    # Callback to update R-top times upon dragging a line
    def update_rtop(old_x, new_x):
        """
        Update the position of an R-top time after dragging.

        This function updates the 'RTops' series

        Args:
            old_x (float): original value of the dragged r-top
            new_x (float): The new R-top time to update to
        """
        # Find the index of the R-top time closest to the original position
        closest_idx = (data.RTops["time"] - old_x).abs().idxmin()
        # Update the R-top time at the closest index with the new value
        data.RTops.at[closest_idx, "time"] = new_x
        sort_rtop()

    def remove_rtop(old_x, new_x):
        """
        Removes an R-top time.

        This function updates the 'RTops' series

        Args:
            old_x (float): original value of the to-be removed r-top
        """
        logger.info(f'removing line at: {old_x} vs {new_x}')
        closest_idx = (data.RTops["time"] - new_x).abs().idxmin()
        data.RTops = data.RTops.drop(index=closest_idx)
        sort_rtop()

    def sort_rtop():
        """
        Sort the R-top times in ascending order and reset the index

        This function updates the 'RTops' series and recaclulates the IBI series

        Args:
            None
        """
        data.RTops = data.RTops.sort_values(by="time")
        IBI = np.append(np.diff(data.RTops["time"]), float("nan"))
        data.RTops["ibi"] = IBI
        update_plot(x_min, x_max)
    # Mode selection dropdown widget for interaction
    def update_mode(change, e, d):
        """
        Update the mode in LineHandler based on dropdown selection.
        """
        nonlocal edit_mode
        line_handler.update_mode(change.v_model)
        edit_mode = change.v_model

    # Main Plot: Configure theme
    plt.ioff()
    plt.title("")

    # Initialize x-axis limits based on input or data

    x_min = x_min if x_min is not None else data.ecg.time.min()
    x_max = x_max if x_max is not None else data.ecg.time.max()
    
    x_min = data.x_min if data.x_min is not None else x_min
    x_max = data.x_max if data.x_max is not None else x_max
    
    # Create figure and axis handles
    fig, ax_ecg, ax_overview, ax_br = create_figure_axes(data)

    fig.canvas.toolbar_visible = False
    fig.canvas.header_visible = False
    fig.tight_layout()

    line_handler = LineHandler(ax_ecg, callback_drag=update_rtop, callback_remove=remove_rtop)
    # area_handler = AreaHandler(fig, ax_ecg)
    positional_patch = plot_overview(ax_overview, data.ecg.time, data.ecg.level, x_min, x_max)

    # State variables for dragging
    drag_mode = None
    initial_xmin, initial_xmax = x_min, x_max

    update_plot(x_min, x_max)
    
    # Connect the patch dragging events
    bpe = fig.canvas.mpl_connect("button_press_event", on_press)
    bod = fig.canvas.mpl_connect('motion_notify_event', on_drag)
    bor = fig.canvas.mpl_connect('button_release_event', on_release)

    edit_mode = "Drag"
    '''
    Edit the Mode slector 
    '''
    mode_select = v.Select(
        color="primary",
        v_model="Drag",
        class_="ma-2",
        label="Mode",
        items=["Drag", "Add", "Find", "Remove"],
    )

    mode_select.on_event("change", update_mode)

    figure_title = widgets.HTML(
        value="<center><H2>ECG signal</H2></center>",
        layout=widgets.Layout(width="100%", justify_content="center"),
    )

    spacer = widgets.Label(value="", layout=widgets.Layout(width="200px"))

    header = widgets.HBox(
        [mode_select, figure_title, spacer],
        layout=widgets.Layout(justify_content="center", width="100%"),
    )
    """
    Create navigation Buttons. These are used to navigate through the dataset
    """
    begin = v.Btn(
        color="primary",
        class_="ma-2",
        children=[v.Icon(left=True, children=["fa-step-backward"])],
    )
    left = v.Btn(
        color="primary",
        class_="ma-2",
        children=[v.Icon(left=True, children=["fa-arrow-left"])],
    )
    prev = v.Btn(
        color="primary",
        class_="ma-2",
        children=[v.Icon(left=True, children=["fa-chevron-left"]), 'Previous'],
    )
    wider = v.Btn(
        color="primary",
        class_="ma-2",
        children=[v.Icon(left=True, children=["fa-search-minus"])],
    )
    zoom = v.Btn(
        color="primary",
        class_="ma-2",
        children=[v.Icon(left=True, children=["fa-search-plus"])],
    )
    nex = v.Btn(
        color="primary",
        class_="ma-2",
        children=[v.Icon(left=True, children=["fa-chevron-right"]), 'Next'],
    )
    right = v.Btn(
        color="primary",
        class_="ma-2",
        children=[v.Icon(left=True, children=["fa-arrow-right"])],
    )
    end = v.Btn(
        color="primary",
        class_="ma-2",
        children=[v.Icon(left=True, children=["fa-step-forward"])],
    )
    """
    Link the callbacks for the navigation buttons
    """
    begin.on_event("click", on_begin_clicked)
    left.on_event("click", on_left_clicked)
    prev.on_event("click", on_prev_clicked)
    wider.on_event("click", on_wider_clicked)
    zoom.on_event("click", on_zoom_clicked)
    nex.on_event("click", on_nex_clicked)
    right.on_event("click", on_right_clicked)
    end.on_event("click", on_end_clicked)

    """
    Create the navigation HBox
    """
    navigator = widgets.HBox(
        [begin, left, prev, zoom, wider, nex, right, end],
        layout=widgets.Layout(
            justify_content="center", width="100%", border="0px solid green"
        ),
    )

    """
    Embed the Matplotlib figure in the AppLayout
    Create the GUI
    """
    P = None
    if plot_poincare:
        poincare_result = poincare(data)
        poincare_plot = poincare_result["poincare_plot"]
        poincare_plot.set_size_inches(4, 4)
        P = poincare_plot.canvas

    GUI = widgets.AppLayout(
        header=header,
        left_sidebar=None,
        center=widgets.Output(
            layout=widgets.Layout(
                margin="0 0 0 0", padding="0 0 0 0", border="0px solid red"
            )
        ),
        right_sidebar=P,
        footer=navigator,
        pane_heights=[1, 5, 1],
    )

    with GUI.center:
        display(fig.canvas)

    fig.canvas.draw_idle()

    # Control box for displaying controls and plot
    return GUI
