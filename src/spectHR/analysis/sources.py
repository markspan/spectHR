# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/sources.py
"""
Where a Results column comes from: docstring anchor and source-code location.

The Results dock lets the analyst right-click a column header to open the
metric's *description* (the anchored section in
:doc:`analysis/README.md <README>`) and its *implementation* (the exact lines of
the decorated function on GitHub).  Both links are built here, in the headless
library, so the UI only has to open the URL.

Two design points keep the links honest with zero hand-maintenance:

* The registry holds the live function objects, so :func:`inspect.getsourcelines`
  yields the function's current line range every launch; the "view source" link
  therefore never drifts, even as code moves.
* Data-driven group columns (``lf_power``, ``vlf_pct``, ``lf_tf_modulus``, ...)
  have no single function of their own, so :func:`resolve_metric_function` maps
  them back to the ``@epoch_metric_group`` that emits them.

The GitHub base URL is parsed from the repository's ``origin`` remote when the
package is run from a checkout, falling back to the canonical project URL.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Optional

from spectHR.analysis.registry import get_metric_groups, get_metrics

#: Canonical project URL, used when the origin remote cannot be read (e.g. the
#: package was pip-installed rather than run from a git checkout).
DEFAULT_GITHUB_BASE = "https://github.com/markspan/spectHR"

#: Branch the help links point at (PRs target V2; it is the working reference).
DEFAULT_REF = "V2"

#: Path of the metric-reference document, relative to the repository root.
ANALYSIS_README = "src/spectHR/analysis/README.md"

# Suffix -> emitting group, for the data-driven columns that have no single
# function of their own.  Mirrors the suffix lookups the Results tooltips use.
_GROUP_SUFFIXES = {
    "_power": "band_powers",
    "_pct": "band_rel",
    "_peak_hz": "band_peak",
    "_tf_modulus": "transfer_band_metrics",
    "_tf_coherence": "transfer_band_metrics",
    "_tf_phase_w": "transfer_band_metrics",
}


def resolve_metric_function(column: str):
    """Return ``(name, function)`` for a Results column, or ``None``.

    *column* may be a single metric name, a group name, or one of the
    data-driven columns a group emits (resolved back to that group via its
    suffix).  *name* is the function's ``__name__``, which is also its
    README heading anchor.
    """
    singles = get_metrics()
    if column in singles:
        return column, singles[column]
    groups = get_metric_groups()
    if column in groups:
        return column, groups[column]
    for suffix, gname in _GROUP_SUFFIXES.items():
        if column.endswith(suffix) and gname in groups:
            return gname, groups[gname]
    return None


@lru_cache(maxsize=1)
def repo_root() -> Optional[Path]:
    """The repository root (nearest ancestor with ``pyproject.toml`` / ``.git``)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return None


def _normalise_remote(url: str) -> str:
    """Turn an SSH or HTTPS git remote into a browsable ``https://`` base URL."""
    url = url.strip()
    if url.startswith("git@"):  # git@github.com:owner/repo.git
        host, _, path = url[4:].partition(":")
        url = f"https://{host}/{path}"
    if url.endswith(".git"):
        url = url[:-4]
    return url


@lru_cache(maxsize=1)
def github_base() -> str:
    """Base GitHub URL for the project, from the ``origin`` remote or the default."""
    root = repo_root()
    if root is not None:
        cfg = root / ".git" / "config"
        try:
            text = cfg.read_text(encoding="utf-8")
        except OSError:
            text = ""
        in_origin = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                in_origin = stripped == '[remote "origin"]'
            elif in_origin and stripped.startswith("url"):
                _, _, value = stripped.partition("=")
                if value.strip():
                    return _normalise_remote(value)
    return DEFAULT_GITHUB_BASE


# ---------------------------------------------------------------------------
# Following a metric to its "real algorithm"
#
# Most registered metrics are thin wrappers: they read a cached intermediate off
# the EpochContext or delegate to a helper, and the actual maths lives one or two
# hops away.  resolve_algorithm follows a metric *while it is a pure pass-through*
# (no arithmetic of its own, exactly one non-trivial callee) until it reaches the
# function that does the real computation, so the "view source" link lands on the
# algorithm rather than on `return _bp_metric(ctx, "sbp")`.
# ---------------------------------------------------------------------------

# Plumbing helpers that are never "the algorithm": IBI cleaning, PSD-method
# resolution and the generic per-beat aggregators.  Following into these would
# point at boilerplate, so they are skipped when choosing the next hop.
_TRIVIAL_HELPERS = frozenset({
    "ibi_clean_ms",
    "successive_diffs_ms",
    "_resolve_method",
    "nanmean",
    "median_dt",
    "rpeak_sample_indices",
})

# EpochContext cached-properties bridge a metric to the function that fills them.
# Reading ``ctx.bp_beats`` is, algorithmically, a call to ``bp_beat_parameters``.
_CTX_BRIDGE = {
    "bp_beats": ("spectHR.analysis.bp_metrics", "bp_beat_parameters"),
    "resp_beats": ("spectHR.analysis.respiration_metrics", "resp_beat_parameters"),
    "rsa_beats": ("spectHR.analysis.respiration_metrics", "grossman_rsa_per_breath"),
    "pep_detail": ("spectHR.analysis.icg_metrics", "pep_ensemble"),
    "pep_value": ("spectHR.analysis.icg_metrics", "pep_ensemble"),
    "transfer_result": ("spectHR.analysis.transfer", "compute_transfer"),
}

_MAX_CHAIN = 6  # depth guard; the real chains are 1-3 hops


def _bridge_function(attr: str):
    spec = _CTX_BRIDGE.get(attr)
    if spec is None:
        return None
    try:
        return getattr(importlib.import_module(spec[0]), spec[1], None)
    except ImportError:
        return None


def _ast_of(fn) -> Optional[ast.AST]:
    try:
        return ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return None


def _has_arithmetic(fn) -> bool:
    """True when *fn* does arithmetic of its own (so it *is* an algorithm)."""
    tree = _ast_of(fn)
    if tree is None:
        return True  # cannot see the source, treat as a terminal
    return any(isinstance(node, ast.BinOp) for node in ast.walk(tree))


def _in_package(obj) -> bool:
    return callable(obj) and getattr(obj, "__module__", "").startswith("spectHR")


def _next_hops(fn) -> list:
    """Non-trivial functions *fn* delegates to (direct calls + ctx bridges)."""
    tree = _ast_of(fn)
    if tree is None:
        return []
    glb = getattr(fn, "__globals__", {})
    called: set[str] = set()
    ctx_attrs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
                if (node.func.id == "getattr" and len(node.args) >= 2
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id == "ctx"
                        and isinstance(node.args[1], ast.Constant)):
                    ctx_attrs.add(str(node.args[1].value))
        elif (isinstance(node, ast.Attribute)
              and isinstance(node.value, ast.Name) and node.value.id == "ctx"):
            ctx_attrs.add(node.attr)

    hops: list = []
    seen_ids: set[int] = set()
    for name in sorted(called):
        if name in _TRIVIAL_HELPERS:
            continue
        obj = glb.get(name)
        if _in_package(obj) and id(obj) not in seen_ids:
            seen_ids.add(id(obj))
            hops.append(obj)
    for attr in sorted(ctx_attrs):
        obj = _bridge_function(attr)
        if obj is not None and id(obj) not in seen_ids:
            seen_ids.add(id(obj))
            hops.append(obj)
    return hops


def resolve_algorithm(fn) -> list:
    """The wrapper-to-algorithm chain for *fn* (``[fn]`` when it is inline).

    Follows *fn* while it is a pure pass-through (no arithmetic, exactly one
    non-trivial hop), stopping at the first function that computes something
    itself or that branches to several callees.  The last element is the
    function the "view source" link should open.
    """
    chain = [fn]
    seen = {id(fn)}
    cur = fn
    for _ in range(_MAX_CHAIN):
        if _has_arithmetic(cur):
            break
        hops = [h for h in _next_hops(cur) if id(h) not in seen]
        if len(hops) != 1:
            break
        cur = hops[0]
        seen.add(id(cur))
        chain.append(cur)
    return chain


def metric_algorithm_chain(column: str) -> Optional[list]:
    """``[(name, function), ...]`` from the metric wrapper to its algorithm."""
    resolved = resolve_metric_function(column)
    if resolved is None:
        return None
    return [(fn.__name__, fn) for fn in resolve_algorithm(resolved[1])]


def _function_location(fn):
    """``(relpath, line_start, line_end)`` for *fn*, or ``None``."""
    root = repo_root()
    if root is None:
        return None
    try:
        source_file = Path(inspect.getsourcefile(fn)).resolve()
        lines, start = inspect.getsourcelines(fn)
    except (OSError, TypeError):
        return None
    try:
        rel = source_file.relative_to(root).as_posix()
    except ValueError:
        return None
    return rel, start, start + len(lines) - 1


def metric_source_location(column: str):
    """``(relpath, line_start, line_end)`` of the column's **real algorithm**.

    The metric is followed through its wrapper(s) to the function that does the
    computation (see :func:`resolve_algorithm`).  *relpath* is POSIX, relative
    to the repository root; line numbers are read live, so they never drift.
    """
    chain = metric_algorithm_chain(column)
    if not chain:
        return None
    return _function_location(chain[-1][1])


def metric_source_url(column: str, ref: str = DEFAULT_REF) -> Optional[str]:
    """GitHub blob URL pointing at the exact lines of the column's algorithm."""
    loc = metric_source_location(column)
    if loc is None:
        return None
    rel, start, end = loc
    return f"{github_base()}/blob/{ref}/{rel}#L{start}-L{end}"


def metric_doc_url(column: str, ref: str = DEFAULT_REF) -> Optional[str]:
    """GitHub URL of the column's anchored section in the metric-reference README."""
    resolved = resolve_metric_function(column)
    if resolved is None:
        return None
    anchor = resolved[0]  # function/group name == README heading slug
    return f"{github_base()}/blob/{ref}/{ANALYSIS_README}#{anchor}"
