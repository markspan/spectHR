# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared figure-export behaviour for band-power plot widgets.

Provides
--------
sanitize_filename(name)
    Strip filesystem-unsafe characters from a string.

PlotExportMixin
    Mixin that adds Shift+Ctrl+P figure export to any ``QWidget`` subclass
    that exposes:

    * ``self._export_context`` (class attr, str) -- e.g. ``"PSD"`` or
                                                    ``"Profile"``; used in
                                                    log messages, the summary
                                                    dialog, and as the
                                                    fallback filename prefix
                                                    when no dataset name is
                                                    available.
    * ``self._labels``         -- list[str] of epoch / subplot titles.
    * ``self._subplots``       -- list of subplot objects with ``.canvas``.
    * ``self._series_list``    -- list of series objects (for dataset name).
    * ``self._parameters``     -- :class:`~spectUI.parameters.Parameters` or None.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Dict, Any

from spectHR.Tools.Logger import logger
from spectUI.common.uitools import show_export_summary
from spectUI.settings import AppSettings

_FILENAME_BAD_CHARS = re.compile(r'[\\/:*?"<>|\s]+')

EXPORT_FORMATS: tuple[str, ...] = ("pdf",)


def sanitize_filename(name: str) -> str:
    """Replace filesystem-unsafe characters with underscores."""
    return _FILENAME_BAD_CHARS.sub("_", name).strip("._")


class PlotExportMixin:
    """Shift+Ctrl+P figure export, ready to mix into any plot widget.

    The host class must set a class-level ``_export_context`` string
    (e.g. ``"PSD"`` or ``"Profile"``), everything else is derived
    from that single attribute.
    """

    _export_context: str = "Plot"

    def _save_all_plots(self) -> None:
        ctx = self._export_context
        export_dir = self._resolve_export_dir()
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            msg = f"{ctx} export: could not create {export_dir!s}: {exc}"
            logger.warning(msg)
            show_export_summary(self, context=ctx, summary=msg, failures=(msg,))
            return

        prefix = self._dataset_prefix()
        n_saved = 0
        failures: list[str] = []
        for label, subplot in zip(self._labels, self._subplots):
            stem = self._build_filename_stem(prefix, label)
            for fmt in EXPORT_FORMATS:
                path = export_dir / f"{stem}.{fmt}"
                try:
                    subplot.canvas.figure.savefig(
                        path, format=fmt, bbox_inches="tight",
                    )
                    n_saved += 1
                except (OSError, ValueError) as exc:
                    fail_msg = f"failed to write {path!s}: {exc}"
                    failures.append(fail_msg)
                    logger.warning(f"{ctx} export: {fail_msg}")

        summary = (
            f"{ctx} export: saved {n_saved} file(s) "
            f"({len(self._subplots)} plot(s) x {len(EXPORT_FORMATS)} format(s)) "
            f"to {export_dir!s}"
        )
        logger.info(summary)
        show_export_summary(self, context=ctx, summary=summary, failures=failures)

    def _resolve_export_dir(self) -> Path:
        return AppSettings().export_dir(context=self._export_context)

    def _dataset_prefix(self) -> str:
        for series in self._series_list:
            pd = getattr(series, "_pd", None)
            basename = getattr(pd, "basename", None)
            if basename:
                return sanitize_filename(str(basename))
        return self._export_context

    def _build_filename_stem(self, prefix: str, label: str) -> str:
        clean_label = sanitize_filename(label) or "epoch"
        return f"{prefix}_{self._export_context}_{clean_label}"
