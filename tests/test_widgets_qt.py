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
# Epoch checkboxes form a vertical, scrollable column (V2 layout).
from PySide6.QtWidgets import QScrollArea, QVBoxLayout
assert isinstance(poin._cb_layout, QVBoxLayout)
assert len(poin.findChildren(QScrollArea)) >= 1

# Add a beat to hrv, then refresh: the cloud must change.
from spectUI.widgets.prep.rtop_controller import RTopController
RTopController(session).add_no_classify(3.33)
poin.refresh()
ax2 = poin.fig.axes[0]
n_pts1 = sum(c.get_offsets().shape[0] for c in ax2.collections)
assert n_pts1 == n_pts0 + 1                             # one more pair

# Square axis starting at the origin.
assert ax2.get_xlim()[0] == 0.0 and ax2.get_ylim()[0] == 0.0
assert ax2.get_aspect() in (1.0, "equal")

# Per-epoch checkbox ("epoch scheduling") toggles active + emits epochsChanged.
toggled = {"n": 0}
poin.epochsChanged.connect(lambda: toggled.__setitem__("n", toggled["n"] + 1))
cb = next(iter(poin._checkboxes.values()))
cb.setChecked(False)
assert toggled["n"] >= 1
assert session.epochs["whole"].active is False
cb.setChecked(True)  # restore

# Double-clicking a point emits annotationActivated with that beat's time.
jumped = {"t": None}
poin.annotationActivated.connect(lambda t: jumped.__setitem__("t", t))
x, y, tt, _c = poin._clouds["whole"]
px, py = poin.ax.transData.transform((x[3], y[3]))
from matplotlib.backend_bases import MouseEvent
poin._on_press(MouseEvent("button_press_event", poin.canvas, px, py,
                          button=1, dblclick=True))
assert jumped["t"] is not None and abs(jumped["t"] - tt[3]) < 1e-6

# Annotations are delegated to mplcursors (draggable + right-click removal):
# the cursor is wired over the scatter clouds and our add-callback formats the
# point's epoch / IBI pair / time.
import mplcursors
assert isinstance(poin._cursor, mplcursors.Cursor)
txt = poin._annotation_text("whole", 3)
assert "whole" in txt and "IBI" in txt and f"{tt[3]:.1f}" in txt

# --- Epoch editor: bars render; edge-drag resizes; body-click toggles -------
from spectUI.widgets import EpochEditorWidget
ed = EpochEditorWidget()
ed.show()
ed.set_session(session, None)
ed.canvas.draw()
assert len(ed.ax.patches) >= 1                          # one bar per epoch
assert [t.get_text() for t in ed.ax.get_yticklabels()] == ["whole"]  # names on y-axis
ed_changes = {"n": 0}
ed.epochsChanged.connect(lambda: ed_changes.__setitem__("n", ed_changes["n"] + 1))

ep = session.epochs["whole"]
end0 = float(ep.end)
ex, ey = ed.ax.transData.transform((end0, 0))
ed._on_press(MouseEvent("button_press_event", ed.canvas, ex, ey, button=1))
assert ed._drag == ("whole", "end")                     # grabbed the end edge
nx, ny = ed.ax.transData.transform((end0 - 10.0, 0))
ed._on_motion(MouseEvent("motion_notify_event", ed.canvas, nx, ny, button=1))
ed._on_release(MouseEvent("button_release_event", ed.canvas, nx, ny, button=1))
assert abs(ep.end - (end0 - 10.0)) < 2.0 and ed_changes["n"] >= 1

bx, by = ed.ax.transData.transform((5.0, 0))            # body click → toggle active
ed._on_press(MouseEvent("button_press_event", ed.canvas, bx, by, button=1))
ed._on_release(MouseEvent("button_release_event", ed.canvas, bx, by, button=1))
assert session.epochs["whole"].active is False and ed_changes["n"] >= 2
session.epochs["whole"].active = True  # restore for the results section

# Right-click → "Add epoch" adds a full-recording-span epoch (tested via the
# dialog-free add_epoch entry point).
n_before = len(session.epochs)
ed.add_epoch("baseline")
assert "baseline" in session.epochs and len(session.epochs) == n_before + 1
new_ep = session.epochs["baseline"]
ecg_ch = session.samples["ecg"]                                  # the recording span
assert abs(new_ep.start - float(ecg_ch.times[0])) < 1e-6
assert abs(new_ep.end - float(ecg_ch.times[-1])) < 1e-6
assert new_ep.active and ed_changes["n"] >= 3
session.epochs.pop("baseline")  # restore for the results section (1 active epoch)

# --- Results table: rows = epochs, columns include time-domain metrics -----
res = ResultsTableWidget()
res.show()
res.set_session(session, None)
assert pump(lambda: res.table.rowCount() == 1)          # async: one active epoch
assert res.table.columnCount() > 1                      # epoch + metrics
assert res._export_btn is not None                      # CSV/H5 export button
assert hasattr(res, "plotsExportRequested")             # → host plot-export dialog
headers = [res.table.horizontalHeaderItem(c).text()
           for c in range(res.table.columnCount())]
assert headers[0] == "epoch"
# Metric column headers carry their calculation's docstring as a tooltip.
tips = {res.table.horizontalHeaderItem(c).text():
        res.table.horizontalHeaderItem(c).toolTip()
        for c in range(1, res.table.columnCount())}
assert "rmssd" in tips and tips["rmssd"].strip(), "no docstring tooltip on header"

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

# Tiles are laid out at most 2 wide and given a fixed (viewport-aspect)
# height so the page scrolls vertically instead of cramming every epoch.
assert psd._columns == 2                                # 2 epochs -> 2 columns
assert all(t.height() > 0 for t in psd._subplots)
ax0 = canvases[0].figure.axes[0]
assert not ax0.spines["top"].get_visible()
assert not ax0.spines["right"].get_visible()
assert any("carspan" in t.get_text().lower() for t in ax0.texts), "no method label"
# Y-axis is a spectral density (keeps /Hz); band-power legend is integrated.
assert ax0.get_ylabel().endswith("/Hz"), ax0.get_ylabel()
leg = ax0.get_legend()
band_lbls = [t.get_text() for t in leg.get_texts()] if leg else []
assert any("/Hz" not in l for l in band_lbls if ":" in l), band_lbls

# Equal y-axis (default) links every tile's y-max to the largest.
assert psd._equal_y_cb.isVisibleTo(psd)                 # shown for >1 epoch
tops = [c.figure.axes[0].get_ylim()[1] for c in canvases]
assert max(tops) - min(tops) < 1e-9, "tiles not linked to a common y-max"
# Up arrow shrinks the y-max (zoom in); Down grows it back past the start.
top0 = canvases[0].figure.axes[0].get_ylim()[1]
psd._zoom_in()
assert canvases[0].figure.axes[0].get_ylim()[1] < top0
psd._zoom_out(); psd._zoom_out()
assert canvases[0].figure.axes[0].get_ylim()[1] > top0

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
