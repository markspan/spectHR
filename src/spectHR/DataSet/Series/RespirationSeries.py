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
        # 0) mandatory prefilter on raw signal
        prefilter_cutoff_hz: float = 2,
        prefilter_order: int | None = None,
        # 1) segmentation constraints
        min_phase_duration: float = 2,
        # 2) smoothing/derivative support (post-prefilter)
        smooth: bool = True,
        smoothing_window: int = 31,
        polyorder: int = 3,
        # 3) peak detection robustness
        prominence: float | None = None,
        prominence_rel: float = 0.55,
        min_amplitude: float | None = None,
    ) -> "RespirationSeries":
        """
        Robust inhale/exhale segmentation using extrema (troughs/peaks).

        Pipeline
        --------
        0) Low-pass filter RAW signal at `prefilter_cutoff_hz` (default 2 Hz)
        1) Optional Savitzky–Golay smoothing (preserves extrema well)
        2) Detect peaks and troughs using prominence + minimum distance
        3) Enforce alternation of extrema
        4) Build phases:
            trough -> peak : INH
            peak  -> trough: EXH

        Assumptions
        -----------
        - `rsp.times` are monotonic increasing (implied by your TimeSeries contract).
        - `rsp.values` are finite (NaNs will reduce robustness; pre-clean upstream if needed).
        """
        times = np.asarray(rsp.times, dtype=float)
        values = np.asarray(rsp.values, dtype=float)
        fs = np.nanmean(1.0 / np.diff(times))

        if prefilter_order is None:
            prefilter_order, wn = buttord(
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

        # Robust fs estimate
        dt = np.diff(times)
        dt = dt[(dt > 0) & np.isfinite(dt)]
        if dt.size == 0:
            logger.warning("Invalid timestamps (non-increasing or non-finite).")
            return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))
        fs = 1.0 / float(np.median(dt))
        nyq = 0.5 * fs

        # ------------------------------------------------------------
        # 0) Prefilter raw signal (low-pass at 2 Hz by default)
        # ------------------------------------------------------------
        y0 = values.astype(float, copy=True)

        # Guard cutoff against Nyquist
        fc = float(prefilter_cutoff_hz)
        fc = min(fc, 0.95 * nyq)
        if fc <= 0:
            raise ValueError("prefilter_cutoff_hz must be > 0.")
        logger.debug(f"RSP prefilter: low-pass {fc:.2f} Hz, order {prefilter_order}")
        sos = butter(int(prefilter_order), fc / nyq, btype="low", output="sos")
        # sosfiltfilt needs some length; if too short, fall back gracefully
        if y0.size >= max(3 * (2 * sos.shape[0] + 1), 15):
            y_lp = sosfiltfilt(sos, y0)
        else:
            y_lp = y0

        # ------------------------------------------------------------
        # 1) Optional Savitzky–Golay smoothing (post-prefilter)
        # ------------------------------------------------------------
        if smooth:
            w = int(smoothing_window)
            if w < 5:
                w = 5
            if w % 2 == 0:
                w += 1
            if w >= y_lp.size:
                w = y_lp.size - 1 if (y_lp.size - 1) % 2 == 1 else y_lp.size - 2
                w = max(w, 5)

            p = int(polyorder)
            p = min(p, w - 2)
            p = max(p, 2)

            y = savgol_filter(y_lp, window_length=w, polyorder=p, mode="interp")
        else:
            y = y_lp

        # ------------------------------------------------------------
        # 2) Peak/trough detection parameters
        # ------------------------------------------------------------
        min_dist_samples = int(max(1, round(min_phase_duration * fs)))

        if prominence is None:
            # Robust scale via MAD
            med = np.median(y)
            mad = np.median(np.abs(y - med))
            sigma = 1.4826 * mad if mad > 0 else float(np.std(y))
            if sigma <= 0:
                logger.warning("RSP signal is near-constant; cannot extract phases.")
                return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))
            prominence = float(prominence_rel * sigma)

        peaks, _ = find_peaks(y, distance=min_dist_samples, prominence=prominence)
        troughs, _ = find_peaks(-y, distance=min_dist_samples, prominence=prominence)

        if peaks.size == 0 or troughs.size == 0:
            logger.warning(
                "No reliable peaks/troughs detected for respiration segmentation."
            )
            return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))

        # ------------------------------------------------------------
        # 3) Merge extrema and enforce alternation
        # ------------------------------------------------------------
        extrema_idx = np.concatenate([peaks, troughs])
        extrema_typ = np.concatenate(
            [np.ones(peaks.size, dtype=int), -np.ones(troughs.size, dtype=int)]
        )

        order = np.argsort(extrema_idx)
        extrema_idx = extrema_idx[order]
        extrema_typ = extrema_typ[order]

        keep_pos = [0]
        for k in range(1, extrema_idx.size):
            prev = keep_pos[-1]
            if extrema_typ[k] != extrema_typ[prev]:
                keep_pos.append(k)
                continue

            i_prev = int(extrema_idx[prev])
            i_cur = int(extrema_idx[k])

            # For peaks keep higher; for troughs keep lower
            if extrema_typ[k] == 1:
                better = y[i_cur] > y[i_prev]
            else:
                better = y[i_cur] < y[i_prev]

            if better:
                keep_pos[-1] = k

        extrema_idx = extrema_idx[keep_pos]
        extrema_typ = extrema_typ[keep_pos]

        if extrema_idx.size < 2:
            return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))

        # ------------------------------------------------------------
        # 4) Build phases between consecutive extrema
        # ------------------------------------------------------------
        starts: list[float] = []
        ends: list[float] = []
        labels: list[str] = []

        for i in range(extrema_idx.size - 1):
            i0 = int(extrema_idx[i])
            i1 = int(extrema_idx[i + 1])

            t0 = float(times[i0])
            t1 = float(times[i1])

            dur = t1 - t0
            if dur < min_phase_duration:
                continue

            amp = float(abs(y[i1] - y[i0]))
            if (min_amplitude is not None) and (amp < float(min_amplitude)):
                continue

            if extrema_typ[i] == -1 and extrema_typ[i + 1] == 1:
                lab = "INH"  # trough -> peak
            elif extrema_typ[i] == 1 and extrema_typ[i + 1] == -1:
                lab = "EXH"  # peak -> trough
            else:
                continue

            starts.append(t0)
            ends.append(t1)
            labels.append(lab)

        if not starts:
            logger.warning(
                "All detected respiration phases rejected (duration/amplitude thresholds)."
            )
            return cls(np.asarray([]), np.asarray([]), np.asarray([], dtype=object))

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
        idx = np.where((self.starts >= starttime) & (self.ends <= endtime))[0]
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
            raise RuntimeError("RespirationSeriesView is not connected to PhysioData.")
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
