# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The dock-protocol contract, checked against the real dock widgets.

Subprocess-isolated (Qt must not enter the shared pytest process).  Verifies
that the live docks satisfy :class:`~spectUI.dock_protocol.DataDock` (and the
timeline docks :class:`TimelineDock`), that the optional capability protocols
match the docks that carry those signals, that ``apply_config`` stores the
config without reloading, and that ``DataCoordinator.register`` rejects a
non-conforming widget loudly instead of silently doing nothing.
"""
from __future__ import annotations

import os
import subprocess
import sys

_DRIVER = r"""
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication([])

from spectUI.coordinator import DataChange, DataCoordinator
from spectUI.dock_protocol import (
    DataDock, EmitsAnnotation, EmitsEpochsChanged, EmitsPlotsExport, TimelineDock,
)
from spectUI.widgets import (
    BPSeriesWidget, EpochEditorWidget, HRSeriesWidget, PoincareWidget,
    ResultsTableWidget,
)

# --- core contract: every live dock is a DataDock --------------------------
for cls in (PoincareWidget, ResultsTableWidget, EpochEditorWidget,
            HRSeriesWidget, BPSeriesWidget):
    assert isinstance(cls(), DataDock), cls.__name__

# --- timeline docks additionally satisfy TimelineDock ----------------------
for cls in (HRSeriesWidget, BPSeriesWidget):
    assert isinstance(cls(), TimelineDock), cls.__name__
assert not isinstance(PoincareWidget(), TimelineDock)   # standalone, no window sync

# --- optional capabilities match the docks that carry the signals ----------
assert isinstance(PoincareWidget(), EmitsEpochsChanged)
assert isinstance(EpochEditorWidget(), EmitsEpochsChanged)
assert isinstance(PoincareWidget(), EmitsAnnotation)
assert isinstance(ResultsTableWidget(), EmitsPlotsExport)
assert not isinstance(HRSeriesWidget(), EmitsPlotsExport)
assert not isinstance(HRSeriesWidget(), EmitsEpochsChanged)

# --- apply_config stores the config without reloading a session ------------
poin = PoincareWidget()
sentinel = object()
poin.apply_config(sentinel)
assert poin._config is sentinel

# --- register enforces DataDock: a bare QWidget is rejected loudly ---------
coord = DataCoordinator()
try:
    coord.register(QWidget(), DataChange.HRV)
except TypeError:
    pass
else:
    raise SystemExit("register accepted a non-DataDock widget")

# --- register accepts a conforming dock ------------------------------------
coord.register(PoincareWidget(), DataChange.HRV)

print("DOCK_PROTOCOL_OK")
"""


def test_dock_protocol_offscreen():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0 and "DOCK_PROTOCOL_OK" in proc.stdout, (
        f"dock-protocol test failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
