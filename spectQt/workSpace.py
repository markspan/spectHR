import os
import json
from PySide6.QtWidgets import QTreeWidgetItem

def LoadWorkspace():
    default_json = os.path.join(os.path.dirname(__file__), "DefaultWorkSpace.json")
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
                workspace.update({k: loaded.get(k, v) for k, v in workspace.items()})
        except Exception as e:
            print(f"Could not load workspace file: {e}")

    return workspace

def PopulateTree(treewidget, workspace):
    treewidget.clear()
    categories = {
        "XDF Files": "*.xdf"
    }
    treewidget.setHeaderLabels(["File Name"]) 
    for label, pattern in categories.items():
        parent = QTreeWidgetItem([label])
        files = sorted(
            [f for f in os.listdir(workspace["DataDirectory"]) if f.endswith(pattern.split("*")[-1])]
        )
        for fname in files:
            QTreeWidgetItem(parent, [fname])
        treewidget.addTopLevelItem(parent)
