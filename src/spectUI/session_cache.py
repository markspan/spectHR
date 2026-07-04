# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
On-disk cache of an edited :class:`~spectHR.session.Session`.

Extracted from ``MainWindow``: the window keeps the debounce timer (UI timing),
but the *path convention* and the pickle write live here.

The cache is a pickle of the whole processed Session next to a raw recording:
on the next load of the same raw file the cached Session, carrying the user's
R-peak edits, is loaded instead of re-parsing and re-detecting.
"""
from __future__ import annotations

import pickle
from pathlib import Path

from spectHR.logger import logger
from spectHR.session import Session


def cache_path(cache_dir: Path, raw_path: Path) -> Path:
    """Cache pickle path for a raw recording: ``<cache_dir>/<name>.pkl``."""
    return Path(cache_dir) / (raw_path.name + ".pkl")


def write_session_cache(session: Session, path: Path) -> bool:
    """Pickle *session* to *path* (best effort); return ``True`` on success.

    Caching is best-effort: a failure is logged and swallowed so it never
    interrupts editing.
    """
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(session, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("Cached edited dataset → %s", path.name)
        return True
    except Exception:   # noqa: BLE001, caching is best-effort
        logger.exception("Failed to write cache pickle %s", path)
        return False
