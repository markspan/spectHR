# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for the metric-facing :class:`~spectHR.session.AnalysisConfig` builder.

``WorkspaceView.analysis_config`` is the single place the typed workspace
settings are mapped onto the flat config the epoch metrics consume;
``AnalysisConfig.from_workspace`` delegates to it.  These checks pin that
delegation and the typed :class:`~spectHR.session.TransferConfig` it carries.
"""
from __future__ import annotations

from spectHR.config import WorkspaceView
from spectHR.session import AnalysisConfig, TransferConfig


def test_from_workspace_delegates_to_view():
    """``AnalysisConfig.from_workspace`` is a shim over ``analysis_config``."""
    ws = {
        "RespirationAnalysis": {"rsa_lag_s": 1.5},
        "PrsaAnalysis": {"prsa_window": 42},
        "IcgAnalysis": {"b_point_guard_ms": 25.0},
    }
    built = AnalysisConfig.from_workspace(ws)
    direct = WorkspaceView(ws).analysis_config()
    assert built.rsa_lag_s == direct.rsa_lag_s == 1.5
    assert built.prsa_window == direct.prsa_window == 42
    assert built.b_point_guard_ms == direct.b_point_guard_ms == 25.0


def test_transfer_config_is_typed():
    """The transfer settings surface as a typed ``TransferConfig``, not a dict."""
    ws = {
        "TransferAnalysis": {"input_signal": "bp_sys", "min_coherence": 0.7, "f_max": 0.4},
        "FrequencyAnalysis": {
            "bands": {
                "FullRange": {"low": 0.02, "high": 0.50},
                "LF": {"low": 0.07, "high": 0.14},
                "HF": {"low": 0.15, "high": 0.40},
            }
        },
    }
    cfg = AnalysisConfig.from_workspace(ws).transfer_config
    assert isinstance(cfg, TransferConfig)
    assert cfg.input_signal == "bp_sys"
    assert cfg.min_coherence == 0.7
    assert cfg.f_max == 0.4
    # FullRange is a display-only overview band and must be excluded.
    assert set(cfg.bands) == {"LF", "HF"}
    assert cfg.bands["LF"] == (0.07, 0.14)


def test_transfer_config_defaults_are_typed():
    """An empty workspace still yields a typed config with sane defaults."""
    cfg = AnalysisConfig.from_workspace(None).transfer_config
    assert isinstance(cfg, TransferConfig)
    assert cfg.bands == {}


def test_transfer_config_is_immutable():
    """``TransferConfig`` is frozen, so a run's settings cannot be mutated."""
    import dataclasses
    import pytest

    cfg = TransferConfig(input_signal="rsp")
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.input_signal = "bp_sys"  # type: ignore[misc]
