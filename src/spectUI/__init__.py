# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectUI/__init__.py
from spectUI.common import LineHandler
from spectUI.preProcessFile import PreProcessFile, apply_bp_calibration
from spectUI.widgets import (
    BPPlotWidget,
    DirectorySelectorDialog,
    EpochPlotWidget,
    EventCodeWindow,
    HRPlotWidget,
    ParametersEditorDialog,
    ParametersPlotWidget,
    PoincarePlotWidget,
    PrepPlotWidget,
    PSDPlotWidget,
    ProfilePlotWidget,
    Spectrogram3DPlotWidget,
    SpectrogramPlotWidget,
    TransferPlotWidget,
    TransferProfilePlotWidget,
)
from spectUI.workSpace import (
    LoadWorkspace,
    PopulateTree,
    SaveWorkspace,
    WorkspaceConfig,
    display_bands_from_workspace,
    log_level_from_workspace,
    psd_method_from_workspace,
    resolved_profile_bands,
    transfer_settings_from_workspace,
)
from spectHR.DataSet.loaders.code_selection import register_code_resolver


def _evt_code_resolver(other_codes, rtop_code):
    """Dialog-backed resolver for the headless ``.evt`` loader hook.

    Pops the :class:`EventCodeWindow` so the researcher can pick which
    event codes mark epoch starts/stops, then returns the selection.
    Registering this on import keeps ``spectHR`` itself UI-free.
    """
    window = EventCodeWindow(other_codes, ignore=rtop_code)
    window.exec()
    return window.start_codes, window.stop_codes


register_code_resolver(_evt_code_resolver)

__all__ = [
    "BPPlotWidget",
    "DirectorySelectorDialog",
    "EpochPlotWidget",
    "EventCodeWindow",
    "HRPlotWidget",
    "LineHandler",
    "LoadWorkspace",
    "ParametersEditorDialog",
    "ParametersPlotWidget",
    "PoincarePlotWidget",
    "PopulateTree",
    "PreProcessFile",
    "apply_bp_calibration",
    "PrepPlotWidget",
    "PSDPlotWidget",
    "ProfilePlotWidget",
    "SaveWorkspace",
    "Spectrogram3DPlotWidget",
    "SpectrogramPlotWidget",
    "TransferPlotWidget",
    "TransferProfilePlotWidget",
    "display_bands_from_workspace",
    "log_level_from_workspace",
    "psd_method_from_workspace",
    "resolved_profile_bands",
    "transfer_settings_from_workspace",
    "WorkspaceConfig",
]
