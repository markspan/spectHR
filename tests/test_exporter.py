# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Headless tests for the per-epoch results exporter (CSV + HDF5).

``EpochExporter`` and the writers are Qt-free, so this runs in-process.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from spectHR.analysis.exporter import (
    EpochExporter,
    write_results_csv,
    write_results_h5,
)
from spectHR.dataset.preprocessing import apply_breath_phases
from spectHR.session import AnalysisConfig, Epoch, Events, Samples, Session

# Minimal workspace with frequency bands (no Qt / Parameters import needed).
_WS = {
    "FrequencyAnalysis": {
        "method": "carspan",
        "bands": {
            "FullRange": {"low": 0.02, "high": 0.50, "color": "gray", "alpha": 0.35},
            "VLF":       {"low": 0.02, "high": 0.06},
            "LF":        {"low": 0.07, "high": 0.14},
            "HF":        {"low": 0.15, "high": 0.40},
        },
    },
}


def _session():
    fs = 50.0
    t = np.arange(0.0, 120.0, 1.0 / fs)
    peaks = np.arange(0.5, 120.0, 0.8)
    s = Session(
        name="x",
        samples={"ecg": Samples(t, np.sin(2 * np.pi * 1.2 * t), "ecg"),
                 "resp": Samples(t, np.sin(2 * np.pi * 0.25 * t), "resp")},
        events={"hrv": Events(peaks, np.full(peaks.shape, "N", object))},
        epochs={"a": Epoch("a", 0.0, 60.0, True), "b": Epoch("b", 60.0, 120.0, True)},
    )
    return apply_breath_phases(s, None)


def test_collect_has_arrays_per_epoch():
    s = _session()
    tbl = s.epochs_table(AnalysisConfig.from_workspace(_WS))
    data = EpochExporter(_WS, tbl.contexts).collect()
    assert set(data) == {"a", "b"}
    for ed in data.values():
        # respiration (RSA) and the spectral arrays are present for this session.
        assert ed["psd"] is not None
        assert ed["profile"] is not None
        assert ed["respiration"] is not None and ed["respiration"]["rsa"].size > 0


def test_write_csv(tmp_path: Path):
    s = _session()
    tbl = s.epochs_table(AnalysisConfig.from_workspace(_WS))
    out = tmp_path / "results.csv"
    write_results_csv(out, tbl)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("epoch,")           # header
    assert len(lines) == 1 + len(tbl.labels)        # header + one row per epoch
    assert lines[1].split(",")[0] == "a"


def test_write_h5(tmp_path: Path):
    import h5py

    s = _session()
    tbl = s.epochs_table(AnalysisConfig.from_workspace(_WS))
    data = EpochExporter(_WS, tbl.contexts).collect()
    out = tmp_path / "results.h5"
    write_results_h5(out, tbl, data)
    with h5py.File(out, "r") as hf:
        assert hf.attrs["specthr_export_version"] == "3"
        assert set(hf.keys()) == {"a", "b"}
        ga = hf["a"]
        assert "psd" in ga and "freqs" in ga["psd"]      # arrays present
        assert "rmssd" in ga.attrs                       # metric scalar attr
        assert ga["psd"]["freqs"].shape[0] > 0
