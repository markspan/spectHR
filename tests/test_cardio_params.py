# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for the ``CardioParameters`` workspace accessor.

:class:`~spectHR.config.CardioParams` carries the ECG prefilter, R-peak
detector, and IBI-classifier settings the pre-processing pipeline needs.
These checks pin the defaults (which must match the spectUI workspace
defaults) and the round-trip from a raw workspace dict.
"""
from __future__ import annotations

from spectHR.config import (
    CardioParams,
    WorkspaceView,
    cardio_params_from_workspace,
)


def test_defaults_match_workspace_defaults():
    cp = cardio_params_from_workspace(None)
    assert cp.window_length == 20
    assert cp.n_std == 3.0
    assert cp.max_ibi_sec == 2.5
    assert cp.min_peak_distance_ms == 300.0
    assert cp.ecg_filter_type == "highpass"
    assert cp.ecg_filter_cutoff == 0.5
    assert cp.display_filtered is False


def test_reads_values_from_workspace():
    ws = {
        "CardioParameters": {
            "IbiClassification": {
                "window_length": 7,
                "n_std": 2.5,
                "max_ibi_sec": 1.8,
                "min_peak_distance_ms": 250.0,
            },
            "EcgPreprocessing": {
                "filter_type": "lowpass",
                "filter_cutoff": 40.0,
            },
        }
    }
    cp = cardio_params_from_workspace(ws)
    assert cp.window_length == 7
    assert cp.n_std == 2.5
    assert cp.max_ibi_sec == 1.8
    assert cp.min_peak_distance_ms == 250.0
    assert cp.ecg_filter_type == "lowpass"
    assert cp.ecg_filter_cutoff == 40.0


def test_classify_kwargs_subset():
    cp = CardioParams(window_length=11, n_std=4.0, max_ibi_sec=2.0)
    assert cp.classify_kwargs == {
        "window_length": 11,
        "n_std": 4.0,
        "max_ibi_sec": 2.0,
    }


def test_empty_filter_type_disables_prefilter():
    ws = {"CardioParameters": {"EcgPreprocessing": {"filter_type": ""}}}
    assert cardio_params_from_workspace(ws).ecg_filter_type is None


def test_display_filtered_read_from_workspace():
    ws = {"CardioParameters": {"EcgPreprocessing": {"display_filtered": True}}}
    assert cardio_params_from_workspace(ws).display_filtered is True


def test_workspaceview_property_is_cached():
    view = WorkspaceView({"CardioParameters": {"IbiClassification": {"n_std": 9.0}}})
    first = view.cardio_params
    assert first.n_std == 9.0
    assert view.cardio_params is first  # cached_property returns the same object
