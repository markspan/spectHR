# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Offscreen smoke test for the per-epoch grid docks (Profiles / Spectrogram /
Transfer / TransferProfile).  Subprocess-isolated; each dock computes its
epochs off-thread and must build one tile per active epoch.
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
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from spectHR.session import Epoch, Events, Samples, Session
from spectUI.parameters import Parameters
from spectUI.widgets import (
    ProfilePlotWidget, Spectrogram3DPlotWidget, SpectrogramPlotWidget,
    TransferPlotWidget, TransferProfilePlotWidget,
)

app = QApplication.instance() or QApplication([])


def pump(pred, timeout_s=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        QCoreApplication.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return False


def make_session():
    rng = np.random.default_rng(1)
    ibi = 0.8 + 0.05 * np.sin(2 * np.pi * 0.1 * np.arange(320)) + rng.normal(0, 0.01, 320)
    peaks = np.cumsum(np.clip(ibi, 0.4, 1.5))
    labels = np.full(peaks.shape, "N", dtype=object)
    end = float(peaks[-1])
    tr = np.arange(0.0, end, 1.0 / 10.0)
    resp = np.sin(2 * np.pi * 0.25 * tr)
    return Session(
        name="g",
        samples={"resp": Samples(tr, resp, "resp")},
        events={"hrv": Events(peaks, labels)},
        epochs={"a": Epoch("a", 0.0, end / 2), "b": Epoch("b", end / 2, end)},
    )


params = Parameters.default()
params.update("TransferAnalysis", {"input_signal": "rsp"})  # use respiration input
session = make_session()


def check(widget_cls, name):
    w = widget_cls()
    w.show()
    w.set_session(session, params)
    assert pump(lambda: w._content is not None), f"{name}: grid did not build"
    canvases = w._content.findChildren(FigureCanvas)
    assert len(canvases) == 2, f"{name}: expected 2 tiles, got {len(canvases)}"
    # Each tile has at least one axis drawn (line, mesh, or placeholder text).
    for c in canvases:
        assert len(c.figure.axes) >= 1, f"{name}: empty tile"
    print(name, "OK")


check(ProfilePlotWidget, "profiles")
check(SpectrogramPlotWidget, "spectrogram")
check(Spectrogram3DPlotWidget, "spectrogram3d")
check(TransferPlotWidget, "transfer")
check(TransferProfilePlotWidget, "transferprofile")

# The 3-D spectrogram tile is an Axes3D surface, one full-width column.
s3 = Spectrogram3DPlotWidget(); s3.show(); s3.set_session(session, params)
assert pump(lambda: s3._content is not None)
cv3 = s3._content.findChildren(FigureCanvas)[0]
assert cv3.figure.axes[0].name == "3d", "spectrogram3d tile is not a 3-D axis"
assert s3._columns == 1, "spectrogram3d should use one wide column"
assert not s3.Y_ZOOM and not s3._equal_y_cb.isVisibleTo(s3)  # no y-link on a 3-D dock

# A Transfer tile is a Bode triple (modulus / phase / coherence).
tw = TransferPlotWidget(); tw.show(); tw.set_session(session, params)
assert pump(lambda: tw._content is not None)
cv = tw._content.findChildren(FigureCanvas)[0]
ax_mod, ax_phase, ax_coh = cv.figure.axes
assert len([ax_mod, ax_phase, ax_coh]) == 3, "Bode tile needs 3 panels"
# Phase y-axis reads in pi.
phase_labels = [t.get_text() for t in ax_phase.get_yticklabels()]
assert any("\\pi" in lbl for lbl in phase_labels), phase_labels
# Phase + coherence panels carry vertical band shading (axvspan -> patches).
assert len(ax_phase.patches) >= 1 and len(ax_coh.patches) >= 1, "no band shading"

# Editing the band table re-resolves settings on refresh (the path the
# coordinator drives when the workspace changes).
prof = ProfilePlotWidget(); prof.show(); prof.set_session(session, params)
assert pump(lambda: prof._content is not None)
params.update("FrequencyAnalysis",
              {"bands": {"LF": {"low": 0.07, "high": 0.14, "color": "green", "alpha": 0.2}}})
prof.refresh()
assert pump(lambda: prof._content is not None)
assert len(prof._bands) == 1, "profile did not re-read the edited band table"

# Band checkboxes select which bands plot; unticking one re-renders fewer lines.
prof2 = ProfilePlotWidget(); prof2.show(); prof2.set_session(session, Parameters.default())
assert pump(lambda: prof2._content is not None)
assert len(prof2._band_checks) >= 2, "no band checkboxes built"
cv_p = prof2._content.findChildren(FigureCanvas)[0]
n_lines0 = len(cv_p.figure.axes[0].lines)
some_band = next(iter(prof2._band_checks))
prof2._band_checks[some_band].setChecked(False)        # untick one band
assert pump(lambda: prof2._content is not None)
cv_p2 = prof2._content.findChildren(FigureCanvas)[0]
assert len(cv_p2.figure.axes[0].lines) < n_lines0, "unticking a band did not drop a line"

print("GRID_OK")
"""


def test_grid_widgets_offscreen():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0 and "GRID_OK" in proc.stdout, (
        f"grid widgets failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
