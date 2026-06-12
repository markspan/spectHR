# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Offscreen test for parameter persistence (auto-save + restore at startup).

Subprocess-isolated (Qt must not enter the shared pytest process).  The app
auto-saves the live analysis parameters to an app-managed file on every
change, so edits made through the Edit-workspace dialog survive a restart even
when the analyst never explicitly saved a named workspace.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_DRIVER = r"""
import json
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QStandardPaths, QSettings

# Isolate Qt config to a throwaway dir so the test never touches the real
# user settings (AppConfigLocation + the IniFormat backing store).
import tempfile
cfg = tempfile.mkdtemp()
QCoreApplication.setApplicationName("spectHR_test")
QCoreApplication.setOrganizationName("spectHR_test")
QStandardPaths.setTestModeEnabled(True)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cfg)

from spectUI.settings import AppSettings
from spectUI.parameters import Parameters

s = AppSettings()
app_path = s.app_parameters_path
assert app_path.name == "parameters.json"
assert app_path.parent.exists(), "config dir was not created"

# Edit a parameter and persist it the way the MainWindow does on change.
params = Parameters.default()
params.update("FrequencyAnalysis", {"method": "carspan_strict"})
params.update("TransferAnalysis", {"min_coherence": 0.73})
params.save(app_path)
assert app_path.exists(), "parameters file not written"

# Simulate a fresh startup: a new AppSettings sees the same path, and the
# parameters reload with the edits intact.
s2 = AppSettings()
assert s2.app_parameters_path == app_path
restored = Parameters.load(s2.app_parameters_path)
assert restored.psd_method.algorithm == "carspan_strict", restored.psd_method.algorithm
assert abs(restored.transfer_settings["min_coherence"] - 0.73) < 1e-9

# workspace_path round-trips through QSettings (named-file pointer).
wp = Path(cfg) / "study.json"
wp.write_text(json.dumps(params.to_dict()), encoding="utf-8")
s2.workspace_path = wp
assert s2.workspace_path == wp           # exists -> returned
s2.workspace_path = None
assert s2.workspace_path is None

print("SETTINGS_OK")
"""


def test_parameter_persistence_offscreen():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    with tempfile.TemporaryDirectory() as tmp:
        env["HOME"] = tmp
        proc = subprocess.run(
            [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
        )
    assert proc.returncode == 0 and "SETTINGS_OK" in proc.stdout, (
        f"settings persistence failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
