# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Export the open dock figures as PDF/EPS/PNG files.

Extracted from ``MainWindow._export_plots``: a self-contained orchestration
that pops the selection dialog, walks the live data docks for their matplotlib
canvases, and writes one file per figure named ``{datafile}_{dock}[_{epoch}].``.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

from spectHR.logger import logger

#: Vector formats the line/font scale applies to (PNG is raster; its detail is
#: set by DPI, so the scale is not applied to it).
_VECTOR_FORMATS = frozenset({"svg", "pdf", "eps"})


def _slug(text) -> str:
    """Filesystem-safe slug of *text* (collapse non-word runs to ``_``)."""
    return re.sub(r"[^\w.-]+", "_", str(text)).strip("_")


@contextmanager
def _scaled_line_and_font(fig, factor: float):
    """Temporarily scale every line width and font size in *fig* by *factor*.

    A plot authored for a small on-screen tile has line widths and fonts that
    look heavy when the exported file is viewed large (a fullscreen browser SVG
    or a PDF fitted to the window).  Scaling them down, together, without
    changing the figure's physical size, keeps the file usable both for viewing
    and for embedding at its true dimensions.  The originals are restored on
    exit, and no event loop runs in between, so the on-screen canvas never
    repaints (no flicker).
    """
    if factor == 1.0 or factor <= 0.0:
        yield
        return
    from matplotlib.lines import Line2D
    from matplotlib.text import Text

    restore = []
    for line in fig.findobj(Line2D):        # data lines, tick marks, grid, legend
        lw = line.get_linewidth()
        restore.append((line.set_linewidth, lw))
        line.set_linewidth(lw * factor)
    for ax in fig.get_axes():               # axes spines (the plot box)
        for spine in ax.spines.values():
            lw = spine.get_linewidth()
            restore.append((spine.set_linewidth, lw))
            spine.set_linewidth(lw * factor)
    for text in fig.findobj(Text):          # titles, labels, ticks, legend, notes
        fs = text.get_fontsize()
        restore.append((text.set_fontsize, fs))
        text.set_fontsize(fs * factor)
    try:
        yield
    finally:
        for setter, value in restore:
            setter(value)


def _make_svg_responsive(path: Path) -> None:
    """Rewrite a matplotlib SVG so a browser scales it to fill the window.

    matplotlib stamps a fixed ``pt`` width/height on the root ``<svg>``, so a
    browser renders the figure at that small intrinsic size.  Replacing the
    width/height with ``100%`` (while keeping the ``viewBox``) makes the figure
    scale to the viewport, preserving its aspect ratio.  The ``viewBox`` still
    carries the intrinsic dimensions, so vector editors size it correctly.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    m = re.search(r"<svg\b[^>]*>", text)
    if m is None:
        return
    tag = m.group(0)
    new_tag = tag
    # matplotlib always writes a viewBox, but guard the case it does not: build
    # one from the numeric width/height before they are switched to 100%.
    if "viewBox" not in new_tag:
        w = re.search(r'\bwidth="([\d.]+)', tag)
        h = re.search(r'\bheight="([\d.]+)', tag)
        if w and h:
            new_tag = f'{new_tag[:-1]} viewBox="0 0 {w.group(1)} {h.group(1)}">'
    new_tag = re.sub(r'\bwidth="[^"]*"', 'width="100%"', new_tag, count=1)
    new_tag = re.sub(r'\bheight="[^"]*"', 'height="100%"', new_tag, count=1)
    if new_tag != tag:
        path.write_text(text.replace(tag, new_tag, 1), encoding="utf-8")


def _dock_figures(widget):
    """``(canvas, epoch_label|None)`` for every figure in *widget*.

    Grid docks expose one tile per epoch (``_subplots`` aligned with the
    ``_last_results`` records), so each tile is tagged with its epoch label;
    single-figure docks yield one untagged canvas.
    """
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as _Canvas

    tiles = getattr(widget, "_subplots", None)
    results = getattr(widget, "_last_results", None)
    if tiles and results and len(tiles) == len(results):
        return [(t.canvas, lbl) for t, (lbl, _r) in zip(tiles, results)
                if getattr(t, "canvas", None) is not None]
    return [(cv, None) for cv in widget.findChildren(_Canvas)]


def export_dock_plots(
    parent: QWidget,
    data_docks: Mapping[str, QWidget],
    view_labels: Mapping[str, str],
    session_name: str,
    directory: str,
    line_font_scale: float = 1.0,
) -> None:
    """Let the user pick which dock plots to save, then write them to disk.

    Each file is named ``{datafile}_{dock}[_{epoch}].{ext}``, the recording's
    name plus the dock, plus the epoch label for per-epoch grid tiles.  Fonts
    are embedded as TrueType so PDF/EPS text stays editable in vector editors.

    *line_font_scale* multiplies line widths and font sizes for the **vector**
    formats (SVG/PDF/EPS), so a plot authored for a small on-screen tile can be
    made lighter for viewing at a larger size.  ``1.0`` leaves them unchanged.
    """
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as _Canvas

    from spectUI.widgets.plot_export_dialog import PlotExportDialog

    # Every data dock that currently has at least one figure.
    candidates = []
    for obj_name, widget in data_docks.items():
        if widget.findChildren(_Canvas):
            candidates.append((obj_name, view_labels.get(obj_name, obj_name), widget))
    if not candidates:
        QMessageBox.information(parent, "Export plots", "No plots are available to export.")
        return

    dlg = PlotExportDialog(parent, [(k, lbl) for k, lbl, _ in candidates], directory)
    if not dlg.exec():
        return
    out = Path(dlg.directory())
    out.mkdir(parents=True, exist_ok=True)
    selected  = dlg.selected()
    ext, fmt  = dlg.export_format()
    dpi       = dlg.dpi()

    import matplotlib as mpl
    data_stem = _slug(session_name or "data") or "data"
    saved = 0
    # Embed fonts as TrueType (type 42) so PDF/EPS text stays editable in
    # Illustrator / Inkscape rather than being converted to outlines.
    with mpl.rc_context({"pdf.fonttype": 42, "ps.fonttype": 42}):
        for obj_name, label, widget in candidates:
            if obj_name not in selected:
                continue
            figs = _dock_figures(widget)
            dock_slug = _slug(label) or obj_name
            for i, (cv, epoch) in enumerate(figs):
                parts = [data_stem, dock_slug]
                if epoch:
                    parts.append(_slug(epoch))
                elif len(figs) > 1:
                    parts.append(str(i + 1))
                dest = out / f"{'_'.join(parts)}{ext}"
                scale = line_font_scale if fmt in _VECTOR_FORMATS else 1.0
                try:
                    with _scaled_line_and_font(cv.figure, scale):
                        cv.figure.savefig(
                            dest, format=fmt, dpi=dpi, bbox_inches="tight",
                        )
                    if fmt == "svg":
                        _make_svg_responsive(dest)
                    saved += 1
                except Exception:  # noqa: BLE001, skip a bad figure, keep going
                    logger.exception("Failed to save figure for %s", obj_name)
    QMessageBox.information(parent, "Plots exported",
                            f"Saved {saved} figure(s) to {out}")
