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
>>> hrv.get_metrics()              # {name: fn} dict of all registered metrics
>>> hrv.ecg_metrics.rmssd(series)  # call a metric from its module

Metrics are not re-exported at the package root; reach them through their
module (``hrv.ecg_metrics.rmssd``, ``hrv.bp_metrics.bp_sbp``, ...) or look them
up by name via :func:`get_metrics`.
"""

# Importing the metric submodules populates _REGISTRY as a side effect. The
# registry is filled on first access to spectHR.analysis; one submodule per
# series type (see analysis/README.md for the full map).
#
# The import order is also the *column order* of the results table and the CSV
# export (registration order). It is deliberate, not alphabetical: blood
# pressure sits just before the ICG/PEP block, so the table reads
#   epoch | HRV time/frequency (ecg) | blood pressure | PEP (icg) | resp | transfer
# Keep this order; isort is turned off for the block so it is not re-sorted.
# isort: off
from spectHR.analysis import (
    ecg_metrics,          # noqa: F401  (IBI/HRV: time, Poincaré, DFA, PRSA, band powers)
    bp_metrics,           # noqa: F401  (bp_sbp/dbp/pp/map, sbp_sd/dbp_sd)
    icg_metrics,          # noqa: F401  (pep, pep_b/c/q_ms, pep_n_beats, heather_index)
    respiration_metrics,  # noqa: F401  (resp_freq, hf_resp_in_band, resp_mvo/svo, rsa/rsa0)
    transfer_metrics,     # noqa: F401  (transfer_band_metrics)
)
# isort: on
from spectHR.analysis.registry import (
    epoch_metric,
    epoch_metric_group,
    get_metric_groups,
    get_metrics,
)

__all__ = [
    "epoch_metric",
    "epoch_metric_group",
    "get_metrics",
    "get_metric_groups",
    # Metric submodules are importable but not re-exported by name here;
    # call them as hrv.ecg_metrics.rmssd if you need the raw function.
]
