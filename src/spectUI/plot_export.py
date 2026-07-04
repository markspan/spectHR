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
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

from spectHR.logger import logger


def _slug(text) -> str:
    """Filesystem-safe slug of *text* (collapse non-word runs to ``_``)."""
    return re.sub(r"[^\w.-]+", "_", str(text)).strip("_")


# Exported SVGs are scaled to this width in points (aspect ratio preserved), so
# every figure comes out a consistent, large size regardless of its on-screen
# tile size.  Point-based line widths and fonts then read proportionally lighter
# once a browser scales the responsive SVG to fill the window.  A figure that
# packs several sub-plots shares this width, so each sub-plot is correspondingly
# smaller than a single-plot figure of the same width.
_SVG_EXPORT_WIDTH_PT = 1024.0


def _savefig_svg_scaled(fig, dest: Path, dpi: int) -> None:
    """Save *fig* as SVG scaled to :data:`_SVG_EXPORT_WIDTH_PT` wide, then restore it.

    The figure is resized (aspect ratio preserved) so its width is 1024 pt while
    its line widths and fonts stay fixed in points, so relative to the enlarged
    figure they read lighter once a browser scales the SVG to fill the window.
    The live figure size is restored in the ``finally`` block; ``forward=False``
    keeps the change off the on-screen Qt canvas (no flicker).
    """
    orig = fig.get_size_inches().copy()
    orig_w_in = float(orig[0])
    if orig_w_in <= 0:
        fig.savefig(dest, format="svg", dpi=dpi, bbox_inches="tight")
        return
    scale = (_SVG_EXPORT_WIDTH_PT / 72.0) / orig_w_in
    try:
        fig.set_size_inches(orig * scale, forward=False)
        # No bbox_inches="tight" here: the widgets already tight_layout their
        # axes, and cropping would trim the figure below the target width, so
        # this keeps the SVG exactly _SVG_EXPORT_WIDTH_PT wide.
        fig.savefig(dest, format="svg", dpi=dpi)
    finally:
        fig.set_size_inches(orig, forward=False)


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
) -> None:
    """Let the user pick which dock plots to save, then write them to disk.

    Each file is named ``{datafile}_{dock}[_{epoch}].{ext}``, the recording's
    name plus the dock, plus the epoch label for per-epoch grid tiles.  Fonts
    are embedded as TrueType so PDF/EPS text stays editable in vector editors.
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
                try:
                    if fmt == "svg":
                        _savefig_svg_scaled(cv.figure, dest, dpi)
                        _make_svg_responsive(dest)
                    else:
                        cv.figure.savefig(
                            dest, format=fmt, dpi=dpi, bbox_inches="tight",
                        )
                    saved += 1
                except Exception:  # noqa: BLE001, skip a bad figure, keep going
                    logger.exception("Failed to save figure for %s", obj_name)
    QMessageBox.information(parent, "Plots exported",
                            f"Saved {saved} figure(s) to {out}")
