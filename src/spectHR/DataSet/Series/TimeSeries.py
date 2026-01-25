from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
import numpy as np
import scipy.signal as signal

from spectHR.Tools.Logger import logger

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData


@dataclass
class TimeSeries:
    """
    Simple 1-D time series.

    Design role
    -----------
    - Owns raw arrays: times, values
    - Does NOT know about PhysioData, epochs, or stream names
    - Provides identity-neutral views via .view()
    """

    times: np.ndarray
    values: np.ndarray

    def __post_init__(self) -> None:
        self.times = np.asarray(self.times, dtype=float)
        self.values = np.asarray(self.values, dtype=float)

        if self.times.ndim != 1 or self.values.ndim != 1:
            raise ValueError("TimeSeries.times and TimeSeries.values must be 1-D arrays.")
        if self.times.shape[0] != self.values.shape[0]:
            raise ValueError("TimeSeries times and values must have same length.")

    def detect_ecg_polarity(
        self,
        bandpass: tuple[float, float] = (5.0, 20.0),
        min_peak_distance: float = 0.25,
        return_debug: bool = False,
    ) -> str | tuple[str, dict]:
        """
        Determine whether an ECG signal is correctly oriented or inverted.

        Parameters
        ----------
        
        bandpass : tuple[float, float], optional
            Bandpass filter (Hz) used to emphasize QRS complexes.
        min_peak_distance : float, optional
            Minimum distance between peaks (seconds).
        return_debug : bool, optional
            If True, also return a dictionary with diagnostic metrics.

        Returns
        -------
        polarity : {"normal", "inverted"}
            Estimated ECG polarity.
        debug : dict, optional
            Diagnostic metrics used for the decision.

        Notes
        -----
        This method is intentionally conservative and robust:
        - No single heuristic determines polarity.
        - Designed for experimental ECG data with artifacts.
        """
        fs = self.srate
        ecg = self.values.copy()

        if ecg.ndim != 1:
            raise ValueError("ECG signal must be 1D")

        ecg = np.asarray(ecg, dtype=float)
        ecg = ecg[ecg.size // 4 : -ecg.size // 4] if ecg.size > 100 else ecg
        ecg -= np.nanmedian(ecg)

        # ------------------------------------------------------------------
        # 1. Bandpass filter (QRS emphasis)
        # ------------------------------------------------------------------
        nyq = 0.5 * fs
        b, a = signal.butter(
            3,
            [bandpass[0] / nyq, bandpass[1] / nyq],
            btype="bandpass",
        )
        ecg_f = signal.filtfilt(b, a, ecg)

        # ------------------------------------------------------------------
        # 2. Peak polarity dominance
        # ------------------------------------------------------------------
        distance_samples = int(min_peak_distance * fs)

        pos_peaks, pos_props = signal.find_peaks(
            ecg_f,
            distance=distance_samples,
            prominence=np.std(ecg_f),
        )

        neg_peaks, neg_props = signal.find_peaks(
            -ecg_f,
            distance=distance_samples,
            prominence=np.std(ecg_f),
        )

        pos_prom = np.sum(pos_props["prominences"]) if len(pos_peaks) else 0.0
        neg_prom = np.sum(neg_props["prominences"]) if len(neg_peaks) else 0.0

        peak_score = pos_prom - neg_prom

        # ------------------------------------------------------------------
        # 3. Upper vs lower envelope energy
        # ------------------------------------------------------------------
        analytic = signal.hilbert(ecg_f)
        envelope = np.abs(analytic)

        upper_energy = np.mean(envelope[ecg_f > 0]) if np.any(ecg_f > 0) else 0.0
        lower_energy = np.mean(envelope[ecg_f < 0]) if np.any(ecg_f < 0) else 0.0

        envelope_score = upper_energy - lower_energy

        # ------------------------------------------------------------------
        # 4. Extrema asymmetry
        # ------------------------------------------------------------------
        p95 = np.percentile(ecg_f, 95)
        p05 = np.percentile(ecg_f, 5)

        extrema_score = p95 + p05  # positive if upper tail dominates

        # ------------------------------------------------------------------
        # 5. Aggregate decision
        # ------------------------------------------------------------------
        total_score = (
            1.0 * peak_score +
            0.8 * envelope_score +
            0.5 * extrema_score
        )

        polarity = "normal" if total_score < 0 else "inverted"

        debug = dict(
            peak_score=peak_score,
            envelope_score=envelope_score,
            extrema_score=extrema_score,
            total_score=total_score,
            n_pos_peaks=len(pos_peaks),
            n_neg_peaks=len(neg_peaks),
        )

        return (polarity, debug) if return_debug else polarity

    def flip(self) -> None:
        """Invert the signal values in place."""
        logger.info("Flipping TimeSeries values.")
        self.values = -self.values
    
    def filter(
        self,
        *,
        filter_type: str = "highpass",
        cutoff: float = 0.1,
        order: int | None = None,
        inplace: bool = True,
    ) -> TimeSeries:
        """
        Apply a zero-phase Butterworth filter to the signal.

        Parameters
        ----------
        filter_type : {"lowpass", "highpass"}
            Type of Butterworth filter.
        cutoff : float
            Cutoff frequency in Hz.
        order : int | None
            If None, estimate order using buttord; otherwise use explicitly.
        inplace : bool
            If True, modify this TimeSeries in place.
            If False, return a filtered copy.

        Returns
        -------
        TimeSeries
            Filtered TimeSeries (self or a copy).
        """
        if self.srate is None:
            raise ValueError("Cannot filter TimeSeries with unknown sampling rate.")

        if filter_type not in ("lowpass", "highpass"):
            raise ValueError("filter_type must be 'lowpass' or 'highpass'")

        srate = float(self.srate)
        nyq = 0.5 * srate
        norm_cutoff = cutoff / nyq

        if not 0.0 < norm_cutoff < 1.0:
            raise ValueError("Cutoff frequency must be between 0 and Nyquist.")

        # --------------------------------------------------
        # Filter design
        # --------------------------------------------------
        if order is None:
            passband = norm_cutoff * 1.1
            stopband = norm_cutoff / 1.5
            N, wn = signal.buttord(passband, stopband, gpass=1, gstop=5)
        else:
            N = int(order)
            wn = norm_cutoff

        btype = "low" if filter_type == "lowpass" else "high"
        b, a = signal.butter(N, wn, btype=btype, analog=False)

        logger.info(
            f"Filtering TimeSeries ({btype} Butterworth): "
            f"N={N}, cutoff={cutoff} Hz, srate={srate:.2f} Hz"
        )

        # --------------------------------------------------
        # Apply filter
        # --------------------------------------------------
        values = self.values.astype(float)
        filtered = signal.filtfilt(b, a, values)

        if inplace:
            self.values[:] = filtered
            return self

        # Copy semantics
        return TimeSeries(self.times.copy(), filtered)
    
    def __getitem__(self, idx):
        """
        Non-epoch slicing. Returns raw value(s) only.

        Important:
        - We intentionally DO NOT return a TimeSeriesView here, because that would
          enable mutation without identity assignment (pd/stream/epoch).
        """
        return self.values[idx]

    @property
    def srate(self) -> Optional[float]:
        """Approximate sampling rate (Hz), or None if cannot be inferred."""
        if self.times.size < 2:
            return None
        diffs = np.diff(self.times)
        diffs = diffs[diffs > 0]
        if diffs.size == 0:
            return None
        return float(1.0 / np.mean(diffs))

    def view(self, starttime: float | None = None, endtime: float | None = None) -> "TimeSeriesView":
        """
        Return an identity-neutral, zero-copy view on a time interval.

        Identity (pd/stream/epoch) is assigned by StreamAccessor, not here.
        """
        if self.times.size == 0:
            return TimeSeriesView(self, np.empty(0, dtype=int))

        if starttime is None:
            starttime = float(self.times[0])
        if endtime is None:
            endtime = float(self.times[-1])

        mask = (self.times >= starttime) & (self.times <= endtime)
        idx = np.nonzero(mask)[0]
        return TimeSeriesView(self, idx)


class TimeSeriesView:
    """
    Zero-copy dynamic view on a TimeSeries.

    Design role
    -----------
    - Structural slice only; shares storage with the parent series
    - May carry identity metadata (_pd, _stream, _epoch), which is assigned
      by access layers (e.g., StreamAccessor)
    """

    def __init__(self, parent: TimeSeries, indices: np.ndarray) -> None:
        self._parent = parent
        self._indices = np.asarray(indices, dtype=int)

        # Identity metadata (assigned externally by StreamAccessor)
        self._pd: PhysioData | None = None
        self._stream: str | None = None
        self._epoch: str | None = None

    @property
    def physiodata(self) -> "PhysioData | None":
        return self._pd

    @property
    def times(self) -> np.ndarray:
        return self._parent.times[self._indices]

    @property
    def values(self) -> np.ndarray:
        return self._parent.values[self._indices]

    def __getitem__(self, idx: int) -> float:
        parent_idx = int(self._indices[idx])
        return float(self._parent.values[parent_idx])

    def __setitem__(self, idx: int, value: float) -> None:
        """
        Mutate the parent series via the view.

        This is intentionally allowed. Identity metadata enables downstream
        operations (e.g., merging edits back into dataset logic).
        """
        parent_idx = int(self._indices[idx])
        self._parent.values[parent_idx] = float(value)

    def __len__(self) -> int:
        return int(self._indices.size)

    def __repr__(self) -> str:
        return f"TimeSeriesView(n={len(self)}, stream={self._stream!r}, epoch={self._epoch!r})"
