# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/analysis/_docgen.py
"""
Generate the per-metric reference appendix in ``analysis/README.md``.

Every registered metric gets an anchored ``### <name>`` section (so the Results
dock can deep-link to ``README.md#<name>``) carrying the metric's docstring and a
relative link to its source file.  The block deliberately omits line numbers so
it stays stable as code moves; the *exact* line range is what the dock's
"view source" link resolves live (see :mod:`spectHR.analysis.sources`).

Run ``python -m spectHR.analysis._docgen`` to rewrite the appendix in place.  The
test ``tests/test_metric_sources.py`` fails if the committed README drifts from
what this module would generate, so the two cannot fall out of sync silently.
"""
from __future__ import annotations

from pathlib import Path

from spectHR.analysis.registry import get_metric_groups, get_metrics
from spectHR.analysis.sources import (
    ANALYSIS_README,
    metric_source_location,
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


def build_metric_reference() -> str:
    """Markdown for the auto-generated per-metric reference appendix."""
    singles = get_metrics()
    groups = get_metric_groups()
    entries = [(n, fn, False) for n, fn in singles.items()]
    entries += [(n, fn, True) for n, fn in groups.items()]
    entries.sort(key=lambda e: e[0])

    out: list[str] = []
    for name, fn, is_group in entries:
        out.append(f"### {name}")
        out.append("")
        out.append(_first_paragraph(fn.__doc__))
        if is_group:
            out.append("")
            out.append("Group metric: emits several data-driven columns.")
        loc = metric_source_location(name)
        if loc is not None:
            rel = loc[0]
            out.append("")
            out.append(f"Source: [`{Path(rel).name}`]({Path(rel).name}) (`{name}`)")
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
