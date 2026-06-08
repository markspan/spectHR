# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Workspace file I/O and directory management.

A *workspace* is a plain JSON dict with sections like ``FrequencyAnalysis``,
``Profiles``, ``Directories``, etc.  All analysis-parameter extraction from
that dict lives in ``spectHR.config``; this module adds only the file I/O
layer and the output-directory helper.

All ``*_from_workspace`` functions and :class:`~spectHR.config.WorkspaceView`
are re-exported here so existing ``from spectUI.workSpace import …`` call
sites keep working unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spectHR.config import (  # noqa: F401  (re-exported for call sites)
    WorkspaceView,
    display_bands_from_workspace,
    log_level_from_workspace,
    psd_method_from_workspace,
    resolved_profile_bands,
    transfer_settings_from_workspace,
)

# ---------------------------------------------------------------------------
# Default workspace
# ---------------------------------------------------------------------------

_DEFAULT_WORKSPACE: dict[str, Any] = {
    "Directories": {
        "DataDirectory":   str(Path.home()),
        "OutputDirectory": str(Path.home()),
    },
    "FrequencyAnalysis": {
        "method": "carspan",
        "bands": {
            "FullRange": {"low": 0.02, "high": 0.50, "color": "gray",  "alpha": 0.10},
            "VLF":       {"low": 0.02, "high": 0.06, "color": "green", "alpha": 0.20},
            "LF":        {"low": 0.07, "high": 0.14, "color": "blue",  "alpha": 0.20},
            "HF":        {"low": 0.15, "high": 0.40, "color": "red",   "alpha": 0.20},
        },
    },
    "Profiles": {
        "window (sec)": 30.0,
        "step (sec)": 5.0,
        "bands": [],
        "adaptive_source": "respiration_channel",
        "smooth_breath_freq": False,
        "adaptive_bands": {},
    },
    "Spectrogram": {
        "window (sec)": 30.0,
        "step (sec)": 5.0,
        "show_respiration_overlay": True,
        "colormap": "RdYlBu_r",
    },
    "TransferAnalysis": {
        "window (sec)": 30.0,
        "step (sec)": 5.0,
        "min_coherence": 0.5,
        "f_max": 0.5,
        "smooth": True,
    },
    "RespirationAnalysis": {
        "rsa_lag_s": 1.0,
        "rsa_rejection_mode": "none",
    },
    "Calibration": {
        "bp_scale": 0.125,
        "bp_zero": 0.0,
    },
    "Logging": {
        "level": "INFO",
    },
}


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def load_workspace(path: Path | str) -> dict:
    """Load a workspace JSON file and return the raw dict."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_workspace(workspace: dict, path: Path | str) -> None:
    """Write *workspace* to *path* as pretty-printed JSON."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workspace, f, indent=2, ensure_ascii=False)


def default_workspace() -> dict:
    """Return a deep copy of the built-in default workspace."""
    import copy
    return copy.deepcopy(_DEFAULT_WORKSPACE)


# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------


def get_export_dir(workspace: dict | None, *, context: str = "") -> Path:
    """Return the output directory for *context*, creating it if needed.

    Parameters
    ----------
    workspace
        Raw workspace dict (or ``None`` to use the home directory).
    context
        Sub-folder name (e.g. ``"Parameters"``, ``"PSD"``). When empty the
        base ``OutputDirectory`` is returned directly.
    """
    dirs = (workspace or {}).get("Directories", {}) or {}
    base = Path(dirs.get("OutputDirectory", str(Path.home())))
    out  = base / context if context else base
    out.mkdir(parents=True, exist_ok=True)
    return out
