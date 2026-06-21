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

import inspect
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


def metric_source_location(column: str):
    """``(relpath, line_start, line_end)`` for the column's calculation, or ``None``.

    *relpath* is POSIX, relative to the repository root.  Line numbers are read
    live from the function object, so they always match the current source.
    """
    resolved = resolve_metric_function(column)
    root = repo_root()
    if resolved is None or root is None:
        return None
    _, fn = resolved
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


def metric_source_url(column: str, ref: str = DEFAULT_REF) -> Optional[str]:
    """GitHub blob URL pointing at the exact lines of the column's function."""
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
