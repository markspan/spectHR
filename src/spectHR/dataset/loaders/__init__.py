# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import spectHR.dataset.loaders.edf_loader  # noqa: F401
import spectHR.dataset.loaders.evt_loader  # noqa: F401
import spectHR.dataset.loaders.harness_csv  # noqa: F401
import spectHR.dataset.loaders.nff_loader  # noqa: F401  (.nff; also used by evt_loader)
import spectHR.dataset.loaders.pkl_loader  # noqa: F401
import spectHR.dataset.loaders.polar_csv  # noqa: F401

# Force-load concrete loaders so their @register_loader decorators execute.
# Every loader module is listed explicitly (rather than relying on one loader
# importing another) so each registers its extension independently.
import spectHR.dataset.loaders.xdf_loader  # noqa: F401

# Expose registry API
from spectHR.dataset.loaders.registry import load, register_loader

__all__ = ["load", "register_loader"]
