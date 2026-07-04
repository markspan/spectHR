# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for the autoregressive (Burg) PSD back-end.

Checks that the parametric spectrum resolves a known oscillation, that it
dispatches through :class:`PSDEngine` and the workspace config bridge, and
that it integrates band power like the other tachogram methods.
"""
from __future__ import annotations

import numpy as np

from spectHR.analysis.psd import (
    AutoregressiveOptions,
    PsdMethod,
    PSDEngine,
    compute_autoregressive_psd,
)
from spectHR.config import WorkspaceView
from spectHR.session import Events


def _oscillating_tachogram(f0: float = 0.25, mean_ms: float = 1000.0,
                           amp_ms: float = 60.0, n: int = 300):
    """IBI series whose tachogram oscillates at *f0* Hz."""
    # Build times by accumulating IBIs; modulate the IBI at f0.
    t = 0.0
    times = []
    values = []
    for _ in range(n):
        ibi_ms = mean_ms + amp_ms * np.sin(2 * np.pi * f0 * t)
        times.append(t)
        values.append(ibi_ms)
        t += ibi_ms / 1000.0
    return np.asarray(times, float), np.asarray(values, float)


def test_ar_psd_resolves_known_peak():
    """The AR spectrum peaks at the injected tachogram frequency."""
    f0 = 0.25
    times, values = _oscillating_tachogram(f0=f0)
    res = compute_autoregressive_psd(times, values, f_max=0.5)
    assert res.method == "autoregressive"
    assert res.unit == "ms²/Hz"
    peak_hz = float(res.freqs[int(np.argmax(res.power))])
    assert abs(peak_hz - f0) < 0.03, f"peak at {peak_hz}, expected ~{f0}"


def test_ar_psd_via_engine_events():
    """PSDEngine dispatches algorithm='autoregressive' and converts units."""
    f0 = 0.25
    times, values = _oscillating_tachogram(f0=f0)
    # An Events series carrying the beat times; ibi is derived from them.
    peaks = np.asarray(times, float)
    labels = np.full(peaks.shape, "N", dtype=object)
    ev = Events(peaks, labels)

    method = PsdMethod(algorithm="autoregressive")
    res = PSDEngine(ev).compute(method)
    assert res.method == "autoregressive"
    assert res.unit == "mMI²/Hz"          # default units → normalised
    assert np.all(np.isfinite(res.power))
    # Band power in the HF band (0.15-0.40) must exceed VLF (0.02-0.06).
    hf = PSDEngine(ev).for_band_power(method)
    from spectHR.analysis.psd import band_power_rectangular
    p_hf = band_power_rectangular(hf.freqs, hf.power, 0.15, 0.40)
    p_vlf = band_power_rectangular(hf.freqs, hf.power, 0.02, 0.06)
    assert p_hf > p_vlf


def test_ar_options_from_workspace():
    """The config bridge builds AutoregressiveOptions and selects the method."""
    ws = {
        "FrequencyAnalysis": {
            "method": "autoregressive",
            "autoregressive": {"fs": 4.0, "order": 12, "nfreqs": 256},
        }
    }
    method = WorkspaceView(ws).psd_method
    assert method.algorithm == "autoregressive"
    assert isinstance(method.autoregressive, AutoregressiveOptions)
    assert method.autoregressive.order == 12
    assert method.autoregressive.nfreqs == 256


def test_ar_burg_is_stable_on_short_series():
    """Order is clamped and no exception is raised on a short series."""
    times, values = _oscillating_tachogram(n=20)
    res = compute_autoregressive_psd(
        times, values, f_max=0.5, options=AutoregressiveOptions(order=16),
    )
    assert np.all(np.isfinite(res.power))
