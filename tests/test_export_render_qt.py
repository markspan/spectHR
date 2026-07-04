# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Before exporting plots, lazy / async docks are computed and rendered.

Subprocess-isolated (Qt must not enter the shared pytest process).  A grid
dock that was never opened has no figure and never computed; the export path
calls ``DataCoordinator.ensure_ready`` and waits for the background tiles, so
its canvases exist and are drawn before the figures are saved.
"""
from __future__ import annotations

import os
import subprocess
import sys

_DRIVER = r"""
import time
import numpy as np
from PySide6.QtCore import QCoreApplication, QEventLoop
from PySide6.QtWidgets import QApplication
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas

from spectHR.session import Epoch, Events, Session
from spectUI.coordinator import DataChange, DataCoordinator
from spectUI.parameters import Parameters
from spectUI.widgets import PSDPlotWidget

app = QApplication.instance() or QApplication([])


def make_session():
    rng = np.random.default_rng(1)
    ibi = 0.8 + 0.05 * np.sin(2 * np.pi * 0.1 * np.arange(260)) + rng.normal(0, 0.01, 260)
    peaks = np.cumsum(np.clip(ibi, 0.4, 1.5))
    labels = np.full(peaks.shape, "N", dtype=object)
    end = float(peaks[-1])
    return Session(
        name="psd",
        events={"hrv": Events(peaks, labels)},
        epochs={"a": Epoch("a", 0.0, end / 2), "b": Epoch("b", end / 2, end)},
    )


sess = make_session()
params = Parameters.default()

# A hidden grid dock: never shown, so the coordinator keeps the session pending
# and the dock never computes -> no tiles, no canvases.
psd = PSDPlotWidget()
coord = DataCoordinator()
coord.register(psd, DataChange.HRV | DataChange.EPOCHS | DataChange.PARAMS)
coord.set_session(sess, params)

assert not psd.findChildren(Canvas), "hidden dock must not have computed yet"
assert psd._last_results is None

# The export path: bring pending docks current, then wait for the async tiles.
coord.ensure_ready()
t0 = time.time()
while psd.is_busy() and time.time() - t0 < 20.0:
    QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
    time.sleep(0.02)
QCoreApplication.processEvents(QEventLoop.AllEvents, 50)

assert not psd.is_busy(), "grid dock still busy after the wait"
canvases = psd.findChildren(Canvas)
assert len(canvases) == 2, f"expected 2 tiles after ensure_ready, got {len(canvases)}"
drawn = sum(len(c.figure.axes[0].lines) for c in canvases if c.figure.axes)
assert drawn >= 2, "spectra were not drawn"

print("EXPORT_RENDER_OK")
"""


def test_export_renders_lazy_docks():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0 and "EXPORT_RENDER_OK" in proc.stdout, (
        f"export-render test failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
