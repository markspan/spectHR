import json
import os
import sys
from pathlib import Path
from spectHR.Tools.Logger import logger
from platformdirs import user_documents_path
from PySide6.QtWidgets import QTreeWidgetItem
from PySide6.QtCore import Qt

def LoadWorkspace(json_file=None):
    """Load workspace settings from a JSON file or create a default one."""
    if json_file is None:
        json_file = user_documents_path() / "DefaultWorkSpace.json"

    workspace = {
        "DataDirectory": str(user_documents_path() / 'spectHR'),
        "CacheDirectory": str(user_documents_path() / 'spectHR/cache'),
        "OutputDirectory": str(user_documents_path() / 'spectHR/export')
    }

    spectHRDir = user_documents_path() / 'spectHR'
    if not spectHRDir.exists():
        os.makedirs(spectHRDir)

    if os.path.exists(json_file):
        try:
            with open(json_file, "r") as f:
                loaded = json.load(f)
                workspace.update({k: loaded.get(k, v)
                                 for k, v in workspace.items()})
        except Exception as e:
            logger.info(f"Could not load workspace file: {e}")
    else:
        with open(json_file, "w") as f:
            if not os.path.exists(workspace["CacheDirectory"]):
                os.makedirs(workspace["CacheDirectory"])
            if not os.path.exists(workspace["OutputDirectory"]):
                os.makedirs(workspace["OutputDirectory"])
            json.dump(workspace, f, indent=4)
    return workspace


def PopulateTree(treewidget, workspace):
    """Populate a QTreeWidget with files from the workspace directories."""
    treewidget.clear()
    categories = {
        "XDF Files": "*.xdf",
        "CARSPAN EVT Files": "*.evt",
        "RR Text Files": "*.txt"
    }

    treewidget.setHeaderLabels(["WorkSpace Data"])
    for label, pattern in categories.items():

        parent = QTreeWidgetItem([label])
        extension = pattern.split("*")[-1].lower()
        files = sorted(
            [f for f in os.listdir(workspace["DataDirectory"])
             if f.lower().endswith(extension)]
        )

        for fname in files:
            if fname.lower() == "requirements.txt":
                continue

            item = QTreeWidgetItem(parent, [fname])

            # Attach metadata for lazy band handling
            item.setData(0, Qt.UserRole, {
                "type": "dataset",
                "filename": fname,
                "bands_expanded": False,
            })
        treewidget.addTopLevelItem(parent)
    treewidget.expandAll()
