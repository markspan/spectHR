# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
from typing import Callable
from pathlib import Path

LoaderFunc = Callable[..., None]

_EXTENSION_LOADERS: dict[str, LoaderFunc] = {}


def register_loader(*exts: str | Path):
    """
    Decorator to register a loader function for one or more file extensions.

    Loader signature must be:
        loader(physiodata: PhysioData, filename: str, **kwargs) -> None
    """

    def decorator(func: LoaderFunc) -> LoaderFunc:
        for ext in exts:
            _EXTENSION_LOADERS[ext.lower()] = func
        return func

    return decorator


def get_loader(ext_or_path: str) -> LoaderFunc | None:
    """
    Resolve loader based on extension or full path.

    Parameters
    ----------
    ext_or_path : str
        Either a bare extension (".xdf") or a full filename ("data/file.xdf").

    Returns
    -------
    LoaderFunc | None
    """
    _, ext = os.path.splitext(ext_or_path)
    ext = ext.lower() if ext else ext_or_path.lower()
    return _EXTENSION_LOADERS.get(ext)
