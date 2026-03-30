import json
import os
from pathlib import Path

from spectHR.Tools.Logger import logger
from spectHR.DataSet.Series.CardioMetricsMixin import load_frequency_bands
from platformdirs import user_documents_path
from PySide6.QtWidgets import QTreeWidgetItem
from PySide6.QtCore import Qt


# ── Default workspace structure ────────────────────────────────────────────────
#
# The workspace JSON now has two top-level chapters:
#   "Directories"       — data, cache, and output paths
#   "FrequencyAnalysis" — HRV frequency band definitions
#
# Additional chapters can be added here and to the JSON in the future
# without touching any other code.

_DEFAULT_WORKSPACE = {
    "Directories": {
        "DataDirectory": str(user_documents_path() / "spectHR"),
        "CacheDirectory": str(user_documents_path() / "spectHR/cache"),
        "OutputDirectory": str(user_documents_path() / "spectHR/export"),
    },
    "FrequencyAnalysis": {
        "bands": {
            "VLF": {"low": 0.003, "high": 0.04, "color": "blue"},
            "LF": {"low": 0.04, "high": 0.15, "color": "green"},
            "HF": {"low": 0.15, "high": 0.40, "color": "red"},
        }
    },
}


def LoadWorkspace(json_file=None):
    """
    Load the workspace from a JSON file and apply all configuration sections.

    If no file is given, ~/Documents/DefaultWorkSpace.json is used.
    If the file does not exist it is created with the built-in defaults.

    Side effects
    ------------
    - Creates the cache and output directories if they do not exist.
    - Calls load_frequency_bands() to update HRV_FREQUENCY_BANDS in
      CardioMetricsMixin from the FrequencyAnalysis section.

    Returns
    -------
    dict
        The full nested workspace dict with at least "Directories" and
        "FrequencyAnalysis" keys.
    """
    import copy

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

            # Deep-merge loaded values into defaults so missing keys stay safe
            for chapter, defaults in workspace.items():
                if chapter in loaded:
                    if isinstance(defaults, dict):
                        defaults.update(loaded[chapter])
                    else:
                        workspace[chapter] = loaded[chapter]

        except Exception as e:
            logger.warning(f"Could not load workspace file: {e}")
    else:
        # Write defaults to disk on first run
        _ensure_dirs(workspace)
        with open(json_file, "w") as f:
            json.dump(workspace, f, indent=4)

    _ensure_dirs(workspace)

    # Apply frequency band configuration
    try:
        bands = workspace["FrequencyAnalysis"]["bands"]
        load_frequency_bands(bands)
    except (KeyError, Exception) as e:
        logger.warning(f"Could not load frequency bands from workspace: {e}")

    return workspace


def _ensure_dirs(workspace: dict) -> None:
    """Create cache and output directories if they do not exist."""
    dirs = workspace.get("Directories", {})
    for key in ("CacheDirectory", "OutputDirectory"):
        path = dirs.get(key)
        if path and not os.path.exists(path):
            os.makedirs(path)


def SaveWorkspace(workspace: dict, json_file) -> None:
    """
    Save the full workspace dict (all chapters) to a JSON file.

    This is a standalone helper so callers are not duplicating json.dump logic.
    """
    with open(json_file, "w") as f:
        json.dump(workspace, f, indent=4)


def PopulateTree(treewidget, workspace):
    """Populate a QTreeWidget with files from the workspace DataDirectory."""
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
