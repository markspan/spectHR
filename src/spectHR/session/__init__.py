# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectHR.session, modern physiological data layer.

Three immutable data primitives::

    Samples     continuous 1-D waveform (ECG, resp, BP, ICG)
    Events      point process with labels (R-peaks, markers)
    Intervals   labelled segments (INH/EXH phases, conditions)

All three support zero-copy ``obj.window(start, end)`` that returns the
same type, no separate slice class.

Session layer::

    Epoch           labelled time window
    AnalysisConfig  typed analysis parameters
    MetricsTable    structured result of epochs_table
    Session         root container; owns channels and epoch table

Protocols (for type annotations)::

    SamplesLike, EventsLike, IntervalsLike
"""
from spectHR.session._core import (
    Events,
    EventsLike,
    Intervals,
    IntervalsLike,
    Samples,
    SamplesLike,
)
from spectHR.session._session import (
    AnalysisConfig,
    Epoch,
    MetricsTable,
    Session,
)

__all__ = [
    "Samples",
    "Events",
    "Intervals",
    "SamplesLike",
    "EventsLike",
    "IntervalsLike",
    "Epoch",
    "AnalysisConfig",
    "MetricsTable",
    "Session",
]
