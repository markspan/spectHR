# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Workspace file I/O, directory management, and file-tree population.

A *workspace* is a plain JSON dict with sections like ``FrequencyAnalysis``,
``Profiles``, ``Directories``, etc.  All analysis-parameter extraction from
that dict lives in ``spectHR.config``; this module adds only the file I/O
layer, the output-directory helper, and the file-browser tree populator.

All ``*_from_workspace`` functions and :class:`~spectHR.config.WorkspaceView`
are re-exported here so existing ``from spectUI.workSpace import …`` call
sites keep working unchanged.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

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
        "DataDirectory":   str(Path.home() / "Documents" / "spectHR"),
        "CacheDirectory":  str(Path.home() / "Documents" / "spectHR" / "cache"),
        "OutputDirectory": str(Path.home() / "Documents" / "spectHR" / "export"),
    },
    "FrequencyAnalysis": {
        "method": "carspan",
        "bands": {
            "FullRange": {"low": 0.02, "high": 0.50, "color": "gray",      "alpha": 0.35},
            "VLF":       {"low": 0.02, "high": 0.06, "color": "blue",      "alpha": 0.20},
            "LF":        {"low": 0.07, "high": 0.14, "color": "darkgreen", "alpha": 0.20},
            "HF":        {"low": 0.15, "high": 0.40, "color": "red",       "alpha": 0.20},
        },
        "carspan": {
            "freq_resolution":    0.01,
            "signal":             "events",
            "window":             "10% cosine bell",
            "plot_units":         "mMI²/Hz",
            "smooth_for_display": False,
            "dc_removal":         True,
        },
        "welch": {
            "fs": 4.0, "nperseg": 256, "noverlap": 128, "nfft": 512,
            "window": "hann", "units": "mMI²",
        },
        "lombscargle": {
            "nfreqs": 100, "fmin_floor": 0.0001, "units": "mMI²",
        },
        "confidence_interval_alpha": 0.05,
    },
    "CardioParameters": {
        "IbiClassification": {
            "window_length":        20,
            "n_std":                3.0,
            "max_ibi_sec":          2.5,
            "min_peak_distance_ms": 300.0,
        },
        "EcgPreprocessing": {
            "filter_type":   "highpass",
            "filter_cutoff": 0.5,
        },
    },
    "Calibration": {
        "bp_scale": 0.125,
        "bp_zero":  0.0,
    },
    "IcgAnalysis": {
        "b_point_guard_ms": 30.0,
    },
    "Profiles": {
        "window (sec)":       30.0,
        "step (sec)":          5.0,
        "bands":               [],
        "adaptive_bands":      {},
        "adaptive_source":     "respiration_channel",
        "smooth_breath_freq":  False,
        "smooth_for_display":  False,
    },
    "Spectrogram": {
        "window (sec)":              30.0,
        "step (sec)":                 5.0,
        "show_respiration_overlay":  True,
        "colormap":                  "RdYlBu_r",
    },
    "TransferAnalysis": {
        "input_signal":              "rsp",
        "window (sec)":              30.0,
        "step (sec)":                 5.0,
        "min_coherence":              0.5,
        "f_min":                      0.0,
        "f_max":                      0.5,
        "smooth":                     True,
        "phase_view":                "wrapped",
        "show_coherence_threshold":   True,
        "coherence_mask_alpha":       0.20,
    },
    "RespirationAnalysis": {
        "per_epoch":          False,
        "rsa_lag_s":           1.0,
        "rsa_overlay":        "rsa0",
        "rsp_source":         "icg",
        "rsa_rejection_mode": "none",
    },
    "Logging": {
        "level": "INFO",
    },
}

# File categories shown in the workspace tree, in display order.
# Each entry: (category label, tuple of glob patterns)
_FILE_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("XDF Files",         ("*.xdf", "*.XDF")),
    ("VAMS EDF Files",    ("*.edf", "*.EDF")),
    ("CARSPAN EVT Files", ("*.EVT", "*.evt")),
    ("RR Text Files",     ("*.txt", "*.TXT")),
)


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
        json.dump(workspace, f, indent=4, ensure_ascii=False)


def default_workspace() -> dict:
    """Return a deep copy of the built-in default workspace."""
    return copy.deepcopy(_DEFAULT_WORKSPACE)


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------


def get_export_dir(workspace: dict | None, *, context: str = "") -> Path:
    """Return the output directory for *context*, creating it if needed."""
    dirs = (workspace or {}).get("Directories", {}) or {}
    base = Path(dirs.get("OutputDirectory", str(Path.home())))
    out  = base / context if context else base
    out.mkdir(parents=True, exist_ok=True)
    return out


def get_data_dir(workspace: dict | None) -> Path:
    """Return the configured DataDirectory."""
    dirs = (workspace or {}).get("Directories", {}) or {}
    return Path(dirs.get("DataDirectory", str(Path.home())))


def get_cache_dir(workspace: dict | None) -> Path:
    """Return the configured CacheDirectory, creating it if needed."""
    dirs = (workspace or {}).get("Directories", {}) or {}
    p = Path(dirs.get("CacheDirectory", str(Path.home())))
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Workspace tree
# ---------------------------------------------------------------------------


def PopulateTree(tree: QTreeWidget, workspace: dict | None) -> None:
    """Populate *tree* with the recording files found in DataDirectory.

    Organises files into category groups (XDF, EDF, EVT, RR Text). Each
    file item carries ``Qt.UserRole`` metadata so a double-click handler
    can load the corresponding recording.
    """
    tree.clear()
    tree.setHeaderHidden(True)

    data_dir = get_data_dir(workspace)
    if not data_dir.is_dir():
        placeholder = QTreeWidgetItem(tree, [f"Directory not found: {data_dir}"])
        placeholder.setFlags(Qt.ItemIsEnabled)
        return

    for category, patterns in _FILE_CATEGORIES:
        files: list[Path] = []
        for pattern in patterns:
            files.extend(data_dir.glob(pattern))
        files = sorted(set(files), key=lambda p: p.name.lower())

        if not files:
            continue

        parent = QTreeWidgetItem(tree, [category])
        parent.setFlags(Qt.ItemIsEnabled)
        font = parent.font(0)
        font.setBold(True)
        parent.setFont(0, font)

        for f in files:
            item = QTreeWidgetItem(parent, [f.name])
            item.setData(0, Qt.UserRole, {
                "type":           "dataset",
                "filename":       str(f),
                "bands_expanded": False,
            })
            item.setToolTip(0, str(f))

        parent.setExpanded(True)
