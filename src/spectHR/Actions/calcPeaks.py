from __future__ import annotations

from typing import Any, Tuple

import numpy as np
import scipy.signal as signal

from spectHR.Actions.BaseAction import BaseAction
from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.Actions.ibiClassify import ibiClassify
from spectHR.Tools.Logger import logger


class CalcPeaks(BaseAction):
    """
    Band-aware R-peak detection.

    This action always operates on the *currently active ECG band*
    as defined by physiodata.active_band.

    HRV storage model
    -----------------
    physiodata.hrv_map : dict[str, CardioSeries]
        One CardioSeries per ECG band.

    Behaviour
    ---------
    - First call for a band creates a new CardioSeries
    - Subsequent calls replace peaks only inside the target window
    - Epoch-aware replacement is preserved
    """

    @classmethod
    def apply(
        cls,
        target: Any,
        *,
        min_peak_distance_ms: float = 300.0,
        classify: bool = True,
    ) -> CardioSeries:
        """
        Detect R-peaks on the active ECG band.

        Parameters
        ----------
        target
            PhysioData, StreamAccessor, TimeSeries or TimeSeriesView
        min_peak_distance_ms
            Minimum distance between peaks
        classify
            Whether to run ibiClassify afterwards

        Returns
        -------
        CardioSeries
            The band-specific HRV series
        """

        ts, physiodata = cls.resolve_timeseries(target)

        if physiodata is None:
            raise RuntimeError("calcPeaks requires PhysioData context")

        if physiodata.active_band is None:
            raise RuntimeError("No active ECG band selected")

        band = physiodata.active_band

        # Ensure HRV storage exists
        if not hasattr(physiodata, "hrv_map"):
            physiodata.hrv_map = {}

        # --------------------------------------------------
        # Sampling rate estimation
        # --------------------------------------------------
        times = ts.times
        values = ts.values

        diffs = np.diff(times)
        diffs = diffs[diffs > 0]
        if diffs.size == 0:
            raise ValueError("Cannot estimate sampling rate")

        srate = 1.0 / np.mean(diffs)

        # --------------------------------------------------
        # Peak detection
        # --------------------------------------------------
        min_samples = int((min_peak_distance_ms / 1000.0) * srate)
        threshold = float(np.median(values) + 1.5 * np.std(values))

        locs, _ = signal.find_peaks(
            values,
            height=threshold,
            distance=min_samples,
        )

        if locs.size == 0:
            logger.warning(f"No R-peaks found for band '{band}'")
            return physiodata.hrv_map.get(
                band, CardioSeries(np.array([], dtype=float))
            )

        # --------------------------------------------------
        # Sub-sample peak timing correction
        # --------------------------------------------------
        pre = values[np.clip(locs - 1, 0, len(values) - 1)]
        post = values[np.clip(locs + 1, 0, len(values) - 1)]
        vals = values[locs]

        rc = np.maximum(np.abs(vals - pre), np.abs(post - vals))
        rc[rc == 0] = 1e-12

        correction = (post - pre) / srate / (2.0 * rc)
        new_times = times[locs] + correction

        # --------------------------------------------------
        # Determine replacement window
        # --------------------------------------------------
        vmin, vmax = cls._infer_view_bounds(ts, new_times)

        # --------------------------------------------------
        # First HRV for this band
        # --------------------------------------------------
        if band not in physiodata.hrv_map:
            hrv = CardioSeries(new_times)
            hrv._pd = physiodata
            physiodata.hrv_map[band] = hrv

            if classify:
                ibiClassify(hrv)

            logger.info(
                f"Detected {len(hrv.times)} R-peaks for band '{band}'"
            )
            return hrv

        # --------------------------------------------------
        # Replace peaks inside window
        # --------------------------------------------------
        hrv = physiodata.hrv_map[band]

        keep = (hrv.times < vmin) | (hrv.times > vmax)

        kept_times = hrv.times[keep]
        kept_labels = hrv.labels[keep]

        new_labels = np.full(new_times.shape, "N", dtype=object)

        all_times = np.concatenate([kept_times, new_times])
        all_labels = np.concatenate([kept_labels, new_labels])

        order = np.argsort(all_times)

        hrv.times = all_times[order]
        hrv.labels = all_labels[order]

        if classify:
            ibiClassify(hrv)

        logger.info(
            f"Updated R-peaks for band '{band}' "
            f"in [{vmin:.3f}, {vmax:.3f}] "
            f"(n={len(hrv.times)})"
        )

        return hrv

    # --------------------------------------------------
    @staticmethod
    def _infer_view_bounds(
        ts: Any,
        fallback_times: np.ndarray,
    ) -> Tuple[float, float]:
        """
        Infer the time window to replace peaks in.
        """

        if hasattr(ts, "_epoch_start") and hasattr(ts, "_epoch_end"):
            return float(ts._epoch_start), float(ts._epoch_end)

        if hasattr(ts, "starttime") and hasattr(ts, "endtime"):
            return float(ts.starttime), float(ts.endtime)

        return float(fallback_times.min()), float(fallback_times.max())


def calcPeaks(target: Any, **kwargs: Any) -> CardioSeries:
    """
    Convenience wrapper for CalcPeaks.apply.
    """
    return CalcPeaks.apply(target, **kwargs)
