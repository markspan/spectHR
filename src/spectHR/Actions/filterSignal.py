from __future__ import annotations

from typing import Any

import scipy.signal as signal

from spectHR.Actions.BaseAction import BaseAction
from spectHR.DataSet.Series.TimeSeries import TimeSeries, TimeSeriesView
from spectHR.DataSet.PhysioData import StreamAccessor
from spectHR.Tools.Logger import logger

class FilterSignal(BaseAction):
    """
    Apply simple IIR filtering to a TimeSeries.

    Supports targets
    ----------------
    - TimeSeries
    - TimeSeriesView
    - StreamAccessor

    Notes
    -----
    This does NOT operate on PhysioData directly.
    """

    @classmethod
    def apply(
        cls,
        target: Any,
        *,
        filter_type: str = "highpass",
        cutoff: float = 0.1,
        order: int | None = None,
    ) -> TimeSeries:
        """
        Parameters
        ----------
        target : TimeSeries | TimeSeriesView | StreamAccessor
        filter_type : {"lowpass", "highpass"}
            Type of Butterworth filter.
        cutoff : float
            Cutoff frequency (Hz).
        order : int | None
            If None, an order is estimated via buttord; otherwise used directly.

        Returns
        -------
        TimeSeries
            The underlying TimeSeries (modified in place).
        """
        if not isinstance(target, (TimeSeries, TimeSeriesView, StreamAccessor)):
            raise TypeError(
                "FilterSignal only supports TimeSeries, TimeSeriesView, or StreamAccessor targets."
            )

        ts, _ = cls.resolve_timeseries(target)
        srate = ts.srate
        if srate is None:
            raise ValueError("Cannot filter TimeSeries with unknown sampling rate.")

        nyq = 0.5 * srate
        norm_cutoff = cutoff / nyq

        if order is None:
            # Design with a slightly wider passband and narrower stopband
            passband = norm_cutoff * 1.1
            stopband = norm_cutoff / 1.5
            N, wn = signal.buttord(passband, stopband, 1, 5)
        else:
            N = order
            wn = norm_cutoff

        btype = "low" if filter_type == "lowpass" else "high"
        b, a = signal.butter(N, wn, btype=btype, analog=False)

        logger.info(
            f"Filtering signal with {btype} Butterworth filter: "
            f"N={N}, cutoff={cutoff} Hz, srate={srate:.2f} Hz."
        )

        # Filter in-place
        ts.values[:] = signal.filtfilt(b, a, ts.values.astype(float))
        return ts


def filterSignal(target: Any, **kwargs: Any) -> TimeSeries:
    """Convenience wrapper for FilterSignal.apply()."""
    return FilterSignal.apply(target, **kwargs)
