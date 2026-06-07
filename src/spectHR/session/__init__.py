# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectHR.session — modern physiological data layer.

Public surface
--------------
Data primitives (immutable, read-only arrays)::

    Signal, SignalSlice
    Beats, BeatSlice
    BreathPhases, PhaseSlice

Session layer::

    Epoch, AnalysisConfig, EpochsResult
    PhysioSession

Bridge::

    PhysioSession.from_physio_data(pd)   # wrap legacy PhysioData

Protocols (for type annotations)::

    SignalLike, BeatLike, PhaseLike
"""
from spectHR.session._data import (
    Signal,
    SignalSlice,
    Beats,
    BeatSlice,
    BreathPhases,
    PhaseSlice,
    SignalLike,
    BeatLike,
    PhaseLike,
)
from spectHR.session._session import (
    Epoch,
    AnalysisConfig,
    EpochsResult,
    PhysioSession,
)

__all__ = [
    # data primitives
    "Signal",
    "SignalSlice",
    "Beats",
    "BeatSlice",
    "BreathPhases",
    "PhaseSlice",
    # protocols
    "SignalLike",
    "BeatLike",
    "PhaseLike",
    # session
    "Epoch",
    "AnalysisConfig",
    "EpochsResult",
    "PhysioSession",
]
