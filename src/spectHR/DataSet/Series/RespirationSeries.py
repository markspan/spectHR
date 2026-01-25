# spectHR/DataSet/Series/RespirationSeries.py
from __future__ import annotations

from typing import Dict, Optional
import numpy as np
from dataclasses import dataclass
from typing import Iterable

from spectHR.Tools.Logger import logger


class RespirationSeries:
    """
    Container for respiration phase intervals derived from a respiration signal.

    Conceptual model
    ----------------
    A RespirationSeries represents *phase-based* structure extracted from a
    continuous respiration (RSP) TimeSeries.

    Each entry corresponds to a contiguous breathing phase:
        - inhalation ("INH")
        - exhalation ("EXH")

    Phases are represented as aligned arrays:
        - starts : phase start times (seconds)
        - ends   : phase end times (seconds)
        - labels : phase labels ("INH", "EXH")

    Times are expressed in dataset time base (seconds), consistent with
    TimeSeries and CardioSeries.

    Design parallels
    ----------------
    - Comparable to CardioSeries (event/interval-derived, not continuous)
    - Not a replacement for TimeSeries
    - Suitable for epoch slicing, phase-locked analyses, and plotting
    """

    def __init__(
        self,
        starts: np.ndarray,
        ends: np.ndarray,
        labels: np.ndarray,
    ):
        self.starts = np.asarray(starts, dtype=float)
        self.ends = np.asarray(ends, dtype=float)
        self.labels = np.asarray(labels, dtype=object)
        self._pd = None
        self._stream = None

        if not (self.starts.size == self.ends.size == self.labels.size):
            raise ValueError("starts, ends, and labels must have equal length")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_timeseries(
        cls,
        rsp,
        *,
        min_phase_duration: float = 0.3,
        smooth: bool = True,
        smoothing_window: int = 5,
    ) -> "RespirationSeries":
        """
        Derive inhalation and exhalation phases from a respiration TimeSeries.

        Parameters
        ----------
        rsp:
            Respiration TimeSeries providing:
                - rsp.times  : 1D array of timestamps (seconds)
                - rsp.values : 1D array of respiration samples
        min_phase_duration:
            Minimum allowed duration (seconds) for a phase.
            Shorter phases are discarded as noise.
        smooth:
            If True, apply light smoothing before differentiation.
        smoothing_window:
            Window length (samples) for moving-average smoothing.
            Must be odd.

        Returns
        -------
        RespirationSeries
            Series containing inhalation and exhalation phases.

        Notes
        -----
        - Phase boundaries are detected using zero-crossings of the
          first derivative (velocity-based segmentation).
        - This is robust to baseline drift and amplitude scaling.
        - Phase type is determined by the *mean derivative sign*
          within each interval.
        """
        times = np.asarray(rsp.times, dtype=float)
        values = np.asarray(rsp.values, dtype=float)

        if times.size < 3:
            logger.warning("RSP TimeSeries too short for respiration phase extraction.")
            return cls([], [], [])

        # ------------------------------------------------------------
        # Optional smoothing
        # ------------------------------------------------------------
        y = values.copy()

        if smooth and smoothing_window >= 3:
            if smoothing_window % 2 == 0:
                raise ValueError("smoothing_window must be odd")

            kernel = np.ones(smoothing_window, dtype=float) / smoothing_window
            y = np.convolve(y, kernel, mode="same")

        # ------------------------------------------------------------
        # First derivative (respiratory velocity)
        # ------------------------------------------------------------
        dt = np.diff(times)
        dt[dt <= 0] = np.nan  # guard against non-monotonic timestamps

        dy = np.diff(y)
        velocity = dy / dt

        # Align velocity to sample indices
        velocity = np.concatenate(([velocity[0]], velocity))

        # ------------------------------------------------------------
        # Detect zero-crossings of velocity
        # ------------------------------------------------------------
        sign = np.sign(velocity)
        sign[sign == 0] = np.nan

        crossings = np.where(np.diff(sign) != 0)[0] + 1

        if crossings.size < 2:
            logger.warning("No respiration phase boundaries detected.")
            return cls([], [], [])

        # ------------------------------------------------------------
        # Build phases
        # ------------------------------------------------------------
        starts: list[float] = []
        ends: list[float] = []
        labels: list[str] = []

        for i in range(len(crossings) - 1):
            i0 = crossings[i]
            i1 = crossings[i + 1]

            t0 = times[i0]
            t1 = times[i1]

            duration = t1 - t0
            if duration < min_phase_duration:
                continue

            mean_velocity = np.nanmean(velocity[i0:i1])

            label = "INH" if mean_velocity > 0 else "EXH"

            starts.append(t0)
            ends.append(t1)
            labels.append(label)

        if not starts:
            logger.warning("All detected respiration phases rejected by duration threshold.")
            return cls([], [], [])

        return cls(
            np.asarray(starts, dtype=float),
            np.asarray(ends, dtype=float),
            np.asarray(labels, dtype=object),
        )

    # ------------------------------------------------------------------
    # Convenience / inspection
    # ------------------------------------------------------------------

    def as_dict(self) -> Dict[str, np.ndarray]:
        """
        Return respiration phases grouped by label.

        Returns
        -------
        dict
            Keys:
                - "INH"
                - "EXH"
            Values:
                Nx2 arrays of (start, end) times.
        """
        grouped: Dict[str, list] = {"INH": [], "EXH": []}
        for s, e, lab in zip(self.starts, self.ends, self.labels):
            grouped[lab].append((s, e))

        return {k: np.asarray(v, dtype=float) for k, v in grouped.items()}

    def __len__(self) -> int:
        return int(self.starts.size)

    def __repr__(self) -> str:
        return f"RespirationSeries(n={len(self)})"
    
    def view(self, starttime: float, endtime: float) -> RespirationSeriesView:
        idx = np.where(
            (self.starts >= starttime) & (self.ends <= endtime)
        )[0]
        view = RespirationSeriesView(self, idx)
        view._pd = self._pd
        view._stream = self._stream
        view._epoch = None
        return view

class RespirationSeriesView(RespirationSeries):
    """
    Zero-copy view into a parent RespirationSeries.

    A RespirationSeriesView does not own phase data. Instead, it references
    a subset of phases from a parent RespirationSeries using integer indices.

    Identity metadata
    -----------------
    Views may carry optional metadata for downstream logic and UI:
        - _pd     : PhysioData linkage (propagated from parent)
        - _stream : originating band / stream identifier
        - _epoch  : epoch label if produced via epoch slicing

    Notes
    -----
    - Mutations to the parent RespirationSeries are reflected in the view.
    - View methods never modify the parent.
    """

    def __init__(self, parent: RespirationSeries, indices: np.ndarray):
        self._parent = parent
        self._idx = np.asarray(indices, dtype=int)

        # Identity metadata (propagated)
        self._pd = getattr(parent, "_pd", None)
        self._stream = getattr(parent, "_stream", None)
        self._epoch: Optional[str] = None

    # ------------------------------------------------------------------
    # Array views
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
        """
        Create a sub-view by time range.

        Parameters
        ----------
        starttime:
            Start time in seconds (inclusive).
        endtime:
            End time in seconds (inclusive).

        Returns
        -------
        RespirationSeriesView
            Sub-view referencing the same parent RespirationSeries.
        """
        mask = (self.starts >= starttime) & (self.ends <= endtime)
        sub = RespirationSeriesView(self._parent, self._idx[mask])
        sub._pd = self._pd
        sub._stream = self._stream
        sub._epoch = None
        return sub

    def __getitem__(self, epoch_label: str) -> "RespirationSeriesView":
        """
        Return an epoch-restricted view using PhysioData.epochs.

        Parameters
        ----------
        epoch_label:
            Name/key of the epoch in `self._pd.epochs`.

        Returns
        -------
        RespirationSeriesView
            View containing phases fully inside the epoch.

        Raises
        ------
        RuntimeError
            If this RespirationSeriesView is not linked to PhysioData.
        KeyError
            If the requested epoch does not exist.
        """
        if self._pd is None:
            raise RuntimeError(
                "RespirationSeriesView is not connected to PhysioData."
            )
        if epoch_label not in self._pd.epochs:
            raise KeyError(f"No epoch '{epoch_label}' in PhysioData.")

        ep = self._pd.epochs[epoch_label]
        mask = (self.starts >= ep.start) & (self.ends <= ep.end)

        view = RespirationSeriesView(self._parent, self._idx[mask])
        view._pd = self._pd
        view._stream = self._stream
        view._epoch = epoch_label
        return view

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
