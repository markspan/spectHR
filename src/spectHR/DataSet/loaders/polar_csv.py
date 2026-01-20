from __future__ import annotations

import csv
import numpy as np

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.loaders.registry import register_loader
from spectHR.Tools.Logger import logger


@register_loader(".txt")
def load_polar_raw_csv(
    physiodata, filename: str, flip: str | bool = "auto", **kwargs
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
    # READ CSV (stdlib)
    # ------------------------------------------------------------
    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        fieldnames = [c.strip() for c in reader.fieldnames or []]

        if "timestamp [ms]" not in fieldnames or "ecg [uV]" not in fieldnames:
            raise ValueError("CSV does not look like a Polar raw ECG export")

        rows = list(reader)

    if not rows:
        raise ValueError("Empty Polar ECG file")

    physiodata.has_ecg = True

    # ------------------------------------------------------------
    # EXTRACT COLUMNS
    # ------------------------------------------------------------
    def parse_float(x):
        try:
            return float(x)
        except Exception:
            return np.nan

    times = (
        np.array(
            [parse_float(r["timestamp [ms]"]) for r in rows],
            dtype=float,
        )
        / 1000.0
    )

    values = np.array(
        [parse_float(r["ecg [uV]"]) for r in rows],
        dtype=float,
    )

    # ------------------------------------------------------------
    # BASIC SAMPLING CHECK (kept for parity / debugging)
    # ------------------------------------------------------------
    diffs = np.diff(times)
    valid = diffs > 0
    if not np.any(valid):
        raise ValueError("Invalid timestamps in Polar ECG file")

    fs = 1.0 / np.mean(diffs[valid])
    logger.debug(f"Inferred ECG sampling rate: {fs:.2f} Hz")

    # ------------------------------------------------------------
    # POLARITY HEURISTIC
    # ------------------------------------------------------------
    if flip == "auto":
        n = len(values)
        i0 = n // 3
        i1 = 2 * n // 3

        seg = values[i0:i1]
        seg = seg[np.isfinite(seg)]

        if seg.size:
            magic = abs(seg.mean() - seg.min()) / abs(seg.mean() - seg.max())
            logger.debug(f"ECG polarity heuristic (magic={magic:.3f})")

            if magic > 1.5:
                values = -values

    elif flip is True:
        values = -values

    # ------------------------------------------------------------
    # TIMESERIES
    # ------------------------------------------------------------
    band_id = "polar_raw"
    ecg_name = f"ecg-[{band_id}]"

    physiodata.timeseries[ecg_name] = TimeSeries(
        times,
        values,
    )

    logger.info(f"Loaded ECG → {ecg_name}")

    # ------------------------------------------------------------
    # EVENTS (global start / stop)
    # ------------------------------------------------------------
    physiodata.events["markers"] = EventSeries(
        times=np.array([times[0], times[-1]], dtype=float),
        labels=["start experiment", "stop experiment"],
    )

    logger.info("Created global start/stop markers")

    # ------------------------------------------------------------
    # BAND MAP
    # ------------------------------------------------------------
    physiodata.band_map = {
        band_id: {
            "ecg": ecg_name,
        }
    }
    physiodata.active_band = band_id
