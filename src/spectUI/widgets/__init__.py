# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectUI.widgets — the QWidget subclasses presented in the main window.

Ten plot widgets, one per dock in the centre area:

    PrepPlotWidget              ECG preprocessing view with R-peak editor.
    HRPlotWidget                IBI / heart-rate timeseries.
    EpochPlotWidget             Gantt-style epoch editor.
    PoincarePlotWidget          Poincaré scatter per epoch.
    PSDPlotWidget               Per-epoch PSD grid.
    SpectrogramPlotWidget       Per-epoch time-frequency heat map (2-D).
    Spectrogram3DPlotWidget     Per-epoch time-frequency surface (3-D).
    ProfilePlotWidget           Sliding-window band-power profiles.
    TransferPlotWidget          Per-epoch Bode plot, respiration → HR.
    TransferProfilePlotWidget   Time-resolved transfer-band statistics.
    ParametersPlotWidget        Numerical HRV parameters table.

Both spectrogram widgets share the same compute layer
(``_spectrogram_compute``) and read from the same ``Spectrogram``
workspace chapter, so they always show identical underlying data.

Plus two dialogs that the workspace editor relies on:

    DirectorySelectorDialog  Directories chapter editor.
    ParametersEditorDialog   Generic per-section parameters editor.

And one modal that ``spectHR.DataSet.loaders.evt_loader`` uses lazily
to disambiguate non-RTop event codes:

    EventCodeWindow.

Callers can import via this package, or directly from the relevant
submodule when only one symbol is needed.
"""
from __future__ import annotations

from spectUI.widgets.EventCodeWindow import EventCodeWindow
from spectUI.widgets.PSDPlotWidget import PSDPlotWidget
from spectUI.widgets.ProfilePlotWidget import ProfilePlotWidget
from spectUI.widgets.WorkSpaceEditor import (
    DirectorySelectorDialog,
    ParametersEditorDialog,
)
from spectUI.widgets.bpPlotWidget import BPPlotWidget
from spectUI.widgets.epochPlotWidget import EpochPlotWidget
from spectUI.widgets.hrPlotWidget import HRPlotWidget
from spectUI.widgets.parametersPlotWidget import ParametersPlotWidget
from spectUI.widgets.poincarePlotWidget import PoincarePlotWidget
from spectUI.widgets.prepPlotWidget import PrepPlotWidget
from spectUI.widgets.spectrogramPlotWidget import SpectrogramPlotWidget
from spectUI.widgets.spectrogram3dPlotWidget import Spectrogram3DPlotWidget
from spectUI.widgets.transferPlotWidget import TransferPlotWidget
from spectUI.widgets.transferProfilePlotWidget import TransferProfilePlotWidget

__all__ = [
    "BPPlotWidget",
    "DirectorySelectorDialog",
    "EpochPlotWidget",
    "EventCodeWindow",
    "HRPlotWidget",
    "ParametersEditorDialog",
    "ParametersPlotWidget",
    "PoincarePlotWidget",
    "PrepPlotWidget",
    "PSDPlotWidget",
    "ProfilePlotWidget",
    "Spectrogram3DPlotWidget",
    "SpectrogramPlotWidget",
    "TransferPlotWidget",
    "TransferProfilePlotWidget",
]
