from __future__ import annotations

import pickle
from typing import Any

from spectHR.DataSet.loaders.registry import register_loader
from spectHR.Tools.Logger import logger


@register_loader(".pkl")
def load_pkl(physiodata, filename: str, **kwargs: Any) -> None:
    """
    Loader for previously pickled PhysioData objects.

    Notes
    -----
    - This assumes the pickle contains a PhysioData instance.
    - Its internal state is copied onto the current `physiodata`.
    """
    logger.info(f"Loading PhysioData from pickle: {filename}")
    with open(filename, "rb") as f:
        loaded = pickle.load(f)

    # Copy relevant attributes (simple shallow copy)
    for attr in ("timeseries", "events", "epochs", "rtops"):
        if hasattr(loaded, attr):
            setattr(physiodata, attr, getattr(loaded, attr))
