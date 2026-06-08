# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

from spectHR.DataSet.loaders.registry import register_loader
from spectHR.Tools.Logger import logger


@register_loader(".pkl")
def load_pkl(path: Path, **kwargs: Any) -> "Session":
    """Load a pickled :class:`~spectHR.session.Session`."""
    from spectHR.session import Session
    logger.debug(f"Loading Session from pickle: {path}")
    with open(path, "rb") as f:
        obj = pickle.load(f)
    if not isinstance(obj, Session):
        raise TypeError(
            f"Pickle file does not contain a Session (got {type(obj).__name__}). "
            "Old PhysioData pickle files are not compatible with this version."
        )
    return obj
