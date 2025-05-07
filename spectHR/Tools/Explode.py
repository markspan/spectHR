def explode(DataSet):
    """
    Filters and explodes the 'epoch' column of a DataSet's RTops DataFrame based on visible epochs.

    This function processes RTops data within a DataSet object:
    1. Determines visible epochs based on `active_epochs` (if available) or `unique_epochs`.
    2. Filters RTops rows to include only visible epochs in the 'epoch' column.
    3. Explodes the 'epoch' column where it contains lists of epochs.
    4. Removes rows with missing IBI values.

    Args:
        DataSet: An object containing RTops data and epoch-related metadata.
            Required attributes:
                - RTops (pd.DataFrame): A DataFrame with at least:
                    * 'epoch': A column containing lists of epochs.
                    * 'ibi': A column with inter-beat interval (IBI) data.
                - active_epochs (dict, optional): A dict where keys are epoch names 
                    and values are booleans indicating visibility.
                - unique_epochs (iterable): A fallback list of all epochs.

    Returns:
        pd.DataFrame: A DataFrame where:
            - The 'epoch' column is exploded into individual rows.
            - Rows with missing 'ibi' values are dropped.

    Example:
        exploded_data = explode(my_dataset)
    """
    # Step 1: Determine visible epochs
    if hasattr(DataSet, 'active_epochs') and isinstance(DataSet.active_epochs, dict):
        # Use active_epochs if available, filtering for epochs marked as visible (True)
        visible_epochs = {epoch for epoch, visible in DataSet.active_epochs.items() if visible}
    else:
        # Fallback: Assume all unique_epochs are visible
        visible_epochs = set(DataSet.unique_epochs)
    
    # Step 2: Filter RTops rows containing any visible epochs
    def filter_visible_epochs(epoch_list):
        """Helper function to filter epochs within a list based on visibility."""
        return [epoch for epoch in epoch_list if epoch in visible_epochs]
    
    filtered_data = DataSet.RTops.copy()
    filtered_data = filtered_data[
        filtered_data['epoch'].apply(
            lambda epochs: any(epoch in visible_epochs if visible_epochs is not None else False for epoch in epochs)
            if epochs is not None else False
        )
    ]
    #filtered_data = filtered_data[
    #    filtered_data['epoch'].apply(lambda epochs: any(epoch in visible_epochs if visible_epochs is not None else False for epoch in epochs))
    #]
    
    # Step 3: Clean and explode the 'epoch' column
    filtered_data['epoch'] = filtered_data['epoch'].apply(filter_visible_epochs)  # Keep only visible epochs
    exploded_data = filtered_data.explode('epoch')  # Explode epoch lists into individual rows
    
    # Step 4: Drop rows with missing IBI values
    return exploded_data.dropna(subset=['ibi'])
