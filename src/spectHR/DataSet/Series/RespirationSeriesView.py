# spectHR/DataSet/Series/RespirationSeriesView.py
from __future__ import annotations

from typing import TYPE_CHECKING, Optional
import numpy as np

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData
    from spectHR.DataSet.Series.RespirationSeries import RespirationSeries


class RespirationSeriesView:
    """
    Zero-copy view into a parent RespirationSeries.

    Uses composition: holds a reference to the parent and an index array.
    Does NOT inherit from RespirationSeries — it cannot own data or call
    from_timeseries.  Methods that only make sense on the full series are
    deliberately absent.

    Mutations to the parent RespirationSeries are reflected in the view.
    View methods never modify the parent.

    Identity metadata
    -----------------
    _pd     : PhysioData linkage (propagated from parent)
    _stream : band / stream identifier
    _epoch  : epoch label (set when produced by epoch slicing)
    """

    def __init__(self, parent: "RespirationSeries", indices: np.ndarray) -> None:
        self._parent = parent
        self._idx = np.asarray(indices, dtype=int)
        self._pd: Optional["PhysioData"] = getattr(parent, "_pd", None)
        self._stream: Optional[str] = getattr(parent, "_stream", None)
        self._epoch: Optional[str] = None

    # ------------------------------------------------------------------
    # Data interface — composition, not ownership
    # ------------------------------------------------------------------

    @property
    def starts(self) -> np.ndarray:
        """View of parent phase start times (seconds)."""
        return self._parent.starts[self._idx]

    @property
    def ends(self) -> np.ndarray:
        """View of parent phase end times (seconds)."""
        return self._parent.ends[self._idx]

    @property
    def labels(self) -> np.ndarray:
        """View of parent phase labels."""
        return self._parent.labels[self._idx]

    # ------------------------------------------------------------------
    # Slicing
    # ------------------------------------------------------------------

    def view(self, starttime: float, endtime: float) -> "RespirationSeriesView":
        """Create a sub-view restricted to phases within [starttime, endtime]."""
        mask = (self.starts >= starttime) & (self.ends <= endtime)
        sub = RespirationSeriesView(self._parent, self._idx[mask])
        sub._pd = self._pd
        sub._stream = self._stream
        sub._epoch = None
        return sub

    def __getitem__(self, epoch_label: str) -> "RespirationSeriesView":
        """
        Return an epoch-restricted view using PhysioData.epochs.

        Raises
        ------
        RuntimeError
            If not linked to a PhysioData instance.
        KeyError
            If the requested epoch does not exist.
        """
        if self._pd is None:
            raise RuntimeError("RespirationSeriesView is not connected to PhysioData.")
        if epoch_label not in self._pd.epochs:
            raise KeyError(f"No epoch '{epoch_label}' in PhysioData.")
        ep = self._pd.epochs[epoch_label]
        mask = (self.starts >= ep.start) & (self.ends <= ep.end)
        v = RespirationSeriesView(self._parent, self._idx[mask])
        v._pd = self._pd
        v._stream = self._stream
        v._epoch = epoch_label
        return v

    # ------------------------------------------------------------------
    # Aggregate measures
    # ------------------------------------------------------------------

    def mean_breath_frequency_hz(self) -> Optional[float]:
        """Mean breathing frequency inside this view, in Hz.

        Pairs each phase with its successor (INH->EXH or EXH->INH)
        into a full breath cycle and averages ``1 / cycle_period``.
        With ``N`` phases in the view this produces ``N-1`` cycle
        estimates, which is the most data-efficient unbiased
        estimator on the alternating phase sequence built by
        :meth:`RespirationSeries.from_timeseries`.

        Equivalent to CARSPAN's ``1 / LProfile.MeanIn`` used in
        ``RunProfileSommation`` (``T_AnaFunctions.pas`` 2944-2952)
        when the input signal is ``RespPeriod``. spectHR does not
        carry a ``RespPeriod`` series, so we derive the same number
        directly from the phase-segmented respiration signal.

        Returns
        -------
        float or None
            The mean breath frequency in Hz, or ``None`` when fewer
            than two phases fall inside the view (no full cycle
            could be reconstructed). Also returns ``None`` if every
            paired cycle came out non-positive (degenerate data).
        """
        n = int(self._idx.size)
        if n < 2:
            return None
        starts = self.starts
        ends = self.ends
        # One cycle per adjacent (INH+EXH) or (EXH+INH) pair.
        # Cycle duration = end of the second phase - start of the first.
        cycle_periods = ends[1:] - starts[:-1]
        cycle_periods = cycle_periods[cycle_periods > 0]
        if cycle_periods.size == 0:
            return None
        return float(1.0 / np.mean(cycle_periods))

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return int(self._idx.size)

    def __repr__(self) -> str:
        return (
            f"RespirationSeriesView("
            f"n={len(self)}, "
            f"stream={self._stream!r}, "
            f"epoch={self._epoch!r})"
        )
