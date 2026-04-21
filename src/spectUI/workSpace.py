import copy
import json
import os
from pathlib import Path

from spectHR.Tools.Logger import logger
from spectHR.DataSet.Series.CardioMetricsMixin import (
    load_frequency_bands,
    load_welch_params,
    load_lombscargle_params,
    load_carspan_params,  # <-- nieuw
    load_ci_alpha,
    load_method,
)
from platformdirs import user_documents_path
from PySide6.QtWidgets import QTreeWidgetItem
from PySide6.QtCore import Qt

_DEFAULT_WORKSPACE = {
    "Directories": {
        "DataDirectory": str(user_documents_path() / "spectHR"),
        "CacheDirectory": str(user_documents_path() / "spectHR/cache"),
        "OutputDirectory": str(user_documents_path() / "spectHR/export"),
    },
    "FrequencyAnalysis": {
        "method": "welch",
        "bands": {
            "VLF": {"low": 0.003, "high": 0.04, "color": "blue"},
            "LF": {"low": 0.04, "high": 0.15, "color": "darkgreen"},
            "HF": {"low": 0.15, "high": 0.40, "color": "red"},
        },
        "welch": {
            "fs": 4.0,
            "nperseg": 256,
            "noverlap": 128,
            "nfft": 1024,
            "window": "hann",
        },
        "lombscargle": {
            "nfreqs": 1000,
            "fmin_floor": 1e-4,
        },
        "carspan": {
            "freq_resolution": 0.01,
            "window": "5% cosine bell",
            "smooth_for_display": True,
        },
        "confidence_interval_alpha": 0.05,
    },
    "CardioParameters": {
        "IbiClassification": {
            "window_length": 51,
            "n_std": 4.0,
            "max_ibi_sec": 2.0,
            "min_peak_distance_ms": 300.0,
        },
        "EcgPreprocessing": {
            "filter_type": "highpass",
            "filter_cutoff": 1.0,
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base; override values win."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def LoadWorkspace(json_file=None) -> dict:
    """
    Load the workspace from a JSON file and apply all configuration sections.

    If no file is given, ~/Documents/DefaultWorkSpace.json is used.
    If the file does not exist it is created with the built-in defaults.

    Side effects
    ------------
    - Creates CacheDirectory and OutputDirectory if absent.
    - Calls load_frequency_bands()    — updates HRV_FREQUENCY_BANDS.
    - Calls load_welch_params()       — updates WELCH_PARAMS.
    - Calls load_lombscargle_params() — updates LOMBSCARGLE_PARAMS.
    - Calls load_carspan_params()     — updates CARSPAN_PARAMS.
    - Calls load_ci_alpha()           — updates CI_ALPHA.
    - Calls load_method()             — updates METHOD
                                        ("welch", "lombscargle", or "carspan").

    CardioParameters is returned in the dict for callers to read directly
    (preProcessFile.py, PhysioData.preprocess_ecg).

    Returns
    -------
    dict
        The full nested workspace with all chapters.
    """
    workspace = copy.deepcopy(_DEFAULT_WORKSPACE)

    if json_file is None:
        json_file = user_documents_path() / "DefaultWorkSpace.json"

    specthr_dir = user_documents_path() / "spectHR"
    if not specthr_dir.exists():
        os.makedirs(specthr_dir)

    if os.path.exists(json_file):
        try:
            with open(json_file, "r") as f:
                loaded = json.load(f)
            workspace = _deep_merge(workspace, loaded)
        except Exception as e:
            logger.warning(f"Could not load workspace file: {e}")
    else:
        _ensure_dirs(workspace)
        with open(json_file, "w") as f:
            json.dump(workspace, f, indent=4)

    _ensure_dirs(workspace)

    # Apply FrequencyAnalysis to CardioMetricsMixin module-level globals
    fa = workspace.get("FrequencyAnalysis", {})

    try:
        load_frequency_bands(fa["bands"])
    except (KeyError, Exception) as e:
        logger.warning(f"Could not apply frequency bands: {e}")

    try:
        load_welch_params(fa["welch"])
    except (KeyError, Exception) as e:
        logger.warning(f"Could not apply Welch params: {e}")

    try:
        load_lombscargle_params(fa["lombscargle"])
    except (KeyError, Exception) as e:
        logger.warning(f"Could not apply Lomb-Scargle params: {e}")

    try:  # <-- nieuw
        load_carspan_params(fa["carspan"])
    except (KeyError, Exception) as e:
        logger.warning(f"Could not apply CARSPAN params: {e}")

    try:
        load_ci_alpha(fa["confidence_interval_alpha"])
    except (KeyError, Exception) as e:
        logger.warning(f"Could not apply CI alpha: {e}")

    try:
        load_method(fa["method"])
    except (KeyError, Exception) as e:
        logger.warning(f"Could not apply PSD method: {e}")

    return workspace


def SaveWorkspace(workspace: dict, json_file) -> None:
    """Save the full workspace dict (all chapters) to a JSON file."""
    with open(json_file, "w") as f:
        json.dump(workspace, f, indent=4)


def _ensure_dirs(workspace: dict) -> None:
    """Create CacheDirectory and OutputDirectory if they do not exist."""
    dirs = workspace.get("Directories", {})
    for key in ("CacheDirectory", "OutputDirectory"):
        path = dirs.get(key)
        if path and not os.path.exists(path):
            os.makedirs(path)


def PopulateTree(treewidget, workspace: dict) -> None:
    """Populate a QTreeWidget with files from workspace DataDirectory."""
    treewidget.clear()
    data_dir = workspace["Directories"]["DataDirectory"]
    categories = {
        "XDF Files": "*.xdf",
        "CARSPAN EVT Files": "*.evt",
        "RR Text Files": "*.txt",
    }
    treewidget.setHeaderLabels(["WorkSpace Data"])
    for label, pattern in categories.items():
        parent = QTreeWidgetItem([label])
        extension = pattern.split("*")[-1].lower()
        files = sorted(
            [f for f in os.listdir(data_dir) if f.lower().endswith(extension)]
        )
        for fname in files:
            if fname.lower() == "requirements.txt":
                continue
            item = QTreeWidgetItem(parent, [fname])
            item.setData(
                0,
                Qt.UserRole,
                {
                    "type": "dataset",
                    "filename": fname,
                    "bands_expanded": False,
                },
            )
        treewidget.addTopLevelItem(parent)
    treewidget.expandAll()
