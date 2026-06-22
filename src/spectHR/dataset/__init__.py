# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""spectHR.dataset, file loaders and pre-processing for physiological recordings.

This package turns files on disk into a :class:`~spectHR.session.Session`:

* :mod:`spectHR.dataset.loaders`, one parser per file format (registered by
  extension; :func:`load` dispatches on the suffix).
* :mod:`spectHR.dataset.preprocessing`, loader-agnostic ``Session -> Session``
  conditioning (channel canonicalisation, ECG polarity, R-peak detection,
  BP calibration, breath phases).

**The data model itself lives in** :mod:`spectHR.session` (``Samples``,
``Events``, ``Intervals``, ``Session``, ``Epoch``, ``AnalysisConfig``,
``MetricsTable``).  They are re-exported here only as a convenience for callers
that ``import spectHR.dataset`` for both the loaders and the types; ``session``
is their single home.
"""
from spectHR.dataset.loaders import load, register_loader
from spectHR.session import (
    AnalysisConfig,
    Epoch,
    Events,
    Intervals,
    MetricsTable,
    Samples,
    Session,
)

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
