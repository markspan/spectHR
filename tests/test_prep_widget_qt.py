# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Offscreen smoke test for :class:`PrepPlotWidget`.

This drives the real Qt + matplotlib widget, but does so in a **fresh
subprocess** with ``QT_QPA_PLATFORM=offscreen``.  The rest of the test
suite is deliberately Qt-free in-process — importing PySide6 into the
shared pytest process triggers a Qt init-order segfault (the same reason
``test_headless_imports`` shells out).  Running the widget in its own
interpreter keeps that contract while still exercising the genuine widget:
load a synthetic session, render it, edit an R-peak, and navigate.
"""
from __future__ import annotations

import os
import subprocess
import sys

# The body of the subprocess: build a session, drive the widget, assert.
_DRIVER = r"""
import numpy as np
from PySide6.QtWidgets import QApplication

from spectHR.session import Epoch, Events, Intervals, Samples, Session
from spectUI.widgets import PrepPlotWidget

app = QApplication.instance() or QApplication([])

def make_session():
    fs = 130.0
    t = np.arange(0.0, 60.0, 1.0 / fs)
    ecg = np.sin(2.0 * np.pi * 1.2 * t)
    tr = np.arange(0.0, 60.0, 1.0 / 25.0)
    resp = np.sin(2.0 * np.pi * 0.25 * tr)
    peaks = np.arange(0.5, 60.0, 0.83)
    labels = np.full(peaks.shape, "N", dtype=object)
    starts = np.arange(0.0, 60.0, 4.0)
    return Session(
        name="synthetic",
        samples={"ecg": Samples(t, ecg, "ecg"), "resp": Samples(tr, resp, "resp")},
        events={"hrv": Events(peaks, labels)},
        intervals={"breath": Intervals(starts, starts + 2.0,
                                        np.array(["INH"] * starts.size, dtype=object))},
        epochs={"whole": Epoch("whole", 0.0, 60.0, True)},
    )

# 1. Load + render.  Everything about the load lives in one PrepModel.
w = PrepPlotWidget()
session = make_session()
w.set_session(session, config=None)
assert w.isVisible()
m = w._model
assert m is not None and m.rtop_ctrl is not None and m.window is not None

# 1a. Autoscale leaves headroom above the tallest visible sample (no clip).
seg = m.ecg_display.window(m.window.x_min, m.window.x_max)
y0, y1 = w.ax_ecg.get_ylim()
assert y1 > float(seg.values.max())

# 1b. A release that is not a drag must leave the R-peak markers intact
#     (the bug that broke drag/remove cleared them on every release).
n_lines = len(w._marker_lines)
assert n_lines > 0
m.window.drag_mode = None
w._on_release(None)
assert len(w._marker_lines) == n_lines

# 2. Navigation goes through the navigator and narrows the window.
full = m.window.width()
w.zoom_in()
assert m.window.width() < full

# 3. Editing commits a fresh Events into the session (call by reference).
#    The single gesture dispatcher commits via _apply_move.
n_before = session.events["hrv"].times.size
moved_from = float(session.events["hrv"].times[5])
w._apply_move(moved_from, 25.123)
assert session.events["hrv"].times.size == n_before          # move preserves count
assert 25.123 in set(session.events["hrv"].times.tolist())   # peak landed

# 4. Reloading swaps the canvas cleanly.
first_canvas = w.canvas
w.set_session(make_session(), config=None)
assert w.canvas is not first_canvas

# 5. XDF-style session: device-suffixed channel keys and no hrv channel.
#    The load worker (apply_beat_detection) resolves "ecg-[...]" by prefix,
#    prefilters and detects beats; the model then resolves "ecg-[...]" /
#    "RSP-[...]" for display so the ECG renders and R-peaks appear.
from spectUI.preProcessFile import apply_beat_detection

fs = 130.0
t = np.arange(0.0, 30.0, 1.0 / fs)
ecg = np.sin(2.0 * np.pi * 1.2 * t)
tr = np.arange(0.0, 30.0, 1.0 / 25.0)
xdf_like = Session(
    name="xdf-like",
    samples={
        "ecg-[ABCD1234]": Samples(t, ecg, "ecg-[ABCD1234]"),
        "RSP-[ABCD1234]": Samples(tr, np.sin(2.0 * np.pi * 0.25 * tr), "RSP-[ABCD1234]"),
    },
)
assert xdf_like.ecg is None and xdf_like.resp is None  # canonical lookup misses
xdf_like = apply_beat_detection(xdf_like, None)        # worker step
assert xdf_like.events.get("hrv") is not None          # beats were detected
w.set_session(xdf_like, config=None)
m = w._model
assert m.ecg is not None and m.ecg.name == "ecg-[ABCD1234]"
assert m.resp is not None and m.resp.name == "RSP-[ABCD1234]"
assert m.rtop_ctrl is not None
# Classification thresholds come from the workspace (defaults here).
assert m.cardio.window_length == 20 and m.cardio.n_std == 3.0
assert m.rtop_ctrl._classify_params == {
    "window_length": 20, "n_std": 3.0, "max_ibi_sec": 2.5}
assert m.extent is not None                            # so goto/end work
assert len(w.ax_ecg.lines) >= 1                        # ECG actually drawn
assert len(w.ax_overview.lines) >= 1                   # overview ECG drawn
# Default: the displayed trace is the raw channel (no extra filtering).
assert m.ecg_display is m.ecg and not m.cardio.display_filtered

# 6. display_filtered=True shows the prefiltered trace instead of the raw one.
cfg = {"CardioParameters": {"EcgPreprocessing": {
    "filter_type": "highpass", "filter_cutoff": 0.5, "display_filtered": True}}}
w.set_session(make_session(), config=cfg)
m = w._model
assert m.cardio.display_filtered is True
assert m.ecg_display is not m.ecg                      # a filtered copy is shown
import numpy as _np
assert _np.array_equal(m.ecg_display.times, m.ecg.times)  # same time base
assert not _np.array_equal(m.ecg_display.values, m.ecg.values)  # values differ

# 7. A session with neither ECG nor hrv disables editing without crashing.
empty = Session(name="empty")
w.set_session(empty, config=None)
m = w._model
assert m.rtop_ctrl is None and m.ecg is None and m.ecg_display is None
w.next()        # safe no-op
w.go_to_end()   # safe no-op (no extent)

# 8. Static overview: a redraw does not add a second overview trace.
w.set_session(make_session(), config=None)
ov_lines = len(w.ax_overview.lines)
w.zoom_in()
w.redraw()
assert len(w.ax_overview.lines) == ov_lines            # trace drawn once, not per redraw

print("PREP_WIDGET_OK")
"""


def test_prep_widget_offscreen_smoke():
    """Drive the real widget in an offscreen subprocess; assert it succeeds."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0 and "PREP_WIDGET_OK" in proc.stdout, (
        f"prep widget smoke test failed\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
