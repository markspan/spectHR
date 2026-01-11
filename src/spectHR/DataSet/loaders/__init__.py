from __future__ import annotations

# Expose registry API
from spectHR.DataSet.loaders.registry import get_loader, register_loader

# Force-load concrete loaders so their decorators execute
import spectHR.DataSet.loaders.xdf_loader  # noqa: F401
import spectHR.DataSet.loaders.pkl_loader  # noqa: F401
import spectHR.DataSet.loaders.evt_loader  # noqa: F401
import spectHR.DataSet.loaders.polar_csv  # noqa: F401
import spectHR.DataSet.loaders.harness_csv  # noqa: F401

__all__ = ["get_loader", "register_loader"]
