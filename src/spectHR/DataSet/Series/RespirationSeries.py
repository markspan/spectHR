# spectHR/DataSet/Series/RespirationSeries.py
from __future__ import annotations

from typing import Dict, Optional
import numpy as np

from spectHR.Tools.Logger import logger
from scipy.signal import butter, sosfiltfilt, savgol_filter, find_peaks, buttord


class RespirationSeries:
    """
    Container for respiration phase intervals derived from a respiration signal.

    Conceptual model
    ----------------
    A RespirationSeries represents *phase-based* structure extracted from a
    continuous respiration (RSP) TimeSeries. Each entry corresponds to a
    contiguous breathing phase:
    - inhalation ("INH")
    - exhalation ("EXH")

    Phases are represented as aligned arrays:
    - starts : phase start times (seconds)
    - ends   : phase end times (seconds)
    - labels : phase labels ("INH", "EXH")

    Times are expressed in dataset time base (seconds), consistent with
    TimeSeries and CardioSeries.

    Relationship to views
    ---------------------
    RespirationSeries.view() returns a RespirationSeriesView. Views do NOT
    inherit from RespirationSeries — they use composition. There is no shared
    base class; both satisfy the same structural interface (duck typing).
    """

    def __init__(
        self,
        starts: np.ndarray,
        ends: np.ndarray,
        labels: np.ndarray,
    ) -> None:
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
        prefilter_cutoff_hz: float = 2,
        prefilter_order: int | None = None,
        min_phase_duration: float = 2,
        smooth: bool = True,
        smoothing_window: int = 31,
        polyorder: int = 3,
        prominence: float | None = None,
        prominence_rel: float = 0.55,
        min_amplitude: float | None = None,
    ) -> "RespirationSeries":
        """
        Robust inhale/exhale segmentation using extrema (troughs/peaks).

        Pipeline
        --------
        0) Low-pass filter raw signal at prefilter_cutoff_hz (default 2 Hz)
        1) Optional Savitzky-Golay smoothing (preserves extrema well)
        2) Detect peaks and troughs using prominence + minimum distance
        3) Enforce alternation of extrema
        4) Build phases: trough → peak : INH
                          peak → trough : EXH
        """
        times = np.asarray(rsp.times, dtype=float)
        values = np.asarray(rsp.values, dtype=float)
        fs = np.nanmean(1.0 / np.diff(times))

        if prefilter_order is None:
            prefilter_order, _ = buttord(
                prefilter_cutoff_hz * 0.9,
                prefilter_cutoff_hz * 1.1,
                1.0,
                7,
                analog=False,
                fs=fs,
            )

        n = times.size
        if n < 5:
            logger.warning("RSP TimeSeries too short for respiration phase extraction.")
            return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))

        dt = np.diff(times)
        dt = dt[(dt > 0) & np.isfinite(dt)]
        if dt.size == 0:
            logger.warning("Invalid timestamps (non-increasing or non-finite).")
            return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))

        fs = 1.0 / float(np.median(dt))
        nyq = 0.5 * fs

        # 0) Prefilter
        y0 = values.astype(float, copy=True)
        fc = min(float(prefilter_cutoff_hz), 0.95 * nyq)
        if fc <= 0:
            raise ValueError("prefilter_cutoff_hz must be > 0.")
        sos = butter(int(prefilter_order), fc / nyq, btype="low", output="sos")
        y_lp = (
            sosfiltfilt(sos, y0)
            if y0.size >= max(3 * (2 * sos.shape[0] + 1), 15)
            else y0
        )

        # 1) Smoothing
        if smooth:
            w = int(smoothing_window)
            if w < 5:
                w = 5
            if w % 2 == 0:
                w += 1
            if w >= y_lp.size:
                w = y_lp.size - 1 if (y_lp.size - 1) % 2 == 1 else y_lp.size - 2
            w = max(w, 5)
            p = max(2, min(int(polyorder), w - 2))
            y = savgol_filter(y_lp, window_length=w, polyorder=p, mode="interp")
        else:
            y = y_lp

        # 2) Peak/trough detection
        min_dist = int(max(1, round(min_phase_duration * fs)))
        if prominence is None:
            med = np.median(y)
            mad = np.median(np.abs(y - med))
            sigma = 1.4826 * mad if mad > 0 else float(np.std(y))
            if sigma <= 0:
                logger.warning("RSP signal is near-constant; cannot extract phases.")
                return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))
            prominence = float(prominence_rel * sigma)

        peaks, _ = find_peaks(y, distance=min_dist, prominence=prominence)
        troughs, _ = find_peaks(-y, distance=min_dist, prominence=prominence)

        if peaks.size == 0 or troughs.size == 0:
            logger.warning(
                "No reliable peaks/troughs detected for respiration segmentation."
            )
            return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))

        # 3) Merge and enforce alternation
        extrema_idx = np.concatenate([peaks, troughs])
        extrema_typ = np.concatenate(
            [
                np.ones(peaks.size, dtype=int),
                -np.ones(troughs.size, dtype=int),
            ]
        )
        order = np.argsort(extrema_idx)
        extrema_idx = extrema_idx[order]
        extrema_typ = extrema_typ[order]

        keep = [0]
        for k in range(1, extrema_idx.size):
            prev = keep[-1]
            if extrema_typ[k] != extrema_typ[prev]:
                keep.append(k)
            else:
                i_prev, i_cur = int(extrema_idx[prev]), int(extrema_idx[k])
                better = (
                    (y[i_cur] > y[i_prev])
                    if extrema_typ[k] == 1
                    else (y[i_cur] < y[i_prev])
                )
                if better:
                    keep[-1] = k
        extrema_idx = extrema_idx[keep]
        extrema_typ = extrema_typ[keep]

        if extrema_idx.size < 2:
            return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))

        # 4) Build phases
        starts_list: list[float] = []
        ends_list: list[float] = []
        labels_list: list[str] = []

        for i in range(extrema_idx.size - 1):
            i0, i1 = int(extrema_idx[i]), int(extrema_idx[i + 1])
            t0, t1 = float(times[i0]), float(times[i1])
            if t1 - t0 < min_phase_duration:
                continue
            if min_amplitude is not None and abs(y[i1] - y[i0]) < float(min_amplitude):
                continue
            if extrema_typ[i] == -1 and extrema_typ[i + 1] == 1:
                lab = "INH"
            elif extrema_typ[i] == 1 and extrema_typ[i + 1] == -1:
                lab = "EXH"
            else:
                continue
            starts_list.append(t0)
            ends_list.append(t1)
            labels_list.append(lab)

        if not starts_list:
            logger.warning(
                "All detected respiration phases rejected (duration/amplitude thresholds)."
            )
            return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))

        return cls(
            np.asarray(starts_list, dtype=float),
            np.asarray(ends_list, dtype=float),
            np.asarray(labels_list, dtype=object),
        )

    # ------------------------------------------------------------------
    # Convenience / inspection
    # ------------------------------------------------------------------

    def as_dict(self) -> Dict[str, np.ndarray]:
        """
        Return phases grouped by label.

        Returns
        -------
        dict  with keys "INH" and "EXH", values Nx2 (start, end) arrays.
        """
        grouped: Dict[str, list] = {"INH": [], "EXH": []}
        for s, e, lab in zip(self.starts, self.ends, self.labels):
            grouped[lab].append((s, e))
        return {k: np.asarray(v, dtype=float) for k, v in grouped.items()}

    def __len__(self) -> int:
        return int(self.starts.size)

    def __repr__(self) -> str:
        return f"RespirationSeries(n={len(self)})"

    def view(self, starttime: float, endtime: float) -> "RespirationSeriesView":
        """Return a zero-copy view restricted to phases within [starttime, endtime]."""
        idx = np.where((self.starts >= starttime) & (self.ends <= endtime))[0]
        v = RespirationSeriesView(self, idx)
        v._pd = self._pd
        v._stream = self._stream
        v._epoch = None
        return v


# ======================================================================
# RespirationSeriesView — zero-copy view, composition not inheritance
# ======================================================================


class RespirationSeriesView:
    """
    Zero-copy view into a parent RespirationSeries.

    Uses composition: holds a reference to the parent and an index array.
    Does NOT inherit from RespirationSeries — it cannot own data or call
    from_timeseries. Methods that only make sense on the full series are
    deliberately absent.

    Mutations to the parent RespirationSeries are reflected in the view.
    View methods never modify the parent.

    Identity metadata
    -----------------
    _pd     : PhysioData linkage (propagated from parent)
    _stream : band / stream identifier
    _epoch  : epoch label (set when produced by epoch slicing)
    """

    def __init__(self, parent: RespirationSeries, indices: np.ndarray) -> None:
        self._parent = parent
        self._idx = np.asarray(indices, dtype=int)
        self._pd = getattr(parent, "_pd", None)
        self._stream = getattr(parent, "_stream", None)
        self._epoch: Optional[str] = None

    # ------------------------------------------------------------------
    # Data interface (composition, not ownership)
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
