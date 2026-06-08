# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""spectHR.DataSet — physiological data primitives and file loaders.

The data model is built on three immutable primitives:

    Samples    — continuous 1-D waveform (ECG, respiration, blood pressure)
    Events     — point process with categorical labels (R-peaks, triggers)
    Intervals  — labelled non-overlapping segments (INH/EXH breath phases)

They are composed into a :class:`Session` which is the root container for
one physiological recording.  File I/O goes through :func:`load`.
"""
from spectHR.session import (
    Samples,
    Events,
    Intervals,
    Epoch,
    Session,
    AnalysisConfig,
    MetricsTable,
)
from spectHR.DataSet.loaders import load, register_loader

__all__ = [
    "Samples",
    "Events",
    "Intervals",
    "Epoch",
    "Session",
    "AnalysisConfig",
    "MetricsTable",
    "load",
    "register_loader",
]
