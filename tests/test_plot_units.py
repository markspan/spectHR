# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The display unit is a single top-level setting (``FrequencyAnalysis.plot_units``).

The per-method options bundles no longer carry their own ``units`` /
``plot_units`` field; the one ``PsdMethod.plot_units`` drives every method.
These checks pin that, and that the shipped presets were migrated to the
top-level key (so taskforce / vuams still emit ms²/Hz).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from spectHR.analysis.psd import PSDEngine, PsdMethod
from spectHR.config import WorkspaceView
from spectHR.session import Events

_PRESETS = Path(__file__).resolve().parents[1] / "presets"


def _events(n: int = 200):
    rng = np.random.default_rng(0)
    ibi = 1.0 + rng.normal(0.0, 0.02, n)
    peaks = np.cumsum(np.clip(ibi, 0.4, 1.6))
    return Events(peaks, np.full(peaks.shape, "N", dtype=object))


def test_plot_units_single_source_drives_every_method():
    ev = _events()
    for algo in ("welch", "lombscargle", "autoregressive", "carspan",
                 "carspan_strict"):
        r_ms = PSDEngine(ev).compute(PsdMethod(algorithm=algo, plot_units="ms²/Hz"))
        assert "ms" in r_ms.unit, f"{algo} should honour ms² plot_units"
        r_norm = PSDEngine(ev).compute(
            PsdMethod(algorithm=algo, plot_units="mMI²/Hz")
        )
        assert "mMI" in r_norm.unit, f"{algo} should honour mMI² plot_units"


def _preset_plot_units(name: str) -> str:
    ws = json.loads((_PRESETS / name).read_text(encoding="utf-8"))
    return WorkspaceView(ws).psd_method.plot_units


def test_presets_use_top_level_plot_units():
    # taskforce / vuams relied on a per-method welch.units="ms²"; the migration
    # moved that to the top-level plot_units, so their ms² output is preserved.
    assert _preset_plot_units("taskforce.json") == "ms²/Hz"
    assert _preset_plot_units("vuams_welch.json") == "ms²/Hz"
    # carspan_manual set only default (mMI²) per-method units → normalised.
    assert _preset_plot_units("carspan_manual.json") == "mMI²/Hz"


def test_legacy_per_method_units_key_is_ignored():
    """An old workspace with a stale per-method units key still loads cleanly."""
    ws = {
        "FrequencyAnalysis": {
            "method": "welch",
            "plot_units": "ms²/Hz",
            "welch": {"fs": 4.0, "units": "mMI²"},   # stale key, must be dropped
        }
    }
    method = WorkspaceView(ws).psd_method
    assert method.plot_units == "ms²/Hz"
    assert not hasattr(method.welch, "units")
