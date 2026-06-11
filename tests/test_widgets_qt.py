# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Offscreen smoke tests for the BP / Poincaré / Results docks.

Subprocess-isolated (Qt must not enter the shared pytest process).  Each
dock is loaded with a synthetic session, rendered, and — where it derives
from the R-peaks — checked to refresh after an edit.
"""
from __future__ import annotations

import os
import subprocess
import sys

_DRIVER = r"""
import time
import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from spectHR.session import Epoch, Events, Samples, Session
from spectUI.parameters import Parameters
from spectUI.widgets import (
    BPSeriesWidget, PoincareWidget, PSDPlotWidget, ResultsTableWidget,
)

app = QApplication.instance() or QApplication([])


def pump(predicate, timeout_s=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def make_session():
    fs = 100.0
    t = np.arange(0.0, 40.0, 1.0 / fs)
    bp = 90.0 + 30.0 * (np.sin(2 * np.pi * 1.1 * t) > 0.6)   # crude pulsatile BP
    rng = np.random.default_rng(0)
    peaks = np.cumsum(0.8 + rng.normal(0.0, 0.03, 50))
    labels = np.full(peaks.shape, "N", dtype=object)
    return Session(
        name="s",
        samples={"ecg": Samples(t, np.sin(t), "ecg"), "bp": Samples(t, bp, "bp")},
        events={"hrv": Events(peaks, labels)},
        epochs={"whole": Epoch("whole", 0.0, 40.0, True)},
    )


session = make_session()

# --- BP dock: waveform renders, time extent set ----------------------------
bp = BPSeriesWidget()
bp.show()
bp.set_session(session, None)
assert bp._model.bp is not None
assert bp._model.extent is not None
assert len(bp.ax_main.lines) >= 1

# --- Poincaré dock: cloud + ellipse render; refresh after edit -------------
poin = PoincareWidget()
poin.show()
poin.set_session(session, None)
ax = poin.fig.axes[0]
n_pts0 = sum(c.get_offsets().shape[0] for c in ax.collections)
assert n_pts0 > 10                                      # scatter drawn

# Add a beat to hrv, then refresh: the cloud must change.
from spectUI.widgets.prep.rtop_controller import RTopController
RTopController(session).add_no_classify(3.33)
poin.refresh()
ax2 = poin.fig.axes[0]
n_pts1 = sum(c.get_offsets().shape[0] for c in ax2.collections)
assert n_pts1 == n_pts0 + 1                             # one more pair

# --- Results table: rows = epochs, columns include time-domain metrics -----
res = ResultsTableWidget()
res.show()
res.set_session(session, None)
assert res.table.rowCount() == 1                        # one active epoch
assert res.table.columnCount() > 1                      # epoch + metrics
headers = [res.table.horizontalHeaderItem(c).text()
           for c in range(res.table.columnCount())]
assert headers[0] == "epoch"

# --- PSD grid: per-epoch spectra computed off-thread, then gridded ---------
def make_psd_session():
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

psd = PSDPlotWidget()
psd.show()
psd.set_session(make_psd_session(), Parameters.default())
assert pump(lambda: psd._content is not None), "PSD grid did not build"
# Two active epochs -> two tiles, each with a spectrum line.
tiles = psd._content.findChildren(type(psd._content))  # inner tile QWidgets
canvases = psd._content.findChildren(__import__("matplotlib.backends.backend_qtagg",
            fromlist=["FigureCanvasQTAgg"]).FigureCanvasQTAgg)
assert len(canvases) == 2, f"expected 2 PSD tiles, got {len(canvases)}"
drawn = sum(len(c.figure.axes[0].lines) for c in canvases if c.figure.axes)
assert drawn >= 2, "PSD spectra not drawn"

print("WIDGETS_OK")
"""


def test_widgets_offscreen():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0 and "WIDGETS_OK" in proc.stdout, (
        f"widget smoke test failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
