import matplotlib.pyplot as plt
import numpy as np
import copy
from spectHR.Tools.Logger import logger

def gantt(dataset, labels=True):
    """
    Generates a Gantt chart from the provided dataset, visualizing the duration and time range
    of active epochs. Optionally annotates the start and end times on the chart.

    Parameters:
        dataset (object): A dataset containing R-top information and epochs. 
                          Must have 'RTops' DataFrame and optionally 'active_epochs'.
                          - 'RTops' is expected to include:
                              - 'epoch' (list of epoch names)
                              - 'time' (float or int representing time)
        labels (bool, optional): If True, displays start and end time annotations on the chart. 
                                 Defaults to False.

    Returns:
        matplotlib.figure.Figure: A Matplotlib figure object containing the Gantt chart.

    Notes:
        - If 'active_epochs' exists and is a dictionary, only the visible epochs will be plotted.
        - If 'active_epochs' does not exist, all unique epochs in the dataset will be plotted.
        - The Gantt chart uses a colormap to assign unique colors to each epoch.
    """
    
    # Deep copy RTops to avoid modifying the original dataset
    RTops = copy.deepcopy(dataset.RTops)
    
    # Filter epochs to keep only those marked as visible
    if hasattr(dataset, 'active_epochs') and isinstance(dataset.active_epochs, dict):
        # Use 'active_epochs' to filter visible epochs
        visible_epochs = {epoch: visible for epoch, visible in dataset.active_epochs.items() if visible}
    else:
        # If 'active_epochs' is not defined, assume all epochs are visible
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
    color_dict = dict(zip(epoch_names, colors))  # Map epoch names to specific colors

    # Initialize the Gantt chart figure and axis
    fig, ax = plt.subplots(figsize=(15, 7))
    
    # Plot horizontal bars for each epoch
    for i, epoch in enumerate(epoch_names):
        ax.barh(
            epoch,                      # Position on y-axis
            durations[i],               # Bar width (duration)
            left=start_times[i],        # Start time (left edge of bar)
            color=color_dict[epoch],    # Assigned color for the epoch
            edgecolor="black",          # Black border around bars
            alpha=0.5                   # Set transparency
        )
    
    # Customize y-axis ticks and labels
    ax.set_yticks(range(len(epoch_names)))
    ax.set_yticklabels([name.title() for name in epoch_names])  # Convert epoch names to title case

    # Add axis labels and grid
    ax.set_xlabel("Time")            # Label x-axis
    ax.set_ylabel("")                # No y-axis label
    ax.set_title("")                 # No chart title
    ax.grid(axis="y", linestyle="-", alpha=0.7)  # Add grid lines along the y-axis
    
    # Optionally annotate start and end times on each bar
    if labels:
        for i, row in epochs_gantt.iterrows():
            # Annotate start time
            ax.text(
                row["start"], i, f"{round(row['start'])}", 
                va="center", ha="left", fontsize=8, rotation='vertical'
            )
            # Annotate end time
            ax.text(
                row["end"], i, f"{round(row['end'])}", 
                va="center", ha="right", fontsize=8, rotation='vertical'
            )
    
    # Adjust layout to avoid clipping
    plt.tight_layout()
    
    # Return the Matplotlib figure
    return fig
