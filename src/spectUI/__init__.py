# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from spectUI.common import LineHandler
from spectUI.preProcessFile import (
    PreProcessFile,
    apply_beat_detection,
    apply_bp_calibration,
    apply_rsp_source,
)
from spectUI.widgets import (
    DirectorySelectorDialog,
    EventCodeWindow,
    LogWidget,
    ParametersEditorDialog,
)
from spectUI.parameters import Parameters, populate_tree
from spectUI.settings import AppSettings
from spectHR.DataSet.loaders.code_selection import register_code_resolver
from spectUI.gui_invoke import run_in_gui_thread


def _evt_code_resolver(other_codes, rtop_code):
    """Dialog-backed resolver for the headless ``.evt`` loader hook.

    File loading runs on a worker ``QThread``, but Qt dialogs may only be
    created on the GUI thread — so the dialog is marshalled there via
    :func:`~spectUI.gui_invoke.run_in_gui_thread`, which blocks the
    loader until the user has chosen the start/stop codes.
    """
    # Materialise before crossing threads: numpy views may reference
    # loader-thread state.
    codes = [int(c) for c in other_codes]

    def ask() -> tuple[list[int], list[int]]:
        window = EventCodeWindow(codes, ignore=rtop_code)
        window.exec()
        return window.start_codes, window.stop_codes

    return run_in_gui_thread(ask)


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
    "apply_beat_detection",
    "apply_bp_calibration",
    "apply_rsp_source",
    "populate_tree",
    "run_in_gui_thread",
]
