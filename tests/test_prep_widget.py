# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for the pre-processing widget's headless helpers.

The :mod:`spectUI.widgets.prep` package keeps its moving parts, window
state, navigation arithmetic, and R-peak editing, as small Qt-free
objects so they can be reasoned about in isolation.  Importing them still
pulls in the ``spectUI`` GUI package (and therefore the Qt + matplotlib
stack), which must never enter the shared pytest process, doing so
triggers the Qt init-order segfault that ``test_headless_imports`` exists
to prevent.  So, like that module, these checks run in a **fresh
subprocess**.  The driver below uses plain ``assert`` statements; on
failure its traceback is surfaced through the captured stderr.
"""
from __future__ import annotations

import os
import subprocess
import sys

_DRIVER = r"""
import numpy as np

from spectHR.session import Events, Session
from spectUI.widgets.prep.rtop_controller import RTopController
from spectUI.widgets.timeline.navigation import TimelineNavigator
from spectUI.widgets.timeline.state import WindowState, YAxisState


def session_with_peaks(times):
    times = np.asarray(times, dtype=float)
    labels = np.full(times.shape, "N", dtype=object)
    return Session(name="t", events={"hrv": Events(times, labels)})


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


# --- WindowState -----------------------------------------------------------
w = WindowState(x_min=10.0, x_max=30.0)
assert w.width() == 20.0 and w.center() == 20.0

w.begin_drag("center")
assert w.drag_mode == "center" and w.initial_xmin == 10.0 and w.initial_xmax == 30.0
assert w.end_drag() is True
assert w.drag_mode is None and w.initial_xmin is None
assert w.end_drag() is False

y = YAxisState(auto=False, ymin=1.0, ymax=2.0)
y.reset()
assert y.auto and y.ymin is None and y.ymax is None


# --- TimelineNavigator -----------------------------------------------------
def nav(x0, x1, extent=(0.0, 100.0)):
    st = WindowState(x_min=x0, x_max=x1)
    return st, TimelineNavigator(st, lambda: extent)

st, n = nav(40.0, 60.0)
assert n.zoom_in() is True
assert approx(st.center(), 50.0) and approx(st.width(), 20.0 * 2 / 3)

st, n = nav(40.0, 60.0)
assert n.zoom_out() is True
assert approx(st.center(), 50.0) and approx(st.width(), 30.0)

st, n = nav(0.0, 20.0)
assert n.pan_left() is False and (st.x_min, st.x_max) == (0.0, 20.0)
assert n.pan_right() is True and approx(st.width(), 20.0) and approx(st.x_min, 20.0)

st, n = nav(0.0, 20.0)
assert n.go_to_end() is True and approx(st.x_min, 80.0) and approx(st.x_max, 100.0)
assert n.go_to_start() is True and approx(st.x_min, 0.0) and approx(st.x_max, 20.0)

st, n = nav(10.0, 30.0)
assert n.constrain(-50.0, 250.0) == (0.0, 100.0)

st = WindowState(x_min=0.0, x_max=10.0)
n = TimelineNavigator(st, lambda: None)
assert n.go_to_start() is False and n.go_to_end() is False


# --- RTopController --------------------------------------------------------
try:
    RTopController(Session(name="empty"))
    raise AssertionError("expected ValueError for missing hrv")
except ValueError:
    pass

s = session_with_peaks([0.0, 1.0, 2.0])
c = RTopController(s)
c.add_no_classify(0.5)
assert list(c.times) == [0.0, 0.5, 1.0, 2.0]
assert list(s.events["hrv"].times) == [0.0, 0.5, 1.0, 2.0]
assert s.events["hrv"].times.flags.writeable is False

c = RTopController(session_with_peaks([0.0, 1.0, 2.0, 3.0]))
c.move_no_classify(1.0, 2.5)
assert list(c.times) == [0.0, 2.0, 2.5, 3.0]

c = RTopController(session_with_peaks([0.0, 1.0, 2.0]))
c.delete_no_classify(1.1)
assert list(c.times) == [0.0, 2.0]

c = RTopController(session_with_peaks([0.0, 1.0, 2.0]))
try:
    c.labels = np.array(["N", "N"], dtype=object)
    raise AssertionError("expected ValueError for mismatched label length")
except ValueError:
    pass

c = RTopController(session_with_peaks([0.0, 1.0, 2.5]))
ibi = c.ibi
assert approx(ibi[0], 1.0) and approx(ibi[1], 1.5) and np.isnan(ibi[-1])

c = RTopController(session_with_peaks([0.0, 1.0, 2.0, 3.0, 4.0]))
view = c.window_view(1.0, 3.0)
assert list(view.times) == [1.0, 2.0, 3.0]
assert view.labels.shape == view.times.shape == view.ibi.shape

# The final beat's IBI is the trailing-NaN sentinel, so classification always
# labels it "T"; it must NOT be a navigation target (idx 4 below).
c = RTopController(session_with_peaks([0.0, 1.0, 2.0, 3.0, 4.0]))
c.labels = np.array(["N", "S", "N", "L", "T"], dtype=object)
assert approx(c.next_non_normal(0.0), 1.0)
assert approx(c.next_non_normal(1.0), 3.0)
assert c.next_non_normal(3.0) is None            # trailing "T" is excluded
assert approx(c.prev_non_normal(5.0), 3.0)
assert c.prev_non_normal(1.0) is None

s = session_with_peaks([0.0, 1.0, 2.0])
c = RTopController(s)
before = s.events["hrv"]
c.add_no_classify(1.5)
after = s.events["hrv"]
assert after is not before and after.times.size == 4


# --- PrepModel.build (per-load bundle) -------------------------------------
# (The Session→Session pre-processing transforms now live in spectHR and are
#  covered headlessly in test_preprocessing.py; here we just need a loaded
#  session with a device-suffixed ECG and an hrv channel.)
from spectHR.config import CardioParams
from spectHR.session import Samples
from spectUI.widgets.prep.model import PrepModel

fs = 130.0
tt = np.arange(0.0, 20.0, 1.0 / fs)
ecg = np.zeros_like(tt)
for bt in np.arange(0.5, 20.0, 0.8):
    ecg += np.exp(-0.5 * ((tt - bt) / 0.01) ** 2)
peaks = np.arange(0.5, 20.0, 0.8)
out = Session(
    name="xdf",
    samples={"ecg-[Z9]": Samples(tt, ecg, "ecg-[Z9]")},
    events={"hrv": Events(peaks, np.full(peaks.shape, "N", dtype=object))},
)

mdl = PrepModel.build(out, CardioParams())
assert mdl.ecg is not None and mdl.ecg.name == "ecg-[Z9]"   # resolved by prefix
assert mdl.rtop_ctrl is not None                       # hrv present -> editable
assert mdl.ecg is not None and mdl.ecg_display is mdl.ecg   # no display filter
assert mdl.extent is not None and mdl.window.x_min == mdl.extent[0]
assert mdl.has_resp() is False                         # this session has no resp
# The navigator clamps to the model's (constant) extent.
assert mdl.navigator.go_to_end() in (True, False)      # callable, no crash

# display_filtered swaps in a distinct, filtered display channel.
mdl2 = PrepModel.build(out, CardioParams(display_filtered=True))
assert mdl2.ecg_display is not mdl2.ecg

# A session with neither ECG nor hrv yields an "empty but valid" model.
empty_mdl = PrepModel.build(Session(name="e"), CardioParams())
assert empty_mdl.rtop_ctrl is None and empty_mdl.ecg is None
assert empty_mdl.extent is None

print("PREP_LOGIC_OK")
"""


def test_prep_headless_helpers():
    """Exercise window/navigation/RTopController logic in a fresh subprocess."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0 and "PREP_LOGIC_OK" in proc.stdout, (
        f"prep headless-helper checks failed\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
