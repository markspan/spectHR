# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from spectHR.DataSet.loaders.registry import register_loader
from spectHR.logger import logger

_MISSING_SENTINEL = -1
_ECG_SCALE = 40.0


@register_loader("._csv")
def load_harness_raw_csv(path: Path, **kwargs) -> "Session":
    """Load raw ECG data from the Harness CSV format as a Session.

    Expected columns:
        - ``ms``        - timestamp in milliseconds, ``-1`` for missing
        - ``ECG Data``  - raw ECG amplitude, ``-1`` for missing; scaled by 40
    """
    from spectHR.session import Session, Samples
    from spectHR.DataSet.loaders._epochs import build_epochs

    logger.info(f"Loading raw Harness CSV: {path}")

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=",")
            cols = reader.fieldnames or []
            rows = list(reader)
    except (IOError, OSError, UnicodeDecodeError, csv.Error) as exc:
        raise IOError(f"Failed to read Harness CSV: {path}") from exc

    if "ECG Data" not in cols or "ms" not in cols:
        raise ValueError("CSV does not match expected Harness format")

    ms_raw  = np.array([r["ms"]       for r in rows], dtype=float)
    ecg_raw = np.array([r["ECG Data"] for r in rows], dtype=float)

    ecg = np.where(ecg_raw == _MISSING_SENTINEL, np.nan, ecg_raw) * _ECG_SCALE
    ms  = np.where(ms_raw  == _MISSING_SENTINEL, np.nan, ms_raw)

    sample_indices = np.arange(ms.size)
    valid = np.isfinite(ms)
    if not valid.any():
        raise ValueError("Harness CSV contains no valid timestamps")

    from scipy.interpolate import interp1d
    ms_filled = interp1d(
        sample_indices[valid],
        ms[valid],
        kind="linear",
        bounds_error=False,
        fill_value=np.nan,
    )(sample_indices)

    times_seconds = ms_filled / 1000.0
    finite_diffs  = np.diff(times_seconds[np.isfinite(times_seconds)])
    if finite_diffs.size == 0:
        raise ValueError("Invalid timestamps in Harness CSV")

    dt    = float(np.median(finite_diffs))
    times = np.arange(ecg.size, dtype=float) * dt
    ecg   = ecg - np.nanmean(ecg)

    ecg_name = "ecg-[harness_raw]"
    samples  = {ecg_name: Samples(times, ecg, name=ecg_name)}

    t_end  = float(times[-1]) if times.size else 0.0
    epochs = build_epochs([], [], t_start=0.0, t_end=t_end)

    logger.info(f"Loaded ECG → {ecg_name}")
    return Session(name=Path(path).stem, samples=samples, epochs=epochs)
