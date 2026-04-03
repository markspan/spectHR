from pathlib import Path

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.Tools.Logger import logger


def PreProcessFile(workspace, file_path, reset=False, border=False):
    """
    Load and preprocess an ECG dataset from a given file path.

    Preprocessing parameters are read from workspace["CardioParameters"]:
    - EcgPreprocessing.filter_type          (default "highpass")
    - EcgPreprocessing.filter_cutoff        (default 1.0)
    - IbiClassification.min_peak_distance_ms (default 300.0)
    - IbiClassification.window_length       (default 51)
    - IbiClassification.n_std              (default 4.0)
    - IbiClassification.max_ibi_sec        (default 2.0)

    Preprocessing is performed for all ECG bands in the file.
    """
    dirs   = workspace["Directories"]
    cp     = workspace.get("CardioParameters", {})
    ecg_pp = cp.get("EcgPreprocessing", {})
    ibi_cl = cp.get("IbiClassification", {})

    filter_type    = ecg_pp.get("filter_type",   "highpass")
    filter_cutoff  = ecg_pp.get("filter_cutoff",  1.0)
    min_peak_dist  = ibi_cl.get("min_peak_distance_ms", 300.0)
    window_length  = ibi_cl.get("window_length",  51)
    n_std          = ibi_cl.get("n_std",           4.0)
    max_ibi_sec    = ibi_cl.get("max_ibi_sec",     2.0)

    dataset = PhysioData(Path(dirs["DataDirectory"]) / file_path)

    if not dataset.has_ecg:
        return dataset

    # Normalize single-band datasets into band_map
    if not hasattr(dataset, "band_map") or not dataset.band_map:
        try:
            _ = dataset["ecg"]
        except KeyError:
            return dataset
        logger.debug("Normalizing single-band ECG dataset into band_map")
        dataset.band_map  = {"ecg": {"ecg": "ecg"}}
        dataset.active_band = "ecg"
        dataset.has_ecg   = True

    original_band = dataset.active_band
    bands = list(dataset.band_map.keys())
    logger.info(f"Preprocessing ECG for {len(bands)} band(s): {bands}")

    for band in bands:
        logger.info(f"Preprocessing band '{band}'")
        dataset.active_band = band
        dataset.preprocess_ecg(
            filter_type=filter_type,
            filter_cutoff=filter_cutoff,
            min_peak_distance_ms=min_peak_dist,
            window_length=window_length,
            n_std=n_std,
            max_ibi_sec=max_ibi_sec,
            classify=True,
        )

    dataset.active_band = original_band or bands[0]
    return dataset