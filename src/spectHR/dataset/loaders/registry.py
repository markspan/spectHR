# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from spectHR.session import Session

LoaderFunc = Callable[..., "Session"]

_EXTENSION_LOADERS: dict[str, LoaderFunc] = {}


def register_loader(*exts: str):
    """Decorator to register a loader for one or more file extensions.

    Loader signature: ``loader(path: Path, **kwargs) -> Session``
    """
    def decorator(fn: LoaderFunc) -> LoaderFunc:
        for ext in exts:
            _EXTENSION_LOADERS[ext.lower()] = fn
        return fn
    return decorator


def load(path: str | Path, **kwargs) -> "Session":
    """Load *path* using the registered loader for its extension."""
    path = Path(path)
    loader = _EXTENSION_LOADERS.get(path.suffix.lower())
    if loader is None:
        raise ValueError(f"No loader registered for '{path.suffix}'")
    return loader(path, **kwargs)
