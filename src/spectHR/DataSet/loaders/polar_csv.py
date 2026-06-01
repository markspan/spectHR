# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import csv

import numpy as np

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.loaders.registry import register_loader
from spectHR.Tools.Logger import logger


@register_loader(".txt")
def load_polar_raw_csv(
    physiodata, filename: str, **kwargs
) -> None:
    """
    Load raw Polar ECG CSV export.

    Expected columns (semicolon-separated):
        - 'timestamp [ms]'
        - 'ecg [uV]'

    Produces:
        - One ECG TimeSeries
        - One global EventSeries (start / stop)
        - One implicit band
    """

    logger.info(f"Loading Polar raw CSV: {filename}")

    # ------------------------------------------------------------
    # READ CSV
    # ------------------------------------------------------------
    try:
        with open(filename, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            cols = reader.fieldnames or []
            rows = list(reader)
    except (IOError, OSError, UnicodeDecodeError, csv.Error) as exc:
        raise IOError(f"Failed to read Polar CSV: {filename}") from exc

    if "ecg [uV]" not in cols or "timestamp [ms]" not in cols:
        raise ValueError("CSV does not look like a Polar raw ECG export")

    times  = np.array([r["timestamp [ms]"] for r in rows], dtype=float) / 1000.0
    values = np.array([r["ecg [uV]"]       for r in rows], dtype=float)

    physiodata.has_ecg = True

    # ------------------------------------------------------------
    # TIMESERIES
    # ------------------------------------------------------------
    # Single implicit band
    band_id = "polar_raw"

    ecg_name = f"ecg-[{band_id}]"
    physiodata.timeseries[ecg_name] = TimeSeries(times, values)

    logger.info(f"Loaded ECG → {ecg_name}")

    # ------------------------------------------------------------
    # EVENTS (global start / stop)
    # ------------------------------------------------------------
    ev_name = "markers"
    physiodata.events[ev_name] = EventSeries(
        times=np.array([times[0], times[-1]], dtype=float),
        labels=["start experiment", "stop experiment"],
    )

    logger.info("Created global start/stop markers")

    # ------------------------------------------------------------
    # BAND MAP (same structure as XDF)
    # ---------------------------------------------