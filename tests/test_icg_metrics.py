# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
tests/test_icg_metrics.py -- pre-ejection period (PEP) from ICG dZ/dt.

Covers the VU-DAMS-aligned ensemble PEP scorer in
``spectHR.analysis.icg_metrics``:

- ensemble scoring on a synthetic dZ/dt complex (B before C, plausible PEP)
- the ``return_detail`` dict: landmark ordering (Q < 0 < B < C) and curves
- the 30 ms B-point guard (excludes the zone immediately before C)
- the registered landmark @epoch_metric functions reading the cached detail
- graceful NaN / None on degenerate input
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.icg_metrics import (
    _b_point_index,
    pep_ensemble,
    pep_b_ms,
    pep_c_ms,
    pep_q_ms,
    pep_n_beats,
)


def _synthetic_icg(n_beats=30, fs=1000.0, hr_s=0.8,
                   t_b_ms=80.0, t_c_ms=120.0, q_ms=-40.0):
    """Build clean ECG + dZ/dt waveforms with known landmarks.

    The dZ/dt complex per beat is a smooth ejection bump peaking (C) at
    ``t_c_ms`` after the R-peak, with an upstroke inflection (B) near
    ``t_b_ms``. Stored with VU-AMS polarity (C as a *minimum*) so the
    detector's polarity auto-correction is exercised. The ECG carries an R
    spike at the beat onset and a small Q dip before it.
    """
    dt = 1.0 / fs
    rpeaks = np.arange(1.0, 1.0 + n_beats * hr_s, hr_s)
    t = np.arange(0.0, rpeaks[-1] + hr_s, dt)
    dz = np.zeros_like(t)
    ecg = np.zeros_like(t)
    tc, tb = t_c_ms / 1000.0, t_b_ms / 1000.0
    width = (tc - tb) * 2.0
    for r in rpeaks:
        # dZ/dt ejection bump: gaussian centred at C (stored negative = VU sign)
        dz += -np.exp(-0.5 * ((t - (r + tc)) / (width / 2.355)) ** 2)
        # ECG: sharp R at r, small Q dip just before
        ecg += np.exp(-0.5 * ((t - r) / (3.0 * dt)) ** 2)
        ecg -= 0.15 * np.exp(-0.5 * ((t - (r + q_ms / 1000.0)) / (5.0 * dt)) ** 2)
    return rpeaks, t, dz, ecg


def test_pep_ensemble_scalar_plausible():
    rpeaks, t, dz, ecg = _synthetic_icg()
    val = pep_ensemble(t, dz, rpeaks, ecg_times=t, ecg_values=ecg)
    assert np.isfinite(val)
    assert 40.0 <= val <= 180.0


def test_pep_return_detail_landmark_ordering():
    rpeaks, t, dz, ecg = _synthetic_icg()
    d = pep_ensemble(t, dz, rpeaks, ecg_times=t, ecg_values=ecg,
                     return_detail=True)
    assert d is not None
    # Q-onset before R, B before C, all in the systolic window.
    assert d["t_q_ms"] < 0.0 < d["t_b_ms"] < d["t_c_ms"]
    # Polarity auto-detected as inverted (VU-AMS stores C as a minimum).
    assert d["polarity"] == -1.0
    # Ensemble curves present and the right shape.
    assert d["rel_ms"].shape == d["icg_ens"].shape
    assert d["ecg_ens"] is not None
    assert d["rel_ms"][0] == -200.0 and d["rel_ms"][-1] >= 399.0
    assert d["n_beats"] >= 5
    # The scalar pep equals the gated B - Q interval.
    assert np.isclose(d["pep"], d["t_b_ms"] - d["t_q_ms"], atol=1.0)


def test_pep_no_ecg_uses_rpeak_reference():
    """Without ECG the reference is the R-peak (Q-onset = 0)."""
    rpeaks, t, dz, _ = _synthetic_icg()
    d = pep_ensemble(t, dz, rpeaks, return_detail=True)
    assert d is not None
    assert d["t_q_ms"] == 0.0
    assert d["ecg_ens"] is None


def test_b_point_guard_flows_through_epoch_context():
    """``EpochContext.b_point_guard_ms`` reaches ``pep_ensemble`` (config path).

    The guard is honoured by the per-epoch table, not just the bare
    ``_b_point_index`` helper: building a context with two different guards
    yields two different B-points / PEP values for the same ICG.
    """
    from types import SimpleNamespace
    from spectHR.session import AnalysisConfig

    from spectHR.analysis.epoch_context import EpochContext

    rpeaks, t, dz, ecg = _synthetic_icg()
    view = SimpleNamespace(
        times=rpeaks,
        ibi=np.diff(rpeaks, prepend=rpeaks[0]),
        labels=np.full(rpeaks.shape, "N", dtype=object),
    )
    icg_ts = SimpleNamespace(times=t, values=dz)
    ecg_ts = SimpleNamespace(times=t, values=ecg)

    def pep_for(guard):
        ctx = EpochContext(view, icg_ts=icg_ts, ecg_ts=ecg_ts,
                           config=AnalysisConfig(b_point_guard_ms=guard))
        return ctx.pep_value

    near, far = pep_for(0.0), pep_for(60.0)
    assert near is not None and far is not None
    assert np.isfinite(near) and np.isfinite(far)
    assert near != far          # the guard actually changes the result


def test_b_point_guard_excludes_zone_before_c():
    """The 30 ms guard moves B earlier when a bump sits just before C.

    Two upstroke acceleration features are built from logistic steps, whose
    positive 2nd-derivative lobe peaks at ``centre − 1.317·w``:
      - a true B inflection at ~70 ms (weaker), and
      - a stronger secondary bump at ~105 ms, only 15 ms before C (120 ms).
    Without the guard the global 2nd-derivative max latches onto the late
    secondary bump; the 30 ms guard (ceiling 90 ms) excludes it and recovers
    the true early B.
    """
    fs = 1000.0
    rel = np.arange(-0.2, 0.4, 1.0 / fs)
    c_idx = int(np.argmin(np.abs(rel - 0.120)))
    lo_idx = int(np.argmin(np.abs(rel - 0.040)))
    w = 0.004
    def _logistic(centre):
        return 1.0 / (1.0 + np.exp(-(rel - centre) / w))
    ens = (1.0 * _logistic(0.070 + 1.317 * w)      # true B lobe ≈ 70 ms
           + 2.0 * _logistic(0.105 + 1.317 * w))   # secondary lobe ≈ 105 ms
    guarded = _b_point_index(rel, ens, c_idx, lo_idx, guard_ms=30.0)
    unguarded = _b_point_index(rel, ens, c_idx, lo_idx, guard_ms=0.0)
    # Guarded B lands on the early inflection; unguarded on the late bump.
    assert rel[guarded] * 1000.0 < 90.0
    assert rel[unguarded] * 1000.0 > 95.0
    assert rel[guarded] < rel[unguarded]


def test_landmark_metrics_read_cached_detail():
    """The registered pep_* metrics pull from ctx.pep_detail."""
    rpeaks, t, dz, ecg = _synthetic_icg()
    detail = pep_ensemble(t, dz, rpeaks, ecg_times=t, ecg_values=ecg,
                          return_detail=True)

    class _Ctx:
        pep_detail = detail

    ctx = _Ctx()
    assert np.isclose(pep_b_ms(ctx), detail["t_b_ms"])
    assert np.isclose(pep_c_ms(ctx), detail["t_c_ms"])
    assert np.isclose(pep_q_ms(ctx), detail["t_q_ms"])
    assert pep_n_beats(ctx) == detail["n_beats"]


def test_landmark_metrics_nan_without_detail():
    """Bare context (no ICG) yields NaN landmarks, never an exception."""
    class _Bare:
        pass

    bare = _Bare()
    for fn in (pep_b_ms, pep_c_ms, pep_q_ms, pep_n_beats):
        assert np.isnan(fn(bare))


def test_pep_ensemble_degenerate_returns_nan_or_none():
    rpeaks = np.array([1.0, 2.0])          # fewer than min_beats
    t = np.linspace(0.0, 3.0, 3000)
    dz = np.zeros_like(t)
    assert np.isnan(pep_ensemble(t, dz, rpeaks))
    assert pep_ensemble(t, dz, rpeaks, return_detail=True) is None
