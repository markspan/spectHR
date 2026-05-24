# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/__init__.py
"""
spectHR.analysis - standalone HRV analysis functions.

Importing this package populates the metric registry with all built-in
time- and frequency-domain metrics.  Any function decorated with
``@hrv_metric`` is then automatically discovered by
``CardioSeries.metric_table()`` and ``PhysioData.hrv_epoch_table()``.

Direct usage
------------
>>> import spectHR.analysis as hrv
>>> hrv.rmssd(series)        # call a metric directly
>>> hrv.get_metrics()        # {name: fn} dict of all registered metrics

Lazy access via the series object
----------------------------------
>>> series.rmssd()           # CardioMetricsMixin.__getattr__ dispatches here
>>> series.metric_table()    # computes all registered metrics on the series
"""

from spectHR.analysis.registry import hrv_metric, get_metrics

# Importing the metric submodules populates _REGISTRY as a side effect.
# They are imported here - not at the top of CardioMetricsMixin - so that
# CardioSeries / CardioSeriesView carry zero analysis weight at module load
# time.  The registry is filled on first access to spectHR.analysis.
from spectHR.analysis import time_metrics       # noqa: F401
from spectHR.analysis import frequency_metrics  # noqa: F401

__all__ = [
    "hrv_metric",
    "get_metrics",
    # Metric submodules are importable but not re-exported by name here;
    # call them as hrv.time_metrics.rmssd if you need the raw function.
]
