# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
# spectHR/DataSet/Series/CardioSeriesProtocol.py
"""
Structural protocol shared by CardioSeries and CardioSeriesView.

CardioSeriesLike lets functions (PSDEngine, Profile, analysis metrics)
accept either a full CardioSeries or an epoch / time-range view of one,
with isinstance() support thanks to @runtime_checkable.

What belongs here
-----------------
Only members *actually called* by algorithm code (PSDEngine, Profile,
spectHR.analysis functions) belong in this protocol.  Public-API methods
such as psd() and band_power() are provided by CardioMetricsMixin and are
not part of the structural contract that algorithm modules depend on.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Tuple, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from spectHR.Tools.PSD._psd_utils import PSDResult
    from spectHR.Tools.PSD._psd_config import MeanConvention


@runtime_checkable
class CardioSeriesLike(Protocol):
    """Structural protocol satisfied by both CardioSeries and CardioSeriesView.

    Use this as a type annotation wherever a function accepts either.

    Example
    -------
    >>> def compute_metrics(series: CardioSeriesLike) -> dict: ...
    """

    # --- core data arrays ------------------------------------------------

    @property
    def times(self) -> np.ndarray:
        """R-peak timestamps in seconds."""
        ...

    @property
    def labels(self) -> np.ndarray:
        """Per-beat label array ("N", "TL", "S", ...)."""
        ...

    @property
    def ibi(self) -> np.ndarray:
        """Inter-beat intervals in seconds, trailing NaN for alignment."""
        ...

    # --- PSD engine duck-typed helpers -----------------------------------
    # Called by PSDEngine; implemented as thin wrappers in CardioMetricsMixin.

    def _ibi_clean_pairs(self) -> Tuple[np.ndarray, np.ndarray]:
        """Aligned (times_s, ibi_ms) with artefact intervals removed.
        Used by Welch and Lomb-Scargle PSD back-ends.
        """
        ...

    def _event_times_clean(self) -> np.ndarray:
        """R-peak timestamps with artefact-labelled beats removed.
        Used by the CARSPAN event-series PSD path.
        """
        ...

    def _mean_ibi_ms(self) -> float:
        """Mean IBI in ms under the T/N harmonic convention."""
        ...

    def _mean_ibi_ms_arithmetic(self) -> float:
        """Mean IBI in ms under CARSPAN arithmetic-mean-of-rate convention."""
        ...

    def _mmi2_factor(self, mean_convention: "MeanConvention") -> float:
        """mean_ibi_ms squared - the mMI2 unit-conversion multiplier."""
        ...

    # --- view construction -----------------------------------------------
    # Called by Profile.py and metric_table_epoch.

    def view(self, starttime: float, endtime: float) -> "CardioSeriesLike":
        """Return a zero-copy view restricted to [starttime, endtime]."""
        ...
