# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Metric registration order = results / export column order.

The blood-pressure metrics must sit just before the ICG/PEP block: after the
HRV (ecg) metrics and before ``pep``.  This is set by the import order in
``spectHR.analysis.__init__`` (protected from isort re-sorting).
"""
from __future__ import annotations

from spectHR.analysis import get_metrics


def test_bp_columns_sit_between_hrv_and_pep():
    names = list(get_metrics())
    for col in ("rmssd", "bp_sbp", "pep"):
        assert col in names, f"{col} not registered"
    # ecg (rmssd) -> blood pressure (bp_sbp ... dbp_sd) -> icg (pep)
    assert names.index("rmssd") < names.index("bp_sbp") < names.index("pep")
    # the whole BP block is contiguous and ahead of pep
    bp_cols = [n for n in ("bp_sbp", "bp_dbp", "bp_pp", "bp_map", "sbp_sd", "dbp_sd")
               if n in names]
    assert bp_cols, "no BP metrics registered"
    assert max(names.index(n) for n in bp_cols) < names.index("pep")
