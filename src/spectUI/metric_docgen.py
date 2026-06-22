# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectUI/metric_docgen.py
"""
Generate the per-metric reference appendix in ``spectHR/analysis/README.md``.

Every registered metric gets an anchored ``### <name>`` section (so the Results
dock can deep-link a column header to ``README.md#<metric>``), carrying its
docstring, its wrapper-to-algorithm call chain, and a relative link to the
algorithm's source file.  The block omits line numbers so it stays stable as code
moves.  Generation runs from a checkout, where live introspection is available;
the compiled app only ever follows the README link.

Run ``python -m spectUI.metric_docgen`` to rewrite the appendix in place.  The
subprocess test ``tests/test_metric_links_qt.py`` fails if the committed README
drifts from what this module would generate, so they cannot fall out of sync.
"""
from __future__ import annotations

from pathlib import Path

from spectHR.analysis.registry import get_metric_groups, get_metrics
from spectUI.metric_links import (
    ANALYSIS_README,
    _function_location as _location,
    metric_algorithm_chain,
    repo_root,
)

START_MARKER = "<!-- METRIC-REFERENCE:START -->"
END_MARKER = "<!-- METRIC-REFERENCE:END -->"


def _first_paragraph(doc: str) -> str:
    """First paragraph of a docstring, collapsed to a single line."""
    doc = (doc or "").strip()
    if not doc:
        return "(no description)"
    return " ".join(doc.split("\n\n")[0].split())


def _entries():
    """Registered metrics + groups as ``(name, fn, is_group)``, name-sorted."""
    entries = [(n, fn, False) for n, fn in get_metrics().items()]
    entries += [(n, fn, True) for n, fn in get_metric_groups().items()]
    entries.sort(key=lambda e: e[0])
    return entries


def build_metric_reference() -> str:
    """Markdown for the auto-generated per-metric reference appendix."""
    out: list[str] = []
    for name, fn, is_group in _entries():
        out.append(f"### {name}")
        out.append("")
        out.append(_first_paragraph(fn.__doc__))
        if is_group:
            out.append("")
            out.append("Group metric: emits several data-driven columns.")
        chain = metric_algorithm_chain(name) or [(name, fn)]
        if len(chain) > 1:
            out.append("")
            out.append("Call chain: " + " -> ".join(f"`{n}`" for n, _ in chain))
        algo_name, algo_fn = chain[-1]
        loc = _location(algo_fn)
        if loc is not None:
            rel = loc[0]
            label = "Algorithm" if len(chain) > 1 else "Source"
            out.append("")
            out.append(f"{label}: [`{Path(rel).name}`]({Path(rel).name}) (`{algo_name}`)")
        out.append("")
    return "\n".join(out).strip() + "\n"


def render_section() -> str:
    """The full marker-delimited section, ready to splice into the README."""
    return f"{START_MARKER}\n\n{build_metric_reference()}\n{END_MARKER}"


def extract_section(readme_text: str) -> str | None:
    """Return the current marker-delimited section of *readme_text*, or ``None``."""
    start = readme_text.find(START_MARKER)
    end = readme_text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        return None
    return readme_text[start : end + len(END_MARKER)]


def rewrite_readme() -> Path:
    """Rewrite the appendix in ``analysis/README.md`` in place; return its path."""
    root = repo_root()
    if root is None:
        raise RuntimeError("repository root not found; run from a checkout")
    path = root / ANALYSIS_README
    text = path.read_text(encoding="utf-8")
    current = extract_section(text)
    if current is None:
        raise RuntimeError(
            f"markers {START_MARKER} / {END_MARKER} not found in {path}"
        )
    text = text.replace(current, render_section())
    path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover - manual regeneration entry point
    written = rewrite_readme()
    print(f"rewrote metric reference in {written}")
