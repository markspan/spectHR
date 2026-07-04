# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Dock layout declarations for the main window.

Pure, declarative configuration extracted from ``MainWindow`` so the window
class is left with wiring, not layout tables:

* the ``DOCK_*`` object-name constants,
* :data:`CENTRE_DOCKS` (order + title of the tabified centre docks),
* :data:`VIEW_LABELS` (View-menu labels),
* :data:`DOCK_REQUIRES` (per-dock "needs this channel to be meaningful"),
* :func:`build_data_specs` (which docks are live and what each derives from),
* the :class:`Placeholder` widget for docks without a real widget yet.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from spectHR.session import Session
from spectUI.coordinator import DataChange


# ---------------------------------------------------------------------------
# Dock object-name constants
# ---------------------------------------------------------------------------

DOCK_WORKSPACE       = "dock.workspace"
DOCK_PREPROCESSING   = "dock.preprocessing"
DOCK_HR              = "dock.hr"
DOCK_BP              = "dock.bp"
DOCK_POINCARE        = "dock.poincare"
DOCK_EPOCHS          = "dock.epochs"
DOCK_PSD             = "dock.psd"
DOCK_SPECTROGRAM     = "dock.spectrogram"
DOCK_SPECTROGRAM3D   = "dock.spectrogram3d"
DOCK_TRANSFER        = "dock.transfer"
DOCK_TRANSFERPROFILE = "dock.transferprofile"
DOCK_PROFILES        = "dock.profiles"
DOCK_RESULTS         = "dock.results"
DOCK_LOG             = "dock.log"


#: Centre docks, in tab order: ``(object_name, title)``.
CENTRE_DOCKS: tuple[tuple[str, str], ...] = (
    (DOCK_PREPROCESSING,   "Preprocessing"),
    (DOCK_HR,              "HR Series"),
    (DOCK_BP,              "Blood Pressure"),
    (DOCK_POINCARE,        "Poincaré"),
    (DOCK_EPOCHS,          "Epochs"),
    (DOCK_PSD,             "PSD"),
    (DOCK_SPECTROGRAM,     "Spectrogram"),
    (DOCK_SPECTROGRAM3D,   "Spectrogram 3D"),
    (DOCK_TRANSFER,        "Transfer"),
    (DOCK_TRANSFERPROFILE, "Transfer Profile"),
    (DOCK_PROFILES,        "Profiles"),
    (DOCK_RESULTS,         "Results"),
)


#: View-menu label for every dock (including the workspace + log docks).
VIEW_LABELS: dict[str, str] = {
    DOCK_WORKSPACE:       "Workspace",
    DOCK_PREPROCESSING:   "Preprocessing",
    DOCK_HR:              "HR Series",
    DOCK_BP:              "Blood Pressure",
    DOCK_POINCARE:        "Poincaré",
    DOCK_EPOCHS:          "Epochs",
    DOCK_PSD:             "PSD",
    DOCK_SPECTROGRAM:     "Spectrogram",
    DOCK_SPECTROGRAM3D:   "Spectrogram 3D",
    DOCK_TRANSFER:        "Transfer",
    DOCK_TRANSFERPROFILE: "Transfer Profile",
    DOCK_PROFILES:        "Profiles",
    DOCK_RESULTS:         "Results",
    DOCK_LOG:             "Log",
}


#: Docks that need a particular source channel to be meaningful.  When the
#: predicate is False for the loaded session the dock is hidden and its
#: View-menu entry greyed out.  Docks not listed here are always available
#: (they derive from the R-peaks, which every loaded session has).
DOCK_REQUIRES: dict[str, Callable[[Session], bool]] = {
    DOCK_BP:              lambda s: s.bp is not None,
    DOCK_TRANSFER:        lambda s: s.resp is not None or s.bp is not None,
    DOCK_TRANSFERPROFILE: lambda s: s.resp is not None or s.bp is not None,
}


def build_data_specs() -> dict[str, tuple[Callable[[], QWidget], DataChange]]:
    """Return ``{object_name: (widget_factory, depends)}`` for the live docks.

    A *live* dock takes a ``Session`` and repaints when its declared
    :class:`~spectUI.coordinator.DataChange` dependencies change; docks not in
    this mapping stay :class:`Placeholder` stubs.  The heavy spectral docks all
    derive from the R-peaks, the epoch table and the analysis parameters.

    Widget classes are imported lazily so importing this module stays cheap and
    free of a hard dependency cycle through the widget package.
    """
    from spectUI.widgets import (
        BPSeriesWidget,
        EpochEditorWidget,
        HRSeriesWidget,
        PoincareWidget,
        PrepPlotWidget,
        ProfilePlotWidget,
        PSDPlotWidget,
        ResultsTableWidget,
        Spectrogram3DPlotWidget,
        SpectrogramPlotWidget,
        TransferPlotWidget,
        TransferProfilePlotWidget,
    )

    heavy = DataChange.HRV | DataChange.EPOCHS | DataChange.PARAMS
    return {
        DOCK_PREPROCESSING:    (PrepPlotWidget, heavy),
        DOCK_HR:               (HRSeriesWidget, DataChange.HRV | DataChange.EPOCHS),
        DOCK_BP:               (BPSeriesWidget, DataChange.BP | DataChange.EPOCHS),
        DOCK_POINCARE:         (PoincareWidget, DataChange.HRV | DataChange.EPOCHS),
        DOCK_EPOCHS:           (EpochEditorWidget, DataChange.HRV | DataChange.EPOCHS),
        DOCK_PSD:              (PSDPlotWidget, heavy),
        DOCK_PROFILES:         (ProfilePlotWidget, heavy),
        DOCK_SPECTROGRAM:      (SpectrogramPlotWidget, heavy | DataChange.RESP),
        DOCK_SPECTROGRAM3D:    (Spectrogram3DPlotWidget, heavy | DataChange.RESP),
        DOCK_TRANSFER:         (TransferPlotWidget, heavy | DataChange.BP | DataChange.RESP),
        DOCK_TRANSFERPROFILE:  (TransferProfilePlotWidget, heavy | DataChange.BP | DataChange.RESP),
        DOCK_RESULTS:          (ResultsTableWidget, DataChange.ALL),
    }


class Placeholder(QWidget):
    """Grey centred label shown for a dock whose real widget is not built yet."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lbl = QLabel(name)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#bbb; font-size:16pt;")
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)
        self.setStyleSheet("background:#f8f8f8;")
