# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from spectHR.DataSet.PhysioData import PhysioData
from spectHR.Tools.Logger import logger
from spectUI.workSpace import bp_calibration_from_workspace


def apply_bp_calibration(dataset, workspace):
    """Apply the manual blood-pressure calibration to *dataset* in place.

    Converts the raw blood-pressure ADC counts to mmHg using the
    workspace ``Calibration.bp_scale`` / ``bp_zero`` (mmHg = scale * raw +
    zero). Applied only when

    * the dataset actually has a ``bp`` channel,
    * the NFF header did not already carry a per-channel calibration
      (mirrors CARSPAN's "when not already included in the header" rule,
      tracked via ``dataset.channel_calibrated``), and
    * the calibration is not the identity (1.0 / 0.0), so an
      already-physical or deliberately-raw channel is left untouched.

    This lives in its own function so every dataset-load path (the cold
    load in ``MainWindow.on_file_selection`` *and* :func:`PreProcessFile`)
    applies the same calibration; otherwise reloading a single-band file
    would leave BP in raw counts.
    """
    bp_ts = dataset.timeseries.get("bp")
    if bp_ts is None:
        return
    header_calibrated = getattr(dataset, "channel_calibrated", {}).get("bp", False)
    if header_calibrated:
        return
    bp_scale, bp_zero = bp_calibration_from_workspace(workspace)
    if bp_scale != 1.0 or bp_zero != 0.0:
        bp_ts.values = bp_scale * bp_ts.values + bp_zero
        logger.info(
            "Applied manual BP calibration: mmHg = "
            f"{bp_scale:g} * raw + {bp_zero:g}"
        )


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

    # Manual blood-pressure calibration (raw ADC counts -> mmHg). CARSPAN
    # lets the user enter scale/zero in the *Specify data* dialog; we read
    # them from the workspace (Calibration.bp_scale / bp_zero).
    apply_bp_calibration(dataset, workspace)

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