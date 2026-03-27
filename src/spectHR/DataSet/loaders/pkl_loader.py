from __future__ import annotations

import pickle
from typing import Any

from spectHR.DataSet.loaders.registry import register_loader
from spectHR.Tools.Logger import logger


@register_loader(".pkl")
def load_pkl(physiodata, filename: str, **kwargs: Any) -> None:
    """
    Loader for previously pickled PhysioData objects.

    Restores the complete object state by copying all attributes from the
    pickled instance onto the current physiodata shell. This preserves
    hrv_map, band_map, active_band, rsp_map, phases, and all other fields
    that were present when the pickle was saved.
    """
    logger.info(f"Loading PhysioData from pickle: {filename}")
    with open(filename, "rb") as f:
        loaded = pickle.load(f)
    physiodata.__dict__.update(loaded.__dict__)
