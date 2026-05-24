from __future__ import annotations

import csv

import numpy as np

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.loaders.registry import register_loader
from spectHR.DataSet.loaders._loader_utils import is_inverted_ecg
from spectHR.Tools.Logger import logger


# Sentinel value used by the Harness recording software to mark a missing
# sample.  Both the timestamp and the ECG columns may carry this value.
_MISSING_SENTINEL = -1

# Multiplicative scale factor applied to the raw ECG samples (Harness convention).
_ECG_SCALE = 40.0


@register_loader("._csv")
def load_harness_raw_csv(
    physiodata,
    filename: str,
    flip: str | bool = "auto",
    **kwargs,
) -> None:
    """
    Load raw ECG data from the Harness CSV format.

    Expected columns
    ----------------
    - ``ms``        — timestamp in milliseconds, ``-1`` for missing samples
    - ``ECG Data``  — raw ECG amplitude, ``-1`` for missing samples; the
                       reported value is scaled by ``_ECG_SCALE`` to recover
                       the physical amplitude.

    The timestamps are slightly irregular (acquisition jitter), so we
    rebuild them onto a uniform grid using the median sample interval
    after replacing the missing-sample sentinel with NaN.
    """

    logger.info(f"Loading raw Harness CSV: {filename}")

    # ------------------------------------------------------------
    # READ CSV
    # ------------------------------------------------------------
    try:
        with open(filename, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=",")
            cols = reader.fieldnames or []
            rows = list(reader)
    except (IOError, OSError, UnicodeDecodeError, csv.Error) as exc:
        raise IOError(f"Failed to read Harness CSV: {filename}") from exc

    if "ECG Data" not in cols or "ms" not in cols:
        raise ValueError("CSV does not match expected Harness format")

    # Pull the raw values out as floats *before* any scaling/conversion so
    # the missing-sample sentinel (-1) is still detectable.
    ms_raw  = np.array([r["ms"]       for r in rows], dtype=float)
    ecg_raw = np.array([r["ECG Data"] for r in rows], dtype=float)
    physiodata.has_ecg = True

    # ------------------------------------------------------------
    # ECG VALUES — replace sentinel, then apply Harness scale factor
    # ------------------------------------------------------------
    ecg = np.where(ecg_raw == _MISSING_SENTINEL, np.nan, ecg_raw) * _ECG_SCALE

    # ------------------------------------------------------------
    # TIMESTAMPS — replace sentinel, interpolate, build uniform grid
    # ------------------------------------------------------------
    ms = np.where(ms_raw == _MISSING_SENTINEL, np.nan, ms_raw)

    # Linearly interpolate any NaN gaps using neighbouring valid samples,
    # so the median Δt is computed from a clean monotonic series.
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

    # ---- infer uniform sampling grid via median Δt ----------------
    finite_diffs = np.diff(times_seconds[np.isfinite(times_seconds)])
    if finite_diffs.size == 0:
        raise ValueError("Invalid timestamps in Harness CSV")

    dt = float(np.median(finite_diffs))
    # Use an index-based arange so the grid length exactly matches the ECG
    # buffer; np.arange(0, dt*n, dt) can yield n-1 samples on float boundary.
    times = np.arange(ecg.size, dtype=float) * dt

    # ------------------------------------------------------------
    # POLARITY (shared heuristic with polar_csv.py)
    # ------------------------------------------------------------
    if flip == "auto":
        if is_inverted_ecg(ecg):
            ecg = -ecg
            logger.debug("Harness ECG: polarity heuristic triggered → flipped")
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

    physiodata.timeseries[ecg_name] = TimeSeries(times, ecg)
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
