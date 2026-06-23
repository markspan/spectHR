# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from spectHR.dataset.loaders.registry import register_loader
from spectHR.logger import logger

if TYPE_CHECKING:
    from spectHR.session import Session


@register_loader(".txt")
def load_polar_raw_csv(path: Path, **kwargs) -> "Session":
    """Load a raw Polar ECG CSV export as a Session.

    Expected columns (semicolon-separated):
        - 'timestamp [ms]'
        - 'ecg [uV]'
    """
    from spectHR.dataset.loaders._epochs import build_epochs
    from spectHR.session import Samples, Session

    logger.info(f"Loading Polar raw CSV: {path}")

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            cols = reader.fieldnames or []
            rows = list(reader)
    except (IOError, OSError, UnicodeDecodeError, csv.Error) as exc:
        raise IOError(f"Failed to read Polar CSV: {path}") from exc

    if "ecg [uV]" not in cols or "timestamp [ms]" not in cols:
        raise ValueError("CSV does not look like a Polar raw ECG export")

    times  = np.array([r["timestamp [ms]"] for r in rows], dtype=float) / 1000.0
    values = np.array([r["ecg [uV]"]       for r in rows], dtype=float)

    if times.size:
        times = times - times[0]

    ecg_name = "ecg-[polar_raw]"
    samples = {ecg_name: Samples(times, values, name=ecg_name)}

    t_end = float(times[-1]) if times.size else 0.0
    epochs = build_epochs([], [], t_start=0.0, t_end=t_end)

    logger.info(f"Loaded ECG → {ecg_name}")
    return Session(name=Path(path).stem, samples=samples, epochs=epochs)
