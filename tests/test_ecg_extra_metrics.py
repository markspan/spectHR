# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
PLAN.md phase 1: the additional ECG / IBI Results columns.

Frequency completeness (normalised units, total power, ln HF, per-band % and
peak), time-domain staples (pNN50, mean/SD HR, CVNN/CVSD, triangular index,
TINN), Poincaré CSI/CVI, and DFA-alpha2.  Each is pinned to its definition on a
synthetic series.
"""
from __future__ import annotations

import numpy as np

from conftest import WORKSPACE_BANDS, make_cs, make_spectral_cs, make_two_sinusoid_cs
from spectHR.analysis import ecg_metrics as M
from spectHR.analysis.epoch_context import EpochContext
from spectHR.analysis.psd import PsdMethod
from spectHR.session import AnalysisConfig


def _method():
    return PsdMethod(algorithm="carspan", bands=dict(WORKSPACE_BANDS),
                     mean_convention="harmonic")


# ---------------------------------------------------------------------------
# Frequency-domain completeness (1a)
# ---------------------------------------------------------------------------

def test_normalised_units_sum_to_100_and_total_positive():
    ctx = EpochContext(make_two_sinusoid_cs(0.10, 0.25),
                       config=AnalysisConfig(psd_method=_method()))
    lfn, hfn = M.lf_nu(ctx), M.hf_nu(ctx)
    assert np.isfinite(lfn) and np.isfinite(hfn)
    assert abs(lfn + hfn - 100.0) < 1e-6
    tp = M.total_power(ctx)
    assert np.isfinite(tp) and tp > 0
    assert np.isfinite(M.ln_hf(ctx))


def test_band_rel_percentages_sum_to_100():
    ctx = EpochContext(make_two_sinusoid_cs(0.10, 0.25),
                       config=AnalysisConfig(psd_method=_method()))
    rel = M.band_rel(ctx)
    assert {"vlf_pct", "lf_pct", "hf_pct"} <= set(rel)
    assert abs(sum(rel.values()) - 100.0) < 1e-6


def test_band_peak_frequencies_fall_in_their_bands():
    ctx = EpochContext(make_two_sinusoid_cs(0.10, 0.25),
                       config=AnalysisConfig(psd_method=_method()))
    peak = M.band_peak(ctx)
    lf, hf = WORKSPACE_BANDS["LF"], WORKSPACE_BANDS["HF"]
    assert lf.low <= peak["lf_peak_hz"] <= lf.high
    assert hf.low <= peak["hf_peak_hz"] <= hf.high


def test_frequency_metrics_nan_without_method():
    ctx = EpochContext(make_spectral_cs(0.25), config=AnalysisConfig(psd_method=None))
    assert np.isnan(M.lf_nu(ctx)) and np.isnan(M.total_power(ctx))
    assert M.band_rel(ctx) == {} and M.band_peak(ctx) == {}


# ---------------------------------------------------------------------------
# Time-domain staples (1b)
# ---------------------------------------------------------------------------

def test_pnn50_nn50_definition():
    # Diffs: 100, 0, 100, 0 ms -> two diffs exceed 50 of four -> 50 %.
    cs = make_cs([800, 900, 900, 1000, 1000])
    assert M.nn50(cs) == 2.0
    assert abs(M.pnn50(cs) - 50.0) < 1e-9
    assert M.nn20(cs) == 2.0


def test_mean_hr_and_cv():
    cs = make_cs([800] * 20)             # constant 800 ms -> 75 bpm, zero CV
    assert abs(M.mean_hr(cs) - 75.0) < 1e-6
    assert abs(M.cvnn(cs)) < 1e-9
    assert abs(M.sd_hr(cs)) < 1e-9


def test_triangular_index_and_tinn_finite():
    cs = make_spectral_cs(0.25)
    ti = M.hrv_ti(cs)
    assert np.isfinite(ti) and ti >= 1.0     # N / peak bin >= 1
    tinn = M.tinn(cs)
    assert np.isfinite(tinn) and tinn > 0.0


# ---------------------------------------------------------------------------
# Poincaré CSI / CVI (1c) and DFA-alpha2 (1d)
# ---------------------------------------------------------------------------

def test_csi_cvi_consistency():
    cs = make_spectral_cs(0.25)
    s1, s2 = M.sd1(cs), M.sd2(cs)
    assert M.csi(cs) > 0
    assert abs(M.csi(cs) - s2 / s1) < 1e-9         # L/T = SD2/SD1
    assert abs(M.cvi(cs) - np.log10(16.0 * s1 * s2)) < 1e-9
    assert M.modified_csi(cs) > 0


def test_dfa_a2_finite_with_enough_beats():
    cs = make_spectral_cs(0.1, duration_s=300.0)   # ~375 beats >= 2*64
    assert np.isfinite(M.dfa_a2(cs))


def test_dfa_a2_nan_when_too_short():
    cs = make_cs([800] * 50)                        # < 128 beats
    assert np.isnan(M.dfa_a2(cs))
