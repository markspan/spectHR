from __future__ import annotations

import numpy as np
import pandas as pd

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
    # READ CSV
    # ------------------------------------------------------------
    try:
        df = pd.read_csv(filename, sep=";")
    except Exception as exc:
        raise IOError(f"Failed to read Polar CSV: {filename}") from exc

    if "ecg [uV]" not in df or "timestamp [ms]" not in df:
        raise ValueError("CSV does not look like a Polar raw ECG export")

    times = df["timestamp [ms]"].to_numpy(dtype=float) / 1000.0
    values = df["ecg [uV]"].to_numpy(dtype=float)
    diffs = np.diff(times)
    fs = 1.0 / np.mean(diffs[diffs > 0])

    physiodata.has_ecg = True

    # ------------------------------------------------------------
    # POLARITY HEURISTIC (same logic, safer indexing)
    # ------------------------------------------------------------
    if flip == "auto":
        n = len(values)
        i0 = n // 3
        i1 = 2 * n // 3

        seg = values[i0:i1]
        magic = abs(seg.mean() - seg.min()) / abs(seg.mean() - seg.max())

        logger.debug(f"ECG polarity heuristic (magic={magic:.3f})")

        if magic > 1.5:
            values = -values

    elif flip is True:
        values = -values

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
    # ------------------------------------------------------------
    physiodata.band_map = {
        band_id: {
            "ecg": ecg_name,
        }
    }
    physiodata.active_band = band_id
