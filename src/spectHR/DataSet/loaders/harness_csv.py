from __future__ import annotations

import numpy as np
import pandas as pd

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
    # READ CSV
    # ------------------------------------------------------------
    try:
        df = pd.read_csv(filename, sep=",")
    except Exception as exc:
        raise IOError(f"Failed to read Harness CSV: {filename}") from exc

    df.columns = df.columns.str.strip()

    if "ECG Data" not in df or "ms" not in df:
        raise ValueError("CSV does not match expected Harness format")

    physiodata.has_ecg = True

    # ------------------------------------------------------------
    # ECG VALUES
    # ------------------------------------------------------------
    ecg = df["ECG Data"].replace(-1, np.nan).astype("float32") * 40.0

    # ------------------------------------------------------------
    # TIMESTAMPS (ms → s, interpolate, resample)
    # ------------------------------------------------------------
    ms = df["ms"].replace(-1, np.nan).astype(float)
    ms = ms.interpolate(method="linear")

    times = ms.to_numpy(dtype=float) / 1000.0

    # ---- infer uniform sampling grid via median Δt ----
    diffs = np.diff(times[np.isfinite(times)])
    if len(diffs) == 0:
        raise ValueError("Invalid timestamps in Harness CSV")

    dt = float(np.median(diffs))
    n = len(times)

    times = np.arange(0.0, dt * n, dt, dtype=float)

    # ------------------------------------------------------------
    # POLARITY HEURISTIC (unchanged logic, safer slicing)
    # ------------------------------------------------------------
    if flip == "auto":
        n = len(ecg)
        i0 = n // 3
        i1 = 2 * n // 3

        seg = ecg.iloc[i0:i1]
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
        ecg.to_numpy(dtype=float),
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
