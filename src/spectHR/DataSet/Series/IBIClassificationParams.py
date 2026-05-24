# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
IBIClassificationParams.py – Single source of truth for the IBI classifier
default parameters.

Three call sites need the same trio of knobs in step:

* ``CardioSeries.from_timeseries(...)``
* ``CardioSeries.replace_from_timeseries(...)``
* ``PhysioData.preprocess_ecg(...)``  → which forwards them to ``classify_ibi``.

Centralising the defaults in this module means a single edit propagates to
every entry point.  The dataclass also lets workspace loaders pass a single
``params`` object around without unpacking three positional arguments at
each hop.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IBIClassificationParams:
    """
    Parameters consumed by ``CardioSeries.classify_ibi``.

    Attributes
    ----------
    window_length : int
        Centered rolling-window size in beats; the local mean / std used to
        decide whether each interval is a Short / Normal / Long beat.
    n_std : float
        Width of the local acceptance band, in standard deviations.  Beats
        outside ``mean ± n_std × std`` are flagged as outliers.
    max_ibi_sec : float
        Absolute ceiling for an inter-beat interval, in seconds.  Anything
        longer is labelled ``"TL"`` (Too Long) and excluded from statistics.
    """

    window_length: int   = 51
    n_std:         float = 4.0
    max_ibi_sec:   float = 2.0

    def as_kwargs(self) -> dict:
        """Return the parameters as a kwargs dict for ``classify_ibi(**...)``."""
        return asdict(self)


# Module-level default - referenced by ``CardioSeries`` / ``PhysioData``
# as the source of every parameter default.  Keep this immutable so
# call-site defaults never accidentally drift.
DEFAULT_IBI_PARAMS = IBIClassificationParams()
