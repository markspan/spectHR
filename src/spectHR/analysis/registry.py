# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/registry.py
"""
HRV metric registry.

Functions decorated with ``@hrv_metric`` are stored here and discovered
automatically by ``PhysioData.hrv_epoch_table()``.

The registry is a plain module-level dict; there is no base class
requirement. New metrics are added simply by decorating a standalone
function.
"""
from __future__ import annotations

from typing import Callable, Dict

_REGISTRY: Dict[str, Callable] = {}


def hrv_metric(func: Callable) -> Callable:
    """Register *func* as an HRV metric.

    The decorated function must accept a single positional argument - a
    ``CardioSeriesLike`` - and return a value coercible to ``float``.

    Registration happens at import time; importing ``spectHR.analysis``
    before the first metric call is enough to populate the registry.

    Example
    -------
    >>> from spectHR.analysis.registry import hrv_metric
    >>> @hrv_metric
    ... def my_metric(series) -> float:
    ...     return float(series.ibi.mean())
    """
    _REGISTRY[func.__name__] = func
    func._is_hrv_metric = True
    return func


def get_metrics() -> Dict[str, Callable]:
    """Return a snapshot of the current metric registry (``name → function``)."""
    return dict(_REGISTRY)
