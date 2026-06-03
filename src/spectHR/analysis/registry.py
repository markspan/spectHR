# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/registry.py
"""
Epoch-metric registry.

Functions decorated with ``@epoch_metric`` are stored here and discovered
automatically by ``PhysioData.epoched_parameters_table()``.  Every registered
metric contributes exactly **one** scalar column to the parameters CSV — the
column name is the function's ``__name__``.

The decorator unifies every per-epoch parameter the table exports: the
time-domain HRV metrics (``rmssd``, ``sdnn`` …), the beat-by-beat
blood-pressure and respiration parameters (``bp_sbp`` …, ``resp_mvo`` …) and
the standard band powers (``lf_power`` …, ``lf_hf_ratio``).  A metric receives
a single positional argument — either a bare ``CardioSeriesLike`` (when called
directly) or an :class:`~spectHR.analysis.epoch_context.EpochContext` (when
called by the table), which exposes the same series interface plus the extra
channels and cached PSD that BP / RESP / band-power metrics need.

The registry is a plain module-level dict; there is no base class
requirement. New metrics are added simply by decorating a standalone
function.
"""
from __future__ import annotations

from typing import Callable, Dict

_REGISTRY: Dict[str, Callable] = {}


def epoch_metric(func: Callable) -> Callable:
    """Register *func* as a single-valued per-epoch metric.

    The decorated function must accept a single positional argument — a
    ``CardioSeriesLike`` or an
    :class:`~spectHR.analysis.epoch_context.EpochContext` — and return a value
    coercible to ``float``.  It must contribute exactly one column (one scalar)
    to the parameters table; a metric may never emit multiple columns.

    Registration happens at import time; importing ``spectHR.analysis``
    before the first metric call is enough to populate the registry.

    Raises
    ------
    ValueError
        If a metric with the same name is already registered, to prevent
        silent overwrites when two modules define a function with the
        same ``__name__``.

    Example
    -------
    >>> from spectHR.analysis.registry import epoch_metric
    >>> @epoch_metric
    ... def my_metric(series) -> float:
    ...     return float(series.ibi.mean())
    """
    name = func.__name__
    if name in _REGISTRY:
        raise ValueError(
            f"Epoch metric '{name}' is already registered. "
            "Rename the function or remove the duplicate @epoch_metric decorator."
        )
    _REGISTRY[name] = func
    return func


def get_metrics() -> Dict[str, Callable]:
    """Return a snapshot of the current metric registry (``name → function``)."""
    return dict(_REGISTRY)
