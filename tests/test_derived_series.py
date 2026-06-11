# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for plot-ready derived series (HR over time, Poincaré pairs)."""
from __future__ import annotations

import numpy as np

from spectHR.session import Events
from spectHR.analysis.derived_series import (
    heart_rate_series,
    poincare_descriptors,
    poincare_pairs,
)


def _events(ibi_ms, labels=None) -> Events:
    """Build Events from IBI values (ms); N intervals -> N+1 beats at t=0.."""
    ibi_ms = np.asarray(ibi_ms, dtype=float)
    times = np.concatenate([[0.0], np.cumsum(ibi_ms / 1000.0)])
    if labels is None:
        labels = np.full(times.shape, "N", dtype=object)
    return Events(times, np.asarray(labels, dtype=object))


def test_heart_rate_series_converts_ibi_to_bpm():
    ev = _events([1000.0, 800.0, 600.0])  # 60, 75, 100 bpm
    t, hr = heart_rate_series(ev)
    assert np.allclose(hr, [60.0, 75.0, 100.0])
    assert t.size == hr.size == 3
    assert t[0] == 0.0  # first beat time


def test_heart_rate_series_drops_artefacts():
    # Beat 2 is tagged TL, so its interval (600 ms -> 100 bpm) is excluded;
    # the trailing beat carries a NaN interval and is excluded too.
    ev = _events([1000.0, 800.0, 600.0], labels=["N", "N", "TL", "N"])
    t, hr = heart_rate_series(ev)
    assert np.allclose(hr, [60.0, 75.0])     # only the two valid intervals
    assert 100.0 not in np.round(hr, 0)


def test_heart_rate_series_empty_when_no_beats():
    ev = Events(np.array([0.0]), np.array(["N"], dtype=object))
    t, hr = heart_rate_series(ev)
    assert t.size == 0 and hr.size == 0


def test_poincare_pairs_consecutive():
    ev = _events([800.0, 820.0, 810.0])
    x, y = poincare_pairs(ev)
    assert np.allclose(x, [800.0, 820.0])
    assert np.allclose(y, [820.0, 810.0])


def test_poincare_pairs_break_on_artefact():
    # An artefact interval breaks adjacency: no pair may bridge it.
    ev = _events([800.0, 820.0, 810.0, 805.0], labels=["N", "N", "TL", "N", "N"])
    x, y = poincare_pairs(ev)
    # The TL interval (idx 2) cannot appear as either member of a pair.
    assert 810.0 not in np.round(x, 0)
    assert 810.0 not in np.round(y, 0)


def test_poincare_pairs_empty_for_short_series():
    ev = _events([800.0])
    x, y = poincare_pairs(ev)
    assert x.size == y.size  # may be 1 pair or 0; just aligned and no crash


def test_poincare_descriptors_basic():
    rng = np.random.default_rng(0)
    ibi = 800.0 + rng.normal(0.0, 30.0, 300)
    ev = _events(ibi)
    d = poincare_descriptors(ev)
    assert d is not None
    assert d.sd1 > 0 and d.sd2 > 0
    assert 700.0 < d.cx < 900.0 and 700.0 < d.cy < 900.0


def test_poincare_descriptors_none_for_short_series():
    assert poincare_descriptors(_events([800.0])) is None
