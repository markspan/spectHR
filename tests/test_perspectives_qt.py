# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Saved dock perspectives (named layouts) must survive across sessions: closing
the app writes them to QSettings, the next launch reads them back.  This test
round-trips a perspective through :class:`~spectUI.settings.AppSettings`.

Subprocess-isolated (Qt must not enter the shared pytest process); QSettings is
redirected to a temp directory so the test never touches the real user state.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_DRIVER = r"""
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMainWindow

from PySide6QtAds import CDockManager, CDockWidget, DockWidgetArea
from spectUI.settings import AppSettings

app = QApplication.instance() or QApplication([])

# Isolate to an explicit .ini file (the two-arg QSettings would hit the real
# per-user store — the registry on Windows — regardless of setDefaultFormat).
ini = str(Path(tempfile.mkdtemp()) / "app.ini")


def app_settings():
    return AppSettings(QSettings(ini, QSettings.IniFormat))


def make_manager():
    mw = QMainWindow()
    dm = CDockManager(mw)
    dw = CDockWidget("A")
    dm.addDockWidget(DockWidgetArea.CenterDockWidgetArea, dw)
    return mw, dm


# --- Nothing saved yet: load is a no-op (must not wipe captured built-ins) ---
_mw0, dm0 = make_manager()
assert app_settings().load_perspectives(dm0) is False

# --- Save a user perspective, then load it into a brand-new manager ----------
mw1, dm1 = make_manager()
dm1.addPerspective("MyView")
assert "MyView" in dm1.perspectiveNames()
app_settings().save_perspectives(dm1)

mw2, dm2 = make_manager()
assert "MyView" not in dm2.perspectiveNames()          # a fresh manager is empty
assert app_settings().load_perspectives(dm2) is True
assert "MyView" in dm2.perspectiveNames(), dm2.perspectiveNames()

print("PERSPECTIVES_OK")
"""


def test_perspectives_persist():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    with tempfile.TemporaryDirectory() as tmp:
        env["HOME"] = tmp
        env["USERPROFILE"] = tmp
        proc = subprocess.run(
            [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
        )
    assert proc.returncode == 0 and "PERSPECTIVES_OK" in proc.stdout, (
        f"perspectives persistence failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
