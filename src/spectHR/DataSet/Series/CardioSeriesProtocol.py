# spectHR/DataSet/Series/CardioSeriesProtocol.py
"""
Structural protocol shared by CardioSeries and CardioSeriesView.

The two real classes (``CardioSeries`` in ``CardioSeries.py`` and
``CardioSeriesView`` in ``CardioSeriesView.py``) implement the same data /
method surface, but they don't share an inheritance branch -- views are
composition-based and pull metric methods in via ``CardioMetricsMixin`` /
``CardioFrequencyMetricsMixin``.

``CardioSeriesLike`` lets us annotate functions that accept either, with
``isinstance()`` support thanks to ``@runtime_checkable``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from spectHR.DataSet.Series.CardioFrequencyMetricsMixin import PSDResult


@runtime_checkable
class CardioSeriesLike(Protocol):
    """
    Structural protocol satisfied by both ``CardioSeries`` and
    ``CardioSeriesView``.

    Use this as a type annotation wherever a function accepts either a full
    ``CardioSeries`` or an epoch / time-range view of one.

    Example
    -------
    >>> def compute_metrics(series: CardioSeriesLike) -> dict: ...
    """

    # --- core arrays -----------------------------------------------------

    @property
    def times(self) -> np.ndarray: ...

    @property
    def labels(self) -> np.ndarray: ...

    @property
    def ibi(self) -> np.ndarray: ...

    # --- private helper used by the metrics mixins -----------------------

    def _ibi_clean_ms(self) -> np.ndarray: ...

    # --- public spectral API (CardioFrequencyMetricsMixin) ---------------
    #
    # The real implementation accepts the active method (``"welch"``,
    # ``"lombscargle"``, ``"carspan"``, ``"carspan_strict"``); ``None``
    # picks the workspace default.

    def psd(
        self,
        method: Optional[str] = None,
        with_ci: bool = True,
    ) -> "PSDResult": ...

    def band_power(
        self,
        band_name: str,
        method: Optional[str] = None,
    ) -> float: ...

    # --- view construction -----------------------------------------------

    def view(self, starttime: float, endtime: float) -> "CardioSeriesLike": ...
