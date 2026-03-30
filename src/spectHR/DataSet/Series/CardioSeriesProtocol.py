# spectHR/DataSet/Series/CardioSeriesProtocol.py
from __future__ import annotations

from typing import Tuple, runtime_checkable
from typing import Protocol

import numpy as np


@runtime_checkable
class CardioSeriesLike(Protocol):
    """
    Structural protocol satisfied by both CardioSeries and CardioSeriesView.

    Use this as a type annotation wherever a function accepts either a full
    CardioSeries or an epoch/time-range view of one.  Because the protocol is
    @runtime_checkable, isinstance() checks also work at runtime.

    Example
    -------
    def compute_metrics(series: CardioSeriesLike) -> dict: ...
    """

    @property
    def times(self) -> np.ndarray: ...

    @property
    def labels(self) -> np.ndarray: ...

    @property
    def ibi(self) -> np.ndarray: ...

    def _ibi_clean_ms(self) -> np.ndarray: ...

    def welch_psd(self, **kwargs) -> Tuple[np.ndarray, np.ndarray]: ...

    def view(self, starttime: float, endtime: float) -> "CardioSeriesLike": ...
