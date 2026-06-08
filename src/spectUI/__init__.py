# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from spectUI.common import LineHandler
from spectUI.preProcessFile import PreProcessFile, apply_bp_calibration, apply_rsp_source
from spectUI.widgets import (
    DirectorySelectorDialog,
    EventCodeWindow,
    LogWidget,
    ParametersEditorDialog,
)
from spectUI.parameters import Parameters, populate_tree
from spectUI.settings import AppSettings
from spectHR.DataSet.loaders.code_selection import register_code_resolver


def _evt_code_resolver(other_codes, rtop_code):
    """Dialog-backed resolver for the headless ``.evt`` loader hook."""
    window = EventCodeWindow(other_codes, ignore=rtop_code)
    window.exec()
    return window.start_codes, window.stop_codes


register_code_resolver(_evt_code_resolver)

__all__ = [
    "AppSettings",
    "DirectorySelectorDialog",
    "EventCodeWindow",
    "LineHandler",
    "LogWidget",
    "ParametersEditorDialog",
    "PreProcessFile",
    "Parameters",
    "apply_bp_calibration",
    "apply_rsp_source",
    "populate_tree",
]
