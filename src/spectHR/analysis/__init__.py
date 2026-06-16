# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/__init__.py
"""
spectHR.analysis - standalone HRV analysis functions.

Importing this package populates the metric registry with every built-in
per-epoch parameter: time-domain HRV metrics, the standard band powers, and
the beat-by-beat blood-pressure / respiration parameters. Any function
decorated with ``@epoch_metric`` is then automatically discovered by
``Session.epochs_table()``.

Direct usage
------------
>>> import spectHR.analysis as hrv
>>> hrv.rmssd(series)        # call a metric directly
>>> hrv.get_metrics()        # {name: fn} dict of all registered metrics
"""

from spectHR.analysis.registry import (
    epoch_metric,
    epoch_metric_group,
    get_metrics,
    get_metric_groups,
)

# Importing the metric submodules populates _REGISTRY as a side effect.
# The registry is filled on first access to spectHR.analysis.
from spectHR.analysis import time_metrics       # noqa: F401
from spectHR.analysis import frequency_metrics  # noqa: F401
from spectHR.analysis import bp_metrics         # noqa: F401
from spectHR.analysis import nonlinear          # noqa: F401  (dfa_a1)
from spectHR.analysis import respiration_metrics  # noqa: F401  (resp_freq, hf_resp_in_band)
from spectHR.analysis import icg_metrics        # noqa: F401  (pep)
from spectHR.analysis import transfer_metrics   # noqa: F401  (transfer_band_metrics)
from spectHR.analysis import prsa_metrics       # noqa: F401  (dc, ac)

__all__ = [
    "epoch_metric",
    "epoch_metric_group",
    "get_metrics",
    "get_metric_groups",
    # Metric submodules are importable but not re-exported by name here;
    # call them as hrv.time_metrics.rmssd if you need the raw function.
]
