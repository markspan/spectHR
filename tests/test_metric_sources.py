# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Metric help links: column -> function resolution, GitHub URLs, and the
auto-generated README metric reference staying in sync with the registry.
"""
from __future__ import annotations

import inspect

import pytest

from spectHR.analysis import _docgen
from spectHR.analysis import sources as S
from spectHR.analysis.registry import get_metric_groups, get_metrics


def test_resolve_single_group_and_dynamic_columns():
    assert S.resolve_metric_function("rmssd")[0] == "rmssd"
    assert S.resolve_metric_function("band_powers")[0] == "band_powers"
    # Data-driven columns resolve back to the emitting group.
    assert S.resolve_metric_function("lf_power")[0] == "band_powers"
    assert S.resolve_metric_function("vlf_pct")[0] == "band_rel"
    assert S.resolve_metric_function("hf_peak_hz")[0] == "band_peak"
    assert S.resolve_metric_function("lf_tf_modulus")[0] == "transfer_band_metrics"
    assert S.resolve_metric_function("not_a_metric") is None


def test_source_location_points_at_the_function():
    # rmssd is inline, so its location is the function itself.
    rel, start, end = S.metric_source_location("rmssd")
    assert rel == "src/spectHR/analysis/ecg_metrics.py"
    assert start <= end
    fn = get_metrics()["rmssd"]
    _, def_line = inspect.getsourcelines(fn)
    assert start == def_line


def test_algorithm_chain_follows_wrappers_to_the_maths():
    # Thin wrappers resolve through to the function that does the computation.
    assert [n for n, _ in S.metric_algorithm_chain("bp_sbp")] == [
        "bp_sbp", "_bp_metric", "bp_beat_parameters",
    ]
    assert [n for n, _ in S.metric_algorithm_chain("pep")][-1] == "pep_ensemble"
    assert [n for n, _ in S.metric_algorithm_chain("dfa_a2")][-1] == "dfa_alpha1"
    assert [n for n, _ in S.metric_algorithm_chain("band_powers")][-1] == (
        "band_power_rectangular"
    )


def test_inline_metrics_resolve_to_themselves():
    for name in ("sdnn", "rmssd", "csi", "lf_nu", "tinn"):
        assert [n for n, _ in S.metric_algorithm_chain(name)] == [name]


def test_source_url_targets_the_algorithm_not_the_wrapper():
    # bp_sbp's wrapper lives in bp_metrics; its algorithm is bp_beat_parameters,
    # also in bp_metrics, but at the line range of that function.
    loc = S.metric_source_location("bp_sbp")
    import inspect as _inspect
    from spectHR.analysis.bp_metrics import bp_beat_parameters
    _, def_line = _inspect.getsourcelines(bp_beat_parameters)
    assert loc[0] == "src/spectHR/analysis/bp_metrics.py"
    assert loc[1] == def_line


def test_github_base_from_origin_remote():
    base = S.github_base()
    assert base == "https://github.com/markspan/spectHR"
    assert not base.endswith(".git")


def test_url_builders_format():
    src = S.metric_source_url("csi")
    doc = S.metric_doc_url("csi")
    assert src.startswith("https://github.com/markspan/spectHR/blob/V2/")
    assert "ecg_metrics.py#L" in src
    assert doc.endswith("/src/spectHR/analysis/README.md#csi")


def test_normalise_ssh_remote():
    assert S._normalise_remote("git@github.com:markspan/spectHR.git") == (
        "https://github.com/markspan/spectHR"
    )


def test_every_registered_metric_resolves_and_has_links():
    names = {**get_metrics(), **get_metric_groups()}
    for name in names:
        assert S.resolve_metric_function(name) is not None
        assert S.metric_doc_url(name) is not None
        assert S.metric_source_url(name) is not None


# ---------------------------------------------------------------------------
# README metric reference stays in sync with the registry
# ---------------------------------------------------------------------------

def _readme_text():
    root = S.repo_root()
    assert root is not None
    return (root / S.ANALYSIS_README).read_text(encoding="utf-8")


def test_readme_metric_reference_in_sync():
    current = _docgen.extract_section(_readme_text())
    assert current is not None, "metric-reference markers missing from README"
    assert current.strip() == _docgen.render_section().strip(), (
        "analysis/README.md metric reference is stale; "
        "run `python -m spectHR.analysis._docgen` to regenerate it"
    )


def test_readme_has_an_anchor_per_metric():
    text = _readme_text()
    for name in {**get_metrics(), **get_metric_groups()}:
        assert f"### {name}\n" in text, f"no README anchor for metric {name!r}"
