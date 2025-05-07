import matplotlib.pyplot as plt
import numpy as np
import mplcursors
import copy
import ipyvuetify as v
from matplotlib.patches import Ellipse
from ipywidgets import HBox, VBox, Checkbox, Output, Layout
from spectHR.Tools.Params import *
from spectHR.Tools.Logger import logger

def poincare(dataset):
    """
    Generate an interactive Poincaré plot for a dataset containing Inter-Beat Intervals (IBI).

    This function plots the relationship between consecutive IBIs to form a Poincaré plot.
    It includes the following features:
      - Scatter points representing IBIs for specific epochs.
      - Ellipses to represent SD1 and SD2 measures of variability for each epoch.
      - Interactive visibility toggling for epochs using checkboxes.
      - Hover functionality to display epoch information and time of points.

    Args:
        dataset: An object with the following attributes:
            - RTops (pd.DataFrame): DataFrame containing IBI and epoch data.
                Required columns: 'ibi', 'epoch', 'time'.
            - unique_epochs (iterable): List or set of unique epoch labels.
            - active_epochs (dict, optional): A dictionary with epoch names as keys
                and booleans as values, indicating visibility of each epoch.

    Returns:
        ipywidgets.HBox: A widget containing the interactive Poincaré plot and checkboxes
            for toggling the visibility of epochs.

    Raises:
        ValueError: If required columns ('ibi', 'epoch', 'time') are missing or
            the DataFrame has fewer than two rows.
    """

    # Step 1: Preprocess the dataset
    # Create a deep copy of the RTops DataFrame to avoid modifying the original data
    df = dataset.RTops.dropna(subset=['epoch'])  # Drop rows with missing 'epoch'
    df = df[df['epoch'].apply(lambda x: len(x) > 0)]

    # Validate the DataFrame structure
    required_columns = {'ibi', 'epoch', 'time'}
    if not all(col in df.columns for col in required_columns):
        raise ValueError("DataFrame must contain 'ibi', 'epoch', and 'time' columns.")
    if df.shape[0] < 2:
        raise ValueError("The DataFrame must have at least two rows for a Poincaré plot.")

    # Initialize the figure and axes for the plot
    fig, ax = plt.subplots(figsize=(7, 7))
    fig.canvas.toolbar_visible = False  # Hide the default Matplotlib toolbar

    # Dictionaries to store scatter, ellipse handles, and global indices for hover functionality
    scatter_handles = {}
    ellipse_handles = {}
    global_indices = {}

    # Ensure 'active_epochs' exists; initialize it if not present
    if not hasattr(dataset, 'active_epochs'):
        dataset.active_epochs = {epoch: True for epoch in dataset.unique_epochs}

    filtered_by_epoch = {}
    # Step 2: create the sets
    for unique_epoch in dataset.unique_epochs:
        # Create a mask for the current epoch
        mask = [ unique_epoch in sublist if sublist is not None else False for sublist in dataset.RTops.epoch ]    
        # Subset dataset.RTops for the current epoch
        filtered_by_epoch[unique_epoch] = dataset.RTops[mask]

    # `filtered_by_epoch` now contains the filtered data for each unique epoch
    def on_hover(sel):
        """
        Display epoch and time information on hover.
    
        Args:
            sel: The cursor selection event triggered by hovering.
        """
        scatter_idx = list(scatter_handles.values()).index(sel.artist)
        epoch = list(scatter_handles.keys())[scatter_idx]
    
        # Get the x-value (IBI) of the hovered point
        x_value = sel.artist.get_offsets()[sel.index, 0]  # x-coordinate (IBI value)
        y_value = sel.artist.get_offsets()[sel.index, 1]  # x-coordinate (IBI value)
        
        # Get the DataFrame for the current epoch
        data = filtered_by_epoch[epoch]
    
        # Find the index of the IBI value in the dataset, assuming 'ibi' is a column in 'data'
        ibi_idx = (np.abs(data.ibi - x_value)).argmin()  # Find the closest IBI value
        
        # Get the time corresponding to that index
        time_value = data.time.iloc[ibi_idx]
    
        # Update the annotation text with epoch and time information
        sel.annotation.set_text(f"{epoch.title()}:\nIBI={1000*x_value:.0f}-{1000*y_value:.0f}ms\nTime={time_value:.1f}s")
        

    # Step 3: Plot scatter points and SD1/SD2 ellipses for each epoch
    for epoch in sorted(dataset.unique_epochs):
        visible = dataset.active_epochs[epoch]

        data = filtered_by_epoch[epoch]
        
        x = data.ibi[:-1].reset_index(drop=True)
        y = data.ibi[1:].reset_index(drop=True)
        # Scatter plot for current epoch
        scatter_handles[epoch] = ax.scatter(x, y, label=epoch.title(), alpha=0.2)
        ibm = np.mean(x)  # Mean IBI
        col = scatter_handles[epoch].get_facecolor()  # Color of the scatter points

        # Create an ellipse to represent SD1 and SD2 variability
        ellipse = Ellipse(
            (ibm, ibm), sd1(data.ibi)/500, sd2(data.ibi)/500, angle=-45,
            linewidth=1, zorder=1, facecolor=col, edgecolor='k', alpha=.35
        )
        ax.add_artist(ellipse)
        ellipse_handles[epoch] = ellipse

        # Set visibility based on 'active_epochs'
        scatter_handles[epoch].set_visible(visible)
        ellipse.set_visible(visible)

    # Step 4: Add hover functionality using mplcursors
    cursor= mplcursors.cursor([scatter for scatter in scatter_handles.values()], highlight=True, hover=False)
    cursor.connect("add", on_hover)
    
    # Step 5: Plot formatting
    ax.set_title('')
    ax.set_xlabel('IBI (ms)', fontsize=12)
    ax.set_ylabel('Next IBI (ms)', fontsize=12)
    ax.axline((0, 0), slope=1, color='gray', linestyle='--', linewidth=0.7)  # Line of identity
    # Filter scatter handles based on the dict_values
    scatters = [handle for label, handle in scatter_handles.items() if dataset.active_epochs[label]]

    ax.legend(handles = scatters, fontsize=9, title=None)

    ax.grid(True)

    # Step 6: Create output widget for the plot
    plot_output = Output()
    with plot_output:
        plt.show()

    # Step 7: Add checkboxes for toggling epoch visibility
    vbox_layout = Layout(display='flex', flex_flow='column', align_items='flex-start', gap='0px')
    checkbox_layout = Layout(margin='0px', padding='0px', height='20px')
    checkboxes = {}

    def update_visibility(change):
        """
        Update the visibility of scatter points and ellipses when a checkbox is toggled.

        Args:
            change: A dictionary containing the checkbox state change information.
        """
        epoch = change.owner.label
        visible = change.new
        scatter_handles[epoch].set_visible(visible)
        ellipse_handles[epoch].set_visible(visible)
        dataset.active_epochs[epoch] = visible

        with plot_output:
            fig.canvas.draw_idle()


    for epoch in sorted(dataset.unique_epochs, key=lambda v: v.upper()):
        checkbox = v.Checkbox(
            v_model=dataset.active_epochs[epoch],  # Bind checkbox value
            label=epoch,
            class_='ma-0 pa-0', 
            style_='height: 21px;'
        )
        checkbox.observe(update_visibility, names='v_model')  # Listen for changes to checkbox
        checkboxes[epoch] = checkbox
         
    # Step 8: Return the interactive HBox layout with plot and checkboxes
    return HBox([plot_output, v.Container(children=list(checkboxes.values()), style_="width: auto; min-width: 150px; margin: 0px;")])