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
                try:
                    cv.figure.savefig(
                        out / f"{'_'.join(parts)}{ext}",
                        format=fmt,
                        dpi=dpi,
                        bbox_inches="tight",
                    )
                    saved += 1
                except Exception:  # noqa: BLE001, skip a bad figure, keep going
                    logger.exception("Failed to save figure for %s", obj_name)
    QMessageBox.information(parent, "Plots exported",
                            f"Saved {saved} figure(s) to {out}")
