import json
import os
import sys

from PySide6.QtWidgets import QTreeWidgetItem


def exe_dir_path(filename):
    """Get path to a file in the same directory as the executable."""
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base_dir, filename)


def LoadWorkspace(default_json=None):
    if default_json is None:
        default_json = exe_dir_path("DefaultWorkSpace.json")

    cwd = os.getcwd()
    workspace = {
        "DataDirectory": cwd,
        "CacheDirectory": os.path.join(cwd, "cache"),
        "OutputDirectory": cwd
    }

    if os.path.exists(default_json):
        try:
            with open(default_json, "r") as f:
                loaded = json.load(f)
                workspace.update({k: loaded.get(k, v)
                                 for k, v in workspace.items()})
        except Exception as e:
            print(f"Could not load workspace file: {e}")
    else:
        with open(default_json, "w") as f:
            json.dump(workspace, f, indent=4)
    return workspace


def PopulateTree(treewidget, workspace):
    treewidget.clear()
    categories = {
        "XDF Files": "*.xdf",
        "CARSPAN EVT Files": "*.evt",
        "RR Text Files": "*.txt"
    }

    treewidget.setHeaderLabels(["File Name"])
    for label, pattern in categories.items():

        parent = QTreeWidgetItem([label])
        extension = pattern.split("*")[-1].lower()
        files = sorted(
            [f for f in os.listdir(workspace["DataDirectory"])
             if f.lower().endswith(extension)]
        )
        for fname in files:
            if fname.lower() != 'requirements.txt':
                QTreeWidgetItem(parent, [fname])
        treewidget.addTopLevelItem(parent)
