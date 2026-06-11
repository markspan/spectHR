# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Offscreen tests for the data-update coordinator and the HR dock.

Runs in a fresh subprocess (Qt must not enter the shared pytest process,
per ``test_headless_imports``).  Covers the coordinator's dependency
fan-out, lazy refresh of hidden docks, window sync, and an end-to-end
check that editing an R-peak in the prep dock refreshes the HR dock.
"""
from __future__ import annotations

import os
import subprocess
import sys

_DRIVER = r"""
import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QWidget

from spectHR.session import Epoch, Events, Samples, Session
from spectUI.coordinator import DataChange, DataCoordinator
from spectUI.widgets import HRSeriesWidget, PrepPlotWidget

app = QApplication.instance() or QApplication([])


class FakeDock(QWidget):
    viewChanged = Signal()

    def __init__(self):
        super().__init__()
        self.refreshed = 0
        self._win = (0.0, 10.0)

    def refresh(self):
        self.refreshed += 1

    def current_window(self):
        return self._win

    def apply_window(self, a, b):
        self._win = (a, b)


# --- dependency fan-out (visible) ------------------------------------------
coord = DataCoordinator()
a, b, c = FakeDock(), FakeDock(), FakeDock()
for w in (a, b, c):
    w.show()
coord.register(a, DataChange.HRV)
coord.register(b, DataChange.HRV | DataChange.BP)
coord.register(c, DataChange.BP)
coord.notify(DataChange.HRV, source=a)
assert a.refreshed == 0, "source must be skipped"
assert b.refreshed == 1, "HRV-dependent dock must refresh"
assert c.refreshed == 0, "BP-only dock must not refresh on HRV"

# --- lazy refresh of a hidden dependant ------------------------------------
d = FakeDock()
coord.register(d, DataChange.HRV)
d.hide()
coord.notify(DataChange.HRV)
assert d.refreshed == 0, "hidden dock must defer"
coord.widget_shown(d)
assert d.refreshed == 1, "dirty dock refreshes when shown"
coord.widget_shown(d)
assert d.refreshed == 1, "clean dock does not refresh again"

# --- window sync across timeline docks -------------------------------------
ta, tb = FakeDock(), FakeDock()
ta.show(); tb.show()
coord.register_timeline(ta)
coord.register_timeline(tb)
ta._win = (5.0, 7.0)
ta.viewChanged.emit()
assert tb._win == (5.0, 7.0), "sibling window must follow"

# A hidden timeline dock adopts the shared window when it is shown.
tc = FakeDock()
coord.register_timeline(tc)
tc.hide()
tc._win = (0.0, 99.0)
coord.widget_shown(tc)
assert tc._win == (5.0, 7.0), "shown dock must adopt the coupled window"

# --- end-to-end: edit R-peak in prep -> HR dock refreshes ------------------
def make_session():
    fs = 130.0
    t = np.arange(0.0, 30.0, 1.0 / fs)
    ecg = np.sin(2.0 * np.pi * 1.2 * t)
    peaks = np.arange(0.5, 30.0, 0.83)
    labels = np.full(peaks.shape, "N", dtype=object)
    return Session(
        name="s",
        samples={"ecg": Samples(t, ecg, "ecg")},
        events={"hrv": Events(peaks, labels)},
        epochs={"whole": Epoch("whole", 0.0, 30.0, True)},
    )

prep = PrepPlotWidget()
hr = HRSeriesWidget()
prep.show(); hr.show()
session = make_session()
prep.set_session(session, None)
hr.set_session(session, None)

coord2 = DataCoordinator()
coord2.register(prep, DataChange.HRV | DataChange.EPOCHS)
coord2.register(hr, DataChange.HRV | DataChange.EPOCHS)
# Structural edits notify immediately via dataEdited (no manual notify, no
# waiting for the async re-classification).
prep.dataEdited.connect(lambda: coord2.notify(DataChange.HRV, source=prep))

n_before = hr._model.times.size
prep._apply_add(5.4)                       # commits a new peak into session hrv
assert hr._model.times.size == n_before + 1, "HR dock must reflect the edit at once"

print("COORD_OK")
"""


def test_coordinator_offscreen():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0 and "COORD_OK" in proc.stdout, (
        f"coordinator checks failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
