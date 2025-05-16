import spectHR as cs


def PreProcessFile(file_path, reset = True):
    """
    Load and preprocess an ECG dataset from a given file path.

    This function performs the following steps:
    1. Loads the dataset using SpectHRDataset.
    2. Applies a high-pass filter with a 1 Hz cutoff.
    3. Detects R-peaks if they are not already present in the dataset.

    Parameters
    ----------
    file_path : str
        Path to the ECG data file to be processed.

    Returns
    -------
    dataset : SpectHRDataset
        The preprocessed dataset, ready for visualization or analysis.
    """
    # Load dataset without resetting metadata; auto-detect polarity
    dataset = cs.SpectHRDataset(file_path, reset=reset, flip='auto')
    if file_path.endswith('.xdf'):
        dataset = cs.borderData(dataset)
        # Apply a high-pass filter to remove baseline drift
        dataset = cs.filterECGData(dataset, {"filterType": "highpass", "cutoff": 1})

        # Compute R-peaks only if not already present
        if not hasattr(dataset, 'RTops'):
            dataset = cs.calcPeaks(dataset)

    return dataset
