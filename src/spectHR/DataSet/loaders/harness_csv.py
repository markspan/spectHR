from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.loaders.registry import register_loader
from spectHR.Tools.Logger import logger


@register_loader("._csv")
def load_harness_raw_csv(
    physiodata,
    filename: str,
    flip: str | bool = "auto",
    **kwargs,
) -> None:
    """
    Load raw ECG data from the new Harness CSV format.

    Expected columns:
        - 'ms'
        - 'ECG Data'

    Characteristics:
        - Missing samples encoded as -1
        - ECG scaled by factor 40
        - Irregular timestamps → resampled using median Δt
    """

    logger.info(f"Loading raw Harness CSV: {filename}")

    # ------------------------------------------------------------
    # READ CSV (stdlib)
    # ------------------------------------------------------------
    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = [c.strip() for c in reader.fieldnames or []]

        if "ECG Data" not in fieldnames or "ms" not in fieldnames:
            raise ValueError("CSV does not match expected Harness format")

        rows = list(reader)

    physiodata.has_ecg = True

    # ------------------------------------------------------------
    # EXTRACT COLUMNS
    # ------------------------------------------------------------
    def parse_float(x):
        try:
            v = float(x)
            return np.nan if v == -1 else v
        except Exception:
            return np.nan

    ecg = (
        np.array(
            [parse_float(r["ECG Data"]) for r in rows],
            dtype=float,
        )
        * 40.0
    )

    ms = np.array(
        [parse_float(r["ms"]) for r in rows],
        dtype=float,
    )

    # ------------------------------------------------------------
    # INTERPOLATE TIMESTAMPS (linear)
    # ------------------------------------------------------------
    valid = np.isfinite(ms)
    if not np.any(valid):
        raise ValueError("Invalid timestamps in Harness CSV")

    ms_interp = np.copy(ms)
    ms_interp[~valid] = np.interp(
        np.flatnonzero(~valid),
        np.flatnonzero(valid),
        ms[valid],
    )

    times = ms_interp / 1000.0

    # ---- infer uniform sampling grid via median Δt ----
    diffs = np.diff(times[np.isfinite(times)])
    if diffs.size == 0:
        raise ValueError("Invalid timestamps in Harness CSV")

    dt = float(np.median(diffs))
    n = len(times)
    times = np.arange(0.0, dt * n, dt, dtype=float)

    # ------------------------------------------------------------
    # POLARITY HEURISTIC
    # ------------------------------------------------------------
    if flip == "auto":
        n = len(ecg)
        i0 = n // 3
        i1 = 2 * n // 3

        seg = ecg[i0:i1]
        seg = seg[np.isfinite(seg)]

        if seg.size:
            magic = abs(seg.mean() - seg.min()) / abs(seg.mean() - seg.max())
            logger.debug(f"ECG polarity heuristic (magic={magic:.3f})")

            if magic > 1.5:
                ecg = -ecg

    elif flip is True:
        ecg = -ecg

    # ------------------------------------------------------------
    # MEAN CENTER
    # ------------------------------------------------------------
    ecg = ecg - np.nanmean(ecg)

    # ------------------------------------------------------------
    # TIMESERIES
    # ------------------------------------------------------------
    band_id = "harness_raw"
    ecg_name = f"ecg-[{band_id}]"

    physiodata.timeseries[ecg_name] = TimeSeries(
        times,
        ecg,
    )

    logger.info(f"Loaded ECG → {ecg_name}")

    # ------------------------------------------------------------
    # EVENTS (global start / stop)
    # ------------------------------------------------------------
    physiodata.events["markers"] = EventSeries(
        times=np.array([times[0], times[-1]], dtype=float),
        labels=["start experiment", "stop experiment"],
    )

    # ------------------------------------------------------------
    # BAND MAP
    # ------------------------------------------------------------
    physiodata.band_map = {
        band_id: {
            "ecg": ecg_name,
        }
    }
    physiodata.active_band = band_id
