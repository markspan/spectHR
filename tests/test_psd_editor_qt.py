# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The PSD tab greys out method-specific settings that don't apply.

Subprocess-isolated (Qt must not enter the shared pytest process).  Builds the
ParametersEditorDialog and checks that only the chosen PSD method's
sub-section is enabled, that switching the method combo re-targets the enabled
section, and that carspan_strict shares the carspan section.
"""
from __future__ import annotations

import os
import subprocess
import sys

_DRIVER = r"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox

app = QApplication.instance() or QApplication([])

from spectUI.parameters import Parameters
from spectUI.widgets.workspace_editor import ParametersEditorDialog


def build(method):
    ws = Parameters.default().to_dict()
    ws["FrequencyAnalysis"]["method"] = method
    return ParametersEditorDialog(ws)


def grp(dlg, section):
    return dlg._section_groups.get(f"FrequencyAnalysis.{section}")


ALL = ("welch", "lombscargle", "autoregressive", "carspan")

# --- initial state follows the configured method ---------------------------
dlg = build("welch")
assert grp(dlg, "welch").isEnabled()
for sec in ("lombscargle", "autoregressive", "carspan"):
    assert not grp(dlg, sec).isEnabled(), f"{sec} should be greyed for welch"

# --- switching the combo re-targets the enabled section --------------------
combo = dlg._widgets["FrequencyAnalysis.method"][0]
assert isinstance(combo, QComboBox)


def select(value):
    idx = next(i for i in range(combo.count())
               if combo.itemData(i, Qt.UserRole) == value)
    combo.setCurrentIndex(idx)


select("autoregressive")
assert grp(dlg, "autoregressive").isEnabled()
for sec in ("welch", "lombscargle", "carspan"):
    assert not grp(dlg, sec).isEnabled(), f"{sec} should be greyed for AR"

# --- carspan_strict shares the carspan section -----------------------------
select("carspan_strict")
assert grp(dlg, "carspan").isEnabled()
for sec in ("welch", "lombscargle", "autoregressive"):
    assert not grp(dlg, sec).isEnabled(), f"{sec} should be greyed for strict"


def leaf(field):
    return dlg._widgets[f"FrequencyAnalysis.carspan.{field}"][0]


def leaf_label(field):
    return dlg._field_labels[f"FrequencyAnalysis.carspan.{field}"]


# Under strict, the preset-overridden knobs are greyed (field and label),
# but smooth_for_display, carried over from the user's setting, stays active.
assert leaf("smooth_for_display").isEnabled()
for field in ("signal", "freq_resolution", "window", "dc_removal"):
    assert not leaf(field).isEnabled(), f"{field} should be greyed under strict"
    assert not leaf_label(field).isEnabled(), f"{field} label should be greyed"

# --- plain carspan re-enables every carspan knob ---------------------------
select("carspan")
assert grp(dlg, "carspan").isEnabled()
for field in ("signal", "freq_resolution", "window", "dc_removal",
              "smooth_for_display"):
    assert leaf(field).isEnabled(), f"{field} should be editable for plain carspan"
    assert leaf_label(field).isEnabled(), f"{field} label should be active"

# --- lombscargle path ------------------------------------------------------
select("lombscargle")
assert grp(dlg, "lombscargle").isEnabled()
for sec in ("welch", "autoregressive", "carspan"):
    assert not grp(dlg, sec).isEnabled()

# --- titlecase labels + tooltips + AR one-line grouping --------------------
d2 = build("carspan")

# Labels are title-cased without lowercasing the rest (acronyms survive) and
# pre-formatted unit keys keep their internal spelling.
assert d2._field_labels["CardioParameters.IbiClassification.n_std"].text() == "N Std:"
assert d2._field_labels["Profiles.window (sec)"].text() == "Window (sec):"

# Every field carries a tooltip with its explanation and default, shared with
# the label so hovering either shows it.
w_nstd = d2._widgets["CardioParameters.IbiClassification.n_std"][0]
tip = w_nstd.toolTip()
assert "standard deviations" in tip and "default: 3.0" in tip, tip
assert d2._field_labels["CardioParameters.IbiClassification.n_std"].toolTip() == tip
assert "default: carspan" in d2._widgets["FrequencyAnalysis.method"][0].toolTip()

# The autoregressive options render on one horizontal row.
assert d2._HORIZONTAL_GROUPS["FrequencyAnalysis.autoregressive.fs"] == ["order", "nfreqs"]

print("PSD_EDITOR_OK")
"""


def test_psd_editor_greys_inactive_sections():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0 and "PSD_EDITOR_OK" in proc.stdout, (
        f"PSD editor greying test failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
