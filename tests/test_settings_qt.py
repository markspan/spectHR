# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Settings live in one workspace file (``~/workspace.json``) that holds the
analysis parameters *and* the working directories.  This test exercises the
``Parameters`` directory accessors and the save/load round-trip.

Subprocess-isolated because importing ``spectUI`` pulls in Qt, which must not
enter the shared pytest process.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_DRIVER = r"""
import json
import tempfile
from pathlib import Path

from spectUI.parameters import Parameters

# Directories are part of the workspace defaults now.
p = Parameters.default()
d = p.to_dict()
assert "Directories" in d, "defaults carry no Directories section"
assert isinstance(p.data_dir, Path)
assert p.directories.keys() >= {"DataDirectory", "CacheDirectory", "OutputDirectory"}

# The setter updates in place (no auto-save).
tmp = Path(tempfile.mkdtemp())
p.directories = {"DataDirectory": str(tmp / "data"),
                 "CacheDirectory": str(tmp / "cache"),
                 "OutputDirectory": str(tmp / "out")}
assert p.data_dir == tmp / "data"
assert p.cache_dir == tmp / "cache"
assert p.export_dir("PSD") == tmp / "out" / "PSD"
assert (tmp / "out" / "PSD").is_dir()      # export_dir creates it

# Edit an analysis setting, save the whole workspace, reload: both the
# directories and the parameter survive in one file.
p.update("FrequencyAnalysis", {"method": "carspan_strict"})
wf = tmp / "workspace.json"
p.save(wf)
assert wf.exists()
raw = json.loads(wf.read_text(encoding="utf-8"))
assert raw["Directories"]["DataDirectory"] == str(tmp / "data")

q = Parameters.load(wf)
assert q.data_dir == tmp / "data"
assert q.psd_method.algorithm == "carspan_strict"

# AppSettings is now window-state only — no directory / workspace-path API.
from spectUI.settings import AppSettings
assert not hasattr(AppSettings, "directories")
assert not hasattr(AppSettings, "app_parameters_path")

print("SETTINGS_OK")
"""


def test_workspace_settings_roundtrip():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    with tempfile.TemporaryDirectory() as tmp:
        env["HOME"] = tmp
        proc = subprocess.run(
            [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
        )
    assert proc.returncode == 0 and "SETTINGS_OK" in proc.stdout, (
        f"settings round-trip failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
