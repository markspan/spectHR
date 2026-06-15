# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Offscreen test for MainWindow dock availability.

Subprocess-isolated (Qt must not enter the shared pytest process).  When a
loaded recording lacks a source channel (e.g. blood pressure) the matching
dock is closed and its View-menu entry greyed out; it re-enables for a later
recording that carries the channel.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_DRIVER = r"""
import tempfile
import numpy as np
from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths
from PySide6.QtWidgets import QApplication

# Isolate Qt config so the real user settings are never touched.
cfg = tempfile.mkdtemp()
QCoreApplication.setApplicationName("spectHR_test")
QCoreApplication.setOrganizationName("spectHR_test")
QStandardPaths.setTestModeEnabled(True)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cfg)

app = QApplication.instance() or QApplication([])

import spectUI.MainWindow as mw
from spectHR.session import Epoch, Events, Samples, Session

w = mw.MainWindow()

# First run seeds the single settings file with the defaults.
from pathlib import Path
from platformdirs import user_config_dir
wf = Path(user_config_dir("spectHR")) / "workspace.json"
assert wf.exists(), "MainWindow did not create the default workspace.json"
assert "Directories" in __import__("json").loads(wf.read_text())

t = np.arange(0.0, 30.0, 0.01)
peaks = np.arange(0.5, 30.0, 0.8)
labels = np.full(peaks.shape, "N", dtype=object)


def make_session(with_bp):
    samples = {"ecg": Samples(t, np.sin(t), "ecg")}
    if with_bp:
        samples["bp"] = Samples(t, 90.0 + np.sin(t), "bp")
    return Session(
        name="s", samples=samples,
        events={"hrv": Events(peaks, labels)},
        epochs={"whole": Epoch("whole", 0.0, 30.0, True)},
    )


bp_act = w._view_actions[mw._DOCK_BP]
bp_dock = w._docks[mw._DOCK_BP]

# No BP channel -> BP dock closed + its View entry greyed out.
w._apply_dock_availability(make_session(with_bp=False))
assert not bp_act.isEnabled(), "BP view action should be disabled without BP"
assert bp_dock.isClosed(), "BP dock should be closed without BP"

# BP present -> the View entry re-enables.
w._apply_dock_availability(make_session(with_bp=True))
assert bp_act.isEnabled(), "BP view action should re-enable when BP is present"

print("MAINWINDOW_OK")
"""


def test_dock_availability_offscreen():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    with tempfile.TemporaryDirectory() as tmp:
        # Isolate Path.home() so _restore's ~/workspace.json lands in tmp, not
        # the real home dir (Windows resolves ~ via USERPROFILE).
        env["HOME"] = tmp
        env["USERPROFILE"] = tmp
        proc = subprocess.run(
            [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
        )
    assert proc.returncode == 0 and "MAINWINDOW_OK" in proc.stdout, (
        f"dock availability test failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
