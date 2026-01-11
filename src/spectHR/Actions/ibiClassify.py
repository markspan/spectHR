from __future__ import annotations

from typing import Any

import numpy as np

from spectHR.Actions.BaseAction import BaseAction
from spectHR.DataSet.Series.CardioSeries import CardioSeries, CardioSeriesView
from spectHR.Tools.Logger import logger


class IBIClassify(BaseAction):
    """
    Classify IBIs in an CardioSeries (or view) using statistical thresholds.

    Labels
    ------
    - "N"   : normal
    - "L"   : long IBI
    - "S"   : short IBI
    - "TL"  : too long (> Tmax)
    - "SL"  : short-then-long sequence
    - "SNS" : short-normal-short sequence
    - "T"   : IBI == 0 or NaN (degenerate)
    """

    @classmethod
    def apply(
        cls,
        target: Any,
        *,
        Tw: int = 51,
        Nsd: float = 4.0,
        Tmax: float = 5.0,
    ) -> None:
        """
        Parameters
        ----------
        target : CardioSeries | CardioSeriesView
            Object whose IBI array will be classified in-place.
        Tw : int
            Rolling window width (number of IBIs).
        Nsd : float
            SD multiplier for upper/lower bounds.
        Tmax : float
            Maximum acceptable IBI value (seconds).
        """
        if not isinstance(target, (CardioSeries, CardioSeriesView)):
            raise TypeError("ibiClassify must be applied to CardioSeries (or CardioSeriesView).")

        ibi = target.ibi.copy()

        n = len(ibi)
        labels = target._parent.labels if isinstance(target, CardioSeriesView) else target.labels

        # Treat degenerate IBIs
        bad_mask = np.isnan(ibi) | (ibi <= 0)
        labels[bad_mask] = "T"

        # Rolling mean/std with truncated windows
        pad = Tw // 2
        ibi_padded = np.pad(ibi, (pad, pad), mode="edge")
        windows = np.lib.stride_tricks.sliding_window_view(ibi_padded, Tw)

        avIBIr = np.nanmean(windows, axis=1)
        SDavIBIr = np.nanstd(windows, axis=1)

        avIBIr = avIBIr[:n]
        SDavIBIr = SDavIBIr[:n]

        lower = avIBIr - Nsd * SDavIBIr
        higher = avIBIr + Nsd * SDavIBIr

        # Initial label assignment
        for i in range(n):
            if np.isnan(ibi[i]) or ibi[i] <= 0:
                continue
            if ibi[i] > higher[i]:
                labels[i] = "L"
            elif ibi[i] < lower[i]:
                labels[i] = "S"
            elif ibi[i] > Tmax:
                labels[i] = "TL"
            else:
                # If not already flagged bad or special, keep or reset to N
                if labels[i] not in ("L", "S", "TL", "SL", "SNS", "T"):
                    labels[i] = "N"

        # Sequence-based patterns
        Nlabels = len(labels)

        # Short-then-Long
        for i in range(Nlabels - 1):
            if labels[i] == "S" and labels[i + 1] == "L":
                labels[i] = "SL"

        # Short-Normal-Short
        for i in range(Nlabels - 2):
            if labels[i] == "S" and labels[i + 1] == "N" and labels[i + 2] == "S":
                labels[i] = "SNS"

        # Logging summary
        unique, counts = np.unique(labels, return_counts=True)
        summary = dict(zip(unique, counts))
        logger.info(f"IBI classification summary (n_IBI={n}):")
        for lab, cnt in summary.items():
            logger.info(f"    {lab}: {cnt}")


def ibiClassify(target: Any, **kwargs: Any) -> None:
    """Convenience wrapper around IBIClassify.apply()."""
    IBIClassify.apply(target, **kwargs)
