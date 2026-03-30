from pathlib import Path

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.Actions.calcPeaks import calcPeaks
from spectHR.Actions.filterSignal import filterSignal
from spectHR.Tools.Logger import logger


def PreProcessFile(workspace, file_path, reset=False, border=False):
    """
    Load and preprocess an ECG dataset from a given file path.

    Preprocessing is performed for *all ECG bands* in the file:
    - baseline filtering
    - R-peak detection
    - HRV/CardioSeries construction per band
    """

    # ------------------------------------------------------------
    # Load dataset
    # ------------------------------------------------------------
    dataset = PhysioData(Path(workspace["Directories"]["DataDirectory"]) / file_path)
    if dataset.has_ecg == False:
        return dataset
    # ------------------------------------------------------------
    # Normalize single-band datasets into band_map
    # ------------------------------------------------------------
    if not hasattr(dataset, "band_map") or not dataset.band_map:
        try:
            _ = dataset["ecg"]
        except KeyError:
            return dataset

        logger.debug("Normalizing single-band ECG dataset into band_map")

        dataset.band_map = {"ecg": {"ecg": "ecg"}}
        dataset.active_band = "ecg"

    # ------------------------------------------------------------
    # Multi-band preprocessing
    # ------------------------------------------------------------
    dataset.has_ecg = True

    original_band = dataset.active_band
    bands = list(dataset.band_map.keys())

    logger.info(f"Preprocessing ECG for {len(bands)} band(s): {bands}")

    for band in bands:
        logger.info(f"Preprocessing band '{band}'")
        dataset.active_band = band

        # Logical ECG now resolves to this band
        ecg = dataset["ecg"]

        # 1. Filter
        filterSignal(
            ecg,
            filter_type="highpass",
            cutoff=1.0,
        )

        # 2. Detect peaks → routed to band-specific HRV internally
        calcPeaks(
            ecg,
            min_peak_distance_ms=300.0,
            classify=True,
        )

    # Restore original band (important for UI consistency)
    dataset.active_band = original_band or bands[0]
    return dataset
