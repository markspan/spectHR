# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Parameters — analysis configuration.

A :class:`Parameters` is the single object that carries all settings:
the analysis parameters (PSD method, band definitions, RSA settings,
calibration, …) **and** the working directories (DataDirectory,
CacheDirectory, OutputDirectory).  It is the in-memory form of the
``~/workspace.json`` file; ``MainWindow`` loads it at startup and saves it
only when the user asks (Save settings).  It is passed directly to every
widget so widgets read typed properties instead of digging into dicts.

Only window geometry / dock layout lives outside here, in
:class:`~spectUI.settings.AppSettings` (QSettings) — genuinely
machine-specific UI state, not a portable "setting".

``populate_tree`` lives here because it is the bridge between the file-
system data directory and the file-browser dock.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_documents_dir


_REPLACE_WHOLE = {"bands"}  # keys whose dict value is an atomic table, not merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict: *override* merged onto *base*, recursively.

    Scalar/list values in *override* win outright; dict values are merged
    key-by-key so that a preset that only specifies a few keys leaves the
    rest at their defaults.  Keys listed in ``_REPLACE_WHOLE`` are treated
    as atomic tables — a preset that provides them replaces the base value
    entirely (e.g. ``bands`` defines a complete band table, not additions).
    """
    result = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict) and k not in _REPLACE_WHOLE:
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from spectHR.config import WorkspaceView

# ---------------------------------------------------------------------------
# Default configuration
#
# Everything lives in one workspace dict — including the working directories —
# so it can be saved to / loaded from a single ``workspace.json``.  Window
# geometry stays in QSettings (machine-specific UI state, not a "setting").
# ---------------------------------------------------------------------------

_DEFAULT: dict = {
    "Directories": {
        "DataDirectory":   str(Path(user_documents_dir()) / "spectHR"),
        "CacheDirectory":  str(Path(user_cache_dir("spectHR"))),
        "OutputDirectory": str(Path(user_documents_dir()) / "spectHR" / "export"),
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
            "smooth_for_display": True,
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
            "filter_type":      "highpass",
            "filter_cutoff":    0.5,
            "display_filtered": False,
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
        "window (sec)":             30.0,
        "step (sec)":                5.0,
        "show_respiration_overlay": True,
        "colormap":                 "RdYlBu_r",
    },
    "TransferAnalysis": {
        "input_signal":             "bp_sys",
        "window (sec)":             30.0,
        "step (sec)":                5.0,
        "min_coherence":             0.5,
        "f_min":                     0.0,
        "f_max":                     0.5,
        "smooth":                    True,
        "phase_view":               "wrapped",
        "show_coherence_threshold":  True,
        "coherence_mask_alpha":      0.20,
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

# ---------------------------------------------------------------------------
# Parameters class
# ---------------------------------------------------------------------------


class Parameters(WorkspaceView):
    """Mutable analysis configuration with file I/O.

    Extends :class:`~spectHR.config.WorkspaceView` with creation helpers
    and mutation.  All typed analysis properties (``psd_method``,
    ``rsa_lag_s``, ``profile_settings``, …) are inherited unchanged.

    Examples
    --------
    >>> p = Parameters.default()
    >>> p.save(Path("my_study.json"))
    >>> p = Parameters.load(Path("my_study.json"))
    >>> p.psd_method          # PsdMethod instance
    >>> p.rsa_lag_s           # 1.0
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> Parameters:
        """Return a fresh Parameters object with built-in defaults."""
        return cls(copy.deepcopy(_DEFAULT))

    @classmethod
    def load(cls, path: Path | str) -> Parameters:
        """Load analysis parameters from a JSON file.

        The file is deep-merged onto the built-in defaults so that a preset
        which only specifies a subset of sections (e.g. a VU-AMS preset that
        only overrides ``CardioParameters``) leaves every other section at its
        default value rather than disappearing.
        """
        with open(path, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        return cls(_deep_merge(_DEFAULT, on_disk))

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def save(self, path: Path | str) -> None:
        """Write these parameters to *path* as pretty-printed JSON."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._ws, f, indent=4, ensure_ascii=False)

    def to_dict(self) -> dict:
        """Return a deep copy of the underlying configuration dict."""
        return copy.deepcopy(self._ws)

    @classmethod
    def from_dict(cls, data: dict) -> Parameters:
        """Build a ``Parameters`` object from an already-loaded dict."""
        return cls(copy.deepcopy(data))

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def update(self, section: str, values: dict) -> None:
        """Merge *values* into *section*, then invalidate the cache."""
        self._ws.setdefault(section, {}).update(values)
        self._invalidate()

    def replace(self, data: dict) -> None:
        """Replace the entire configuration dict and invalidate the cache."""
        self._ws = data
        self._invalidate()

    # ------------------------------------------------------------------
    # Working directories (stored in the workspace, not QSettings)
    # ------------------------------------------------------------------

    def _dir(self, key: str, default: Path) -> Path:
        return Path(self._ws.get("Directories", {}).get(key, str(default)))

    @property
    def data_dir(self) -> Path:
        return self._dir("DataDirectory", Path(user_documents_dir()) / "spectHR")

    @property
    def cache_dir(self) -> Path:
        return self._dir("CacheDirectory", Path(user_cache_dir("spectHR")))

    @property
    def output_dir(self) -> Path:
        return self._dir("OutputDirectory", Path(user_documents_dir()) / "spectHR" / "export")

    def export_dir(self, context: str = "") -> Path:
        """Return the output directory for *context*, creating it if needed."""
        path = self.output_dir / context if context else self.output_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def directories(self) -> dict:
        """Flat dict compatible with ``DirectorySelectorDialog``."""
        return {
            "DataDirectory":   str(self.data_dir),
            "CacheDirectory":  str(self.cache_dir),
            "OutputDirectory": str(self.output_dir),
        }

    @directories.setter
    def directories(self, dirs: dict) -> None:
        """Accept the dict from ``DirectorySelectorDialog.get_directories()``."""
        self._ws.setdefault("Directories", {}).update(
            {k: str(v) for k, v in dirs.items()}
        )

    # ------------------------------------------------------------------
    # Cache invalidation
    # ------------------------------------------------------------------

    def _invalidate(self) -> None:
        """Clear all ``cached_property`` values so they recompute on access."""
        cached = {"psd_method", "profile_settings", "resolved_profile_bands",
                  "spectrogram_settings", "transfer_settings", "cardio_params"}
        for key in cached:
            self.__dict__.pop(key, None)


# ---------------------------------------------------------------------------
# File-tree helper
# ---------------------------------------------------------------------------

_FILE_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("XDF Files",         ("*.xdf", "*.XDF")),
    ("VAMS EDF Files",    ("*.edf", "*.EDF")),
    ("CARSPAN EVT Files", ("*.EVT", "*.evt")),
    ("RR Text Files",     ("*.txt", "*.TXT")),
)


def populate_tree(tree: QTreeWidget, data_dir: Path) -> None:
    """Populate *tree* with recording files found in *data_dir*.

    Files are grouped by type; each item carries ``Qt.UserRole``
    metadata so a double-click handler can load the file.
    """
    tree.clear()
    tree.setHeaderHidden(True)

    if not data_dir.is_dir():
        item = QTreeWidgetItem(tree, [f"Directory not found:\n{data_dir}"])
        item.setFlags(Qt.ItemIsEnabled)
        return

    for category, patterns in _FILE_CATEGORIES:
        files: list[Path] = sorted(
            {f for pat in patterns for f in data_dir.glob(pat)},
            key=lambda p: p.name.lower(),
        )
        if not files:
            continue

        header = QTreeWidgetItem(tree, [category])
        header.setFlags(Qt.ItemIsEnabled)
        font = header.font(0)
        font.setBold(True)
        header.setFont(0, font)

        for f in files:
            item = QTreeWidgetItem(header, [f.name])
            item.setData(0, Qt.UserRole, {"type": "dataset", "filename": str(f)})
            item.setToolTip(0, str(f))

        header.setExpanded(True)
