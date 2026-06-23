# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Offscreen tests for the Results metric help links (``spectUI.metric_links``).

Runs in a fresh subprocess (Qt must not enter the shared pytest process, per
``test_headless_imports``; importing ``spectUI`` pulls Qt).  Covers column ->
function resolution, the wrapper-to-algorithm call chain, the GitHub URLs, the
description link still working with no checkout (the compiled-build case, where
the source link is absent), and the README reference staying in sync with the
registry.
"""
from __future__ import annotations

import os
import subprocess
import sys

_DRIVER = r"""
import inspect

import spectUI.metric_links as ML
from spectUI import metric_docgen as DG
from spectHR.analysis.registry import get_metric_groups, get_metrics

names = {**get_metrics(), **get_metric_groups()}

# --- column -> function resolution (singles, groups, dynamic columns) -------
assert ML.resolve_metric_function("rmssd")[0] == "rmssd"
assert ML.resolve_metric_function("band_powers")[0] == "band_powers"
assert ML.resolve_metric_function("lf_power")[0] == "band_powers"
assert ML.resolve_metric_function("vlf_pct")[0] == "band_rel"
assert ML.resolve_metric_function("hf_peak_hz")[0] == "band_peak"
assert ML.resolve_metric_function("lf_tf_modulus")[0] == "transfer_band_metrics"
assert ML.resolve_metric_function("not_a_metric") is None

# --- inline metric: location is the function itself ------------------------
rel, start, end = ML.metric_source_location("rmssd")
assert rel == "src/spectHR/analysis/ecg_metrics.py"
_, def_line = inspect.getsourcelines(get_metrics()["rmssd"])
assert start == def_line

# --- thin wrappers resolve through to the maths ----------------------------
assert [n for n, _ in ML.metric_algorithm_chain("bp_sbp")] == [
    "bp_sbp", "_bp_metric", "bp_beat_parameters"]
assert [n for n, _ in ML.metric_algorithm_chain("pep")][-1] == "pep_ensemble"
assert [n for n, _ in ML.metric_algorithm_chain("dfa_a2")][-1] == "dfa_alpha1"
assert [n for n, _ in ML.metric_algorithm_chain("band_powers")][-1] == (
    "band_power_rectangular")
for name in ("sdnn", "rmssd", "csi", "lf_nu", "tinn"):
    assert [n for n, _ in ML.metric_algorithm_chain(name)] == [name]

# --- URLs ------------------------------------------------------------------
assert ML.github_base() == "https://github.com/markspan/spectHR"
src = ML.metric_source_url("csi")
assert src.startswith("https://github.com/markspan/spectHR/blob/V2/")
assert "ecg_metrics.py#L" in src
assert ML.metric_doc_url("csi").endswith("/src/spectHR/analysis/README.md#csi")
assert ML._normalise_remote("git@github.com:markspan/spectHR.git") == (
    "https://github.com/markspan/spectHR")

# source URL targets the algorithm, not the wrapper
from spectHR.analysis.bp_metrics import bp_beat_parameters
loc = ML.metric_source_location("bp_sbp")
_, algo_line = inspect.getsourcelines(bp_beat_parameters)
assert loc[0] == "src/spectHR/analysis/bp_metrics.py" and loc[1] == algo_line

# every registered metric resolves and yields both links
for name in names:
    assert ML.resolve_metric_function(name) is not None
    assert ML.metric_doc_url(name) is not None
    assert ML.metric_source_url(name) is not None

# --- README reference in sync with the registry ----------------------------
root = ML.repo_root()
readme = (root / ML.ANALYSIS_README).read_text(encoding="utf-8")
assert DG.extract_section(readme) is not None, "README markers missing"
assert DG.extract_section(readme).strip() == DG.render_section().strip(), (
    "analysis/README.md metric reference is stale; "
    "run `python -m spectUI.metric_docgen`")
for name in names:
    assert ("### %s\n" % name) in readme, name

# --- compiled build: no checkout, compiled modules (no live source) --------
# The source link is best-effort and simply absent there; the description link
# keeps working, so the Results menu still has its one entry.
ML.repo_root = lambda: None
ML._ast_of = lambda fn: None
ML.github_base.cache_clear()
assert ML.metric_source_url("bp_sbp") is None
assert ML.metric_doc_url("bp_sbp").endswith("README.md#bp_sbp")

print("LINKS_OK")
"""


def test_metric_links_offscreen():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0 and "LINKS_OK" in proc.stdout, (
        f"metric-links checks failed\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
