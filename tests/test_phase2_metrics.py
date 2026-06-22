# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
PLAN.md phase 2: Heather index (ICG), respiration rate / variability, and
beat-to-beat blood-pressure variability.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.epoch_context import EpochContext
from spectHR.analysis.icg_metrics import heather_index
from spectHR.dataset.preprocessing import apply_breath_phases
from spectHR.session import Epoch, Events, Samples, Session


def _col(table, name):
    assert name in table.columns, name
    return float(table.values[0, table.columns.index(name)])


# ---------------------------------------------------------------------------
# Heather index (2a): exercised against an injected ensemble detail so the
# formula is checked without needing a full ICG ensemble pass.
# ---------------------------------------------------------------------------

def test_heather_index_formula():
    rel = np.arange(-50.0, 300.0, 1.0)                 # ms relative to R
    icg = 5.0 * np.exp(-0.5 * ((rel - 120.0) / 8.0) ** 2)   # C-peak 5.0 at 120 ms
    ctx = EpochContext(Events(np.array([0.0, 0.8]), np.array(["N", "N"], object)))
    ctx.pep_detail = {"t_c_ms": 120.0, "t_q_ms": -20.0, "rel_ms": rel, "icg_ens": icg}
    # (dZ/dt)max = 5.0; Q-to-C = (120 - (-20)) / 1000 = 0.14 s -> 5 / 0.14.
    assert abs(heather_index(ctx) - 5.0 / 0.14) < 0.5


def test_heather_index_nan_without_detail():
    ctx = EpochContext(Events(np.array([0.0, 0.8]), np.array(["N", "N"], object)))
    assert np.isnan(heather_index(ctx))


def test_heather_index_nan_without_q():
    rel = np.arange(-50.0, 300.0, 1.0)
    icg = 5.0 * np.exp(-0.5 * ((rel - 120.0) / 8.0) ** 2)
    ctx = EpochContext(Events(np.array([0.0, 0.8]), np.array(["N", "N"], object)))
    ctx.pep_detail = {"t_c_ms": 120.0, "t_q_ms": float("nan"),
                      "rel_ms": rel, "icg_ens": icg}
    assert np.isnan(heather_index(ctx))


# ---------------------------------------------------------------------------
# Respiration rate / variability (2b)
# ---------------------------------------------------------------------------

def test_resp_rate_bpm_and_rrv():
    fs = 50.0
    t = np.arange(0.0, 120.0, 1.0 / fs)
    resp = np.sin(2 * np.pi * 0.25 * t)               # 0.25 Hz = 15 breaths/min
    peaks = np.arange(0.5, 120.0, 0.8)
    s = Session(
        name="r",
        samples={"resp": Samples(t, resp, "resp")},
        events={"hrv": Events(peaks, np.full(peaks.shape, "N", object))},
        epochs={"whole": Epoch("whole", 0.0, 120.0, True)},
    )
    s = apply_breath_phases(s, None)
    assert s.breath is not None
    t_ = s.epochs_table()
    rf, rb = _col(t_, "resp_freq"), _col(t_, "resp_rate_bpm")
    assert np.isfinite(rb) and abs(rb - 60.0 * rf) < 1e-6
    assert abs(rb - 15.0) < 2.0                        # ~15 breaths/min
    assert np.isfinite(_col(t_, "rrv")) and _col(t_, "rrv") >= 0.0


# ---------------------------------------------------------------------------
# Blood-pressure variability (2c)
# ---------------------------------------------------------------------------

def test_bp_variability_sd():
    fs = 100.0
    t = np.arange(0.0, 40.0, 1.0 / fs)
    # Pulsatile BP whose amplitude drifts slowly, so SBP/DBP vary beat to beat.
    bp = 100.0 + (20.0 + 8.0 * np.sin(2 * np.pi * 0.04 * t)) * np.sin(2 * np.pi * 1.1 * t)
    peaks = np.arange(0.5, 40.0, 0.8)
    s = Session(
        name="b",
        samples={"bp": Samples(t, bp, "bp")},
        events={"hrv": Events(peaks, np.full(peaks.shape, "N", object))},
        epochs={"whole": Epoch("whole", 0.0, 40.0, True)},
    )
    t_ = s.epochs_table()
    assert np.isfinite(_col(t_, "sbp_sd")) and _col(t_, "sbp_sd") > 0.0
    assert np.isfinite(_col(t_, "dbp_sd")) and _col(t_, "dbp_sd") > 0.0


def test_bp_variability_nan_without_bp():
    peaks = np.arange(0.5, 40.0, 0.8)
    s = Session(
        name="n",
        events={"hrv": Events(peaks, np.full(peaks.shape, "N", object))},
        epochs={"whole": Epoch("whole", 0.0, 40.0, True)},
    )
    t_ = s.epochs_table()
    assert np.isnan(_col(t_, "sbp_sd"))
