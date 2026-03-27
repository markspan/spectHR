# CardioSeries.py
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, runtime_checkable
from typing import Protocol

import numpy as np
import scipy.signal as signal
from scipy.interpolate import interp1d
from scipy.stats import chi2

from spectHR.DataSet.HRVMetrics import HRVMetric, hrv_metric
from spectHR.Tools.Logger import logger

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData


# ======================================================================
# Protocol — for type annotations where either owner or view is accepted
# ======================================================================


@runtime_checkable
class CardioSeriesLike(Protocol):
    """
    Structural protocol satisfied by both CardioSeries and CardioSeriesView.

    Use this as a type annotation wherever a function accepts either a full
    CardioSeries or an epoch/time-range view of one.

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


# ======================================================================
# Shared mixin — metric computation shared by owner and view
# ======================================================================


class CardioMetricsMixin(HRVMetric):
    """
    Mixin providing HRV metric computation for any object that exposes:
    - times  : np.ndarray (property or attribute)
    - labels : np.ndarray (property or attribute)
    - ibi    : np.ndarray (property)

    Both CardioSeries (data owner) and CardioSeriesView (zero-copy view)
    inherit from this mixin so they share an identical metric implementation
    without either class depending on the other.

    Methods here never mutate labels or times.
    """

    METRIC_ORDER = [
        "count",
        "mean",
        "median",
        "min",
        "max",
        "std",
        "rmssd",
        "sdnn",
        "sdsd",
        "sd1",
        "sd2",
        "sd_ratio",
        "ellipse_area",
        "vlf_power",
        "lf_power",
        "hf_power",
        "lf_hf_ratio",
    ]

    # ------------------------------------------------------------------
    # Core helper — shared by all metric methods
    # ------------------------------------------------------------------

    def _ibi_clean_ms(self) -> np.ndarray:
        """
        Return valid IBI values in milliseconds for HRV metric calculations.

        Excludes:
        - NaN values (trailing alignment NaN, missing data)
        - Intervals labeled "TL" (too long; likely artifacts)
        - Intervals labeled "T"  (degenerate; zero or negative)

        Returns
        -------
        np.ndarray
            1D float array of IBIs in milliseconds.
        """
        ibi_sec = self.ibi
        if ibi_sec.size == 0:
            return np.array([], dtype=float)
        valid = ~np.isnan(ibi_sec) & (self.labels != "TL") & (self.labels != "T")
        return 1000.0 * ibi_sec[valid]

    # ------------------------------------------------------------------
    # Frequency domain
    # ------------------------------------------------------------------

    def welch_psd(
        self,
        *,
        fs: float = 4.0,
        nperseg: int = 256,
        noverlap: int = 128,
        window: str = "hamming",
        interpolate: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute Welch PSD on the IBI series (ms), optionally interpolated to
        uniform sampling.

        Parameters
        ----------
        fs:
            Target resampling frequency (Hz) for interpolation of unevenly
            spaced IBIs.
        nperseg:
            Segment length for Welch.
        noverlap:
            Segment overlap.
        window:
            Window function name (passed to SciPy's Welch).
        interpolate:
            If True, interpolate the IBI series (ms) to a uniform time grid
            at `fs`.

        Returns
        -------
        freqs, power:
            Arrays of frequencies and power spectral density values.
            Empty arrays are returned if there are no usable IBI samples or
            if interpolation fails.
        """
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size == 0:
            return np.ndarray(0), np.ndarray(0)

        if ibi_ms.size < nperseg:
            nperseg = ibi_ms.size
            noverlap = int(ibi_ms.size / 2) if ibi_ms.size >= 2 else 0

        ibi_times = self.times[: ibi_ms.size]

        if interpolate:
            try:
                if ibi_times.size >= 2:
                    t_uniform = np.arange(ibi_times[0], ibi_times[-1], 1.0 / fs)
                    ibi_ms = interp1d(
                        ibi_times,
                        ibi_ms,
                        kind="linear",
                        fill_value="extrapolate",
                    )(t_uniform)
            except Exception:
                return np.ndarray(0), np.ndarray(0)

        freqs, power = signal.welch(
            ibi_ms,
            fs=fs,
            scaling="density",
            nfft=1024,
            nperseg=nperseg,
            noverlap=noverlap,
            window=window,
        )
        return freqs, power

    def welch_psd_with_ci(
        self,
        *,
        fs: float = 4.0,
        nperseg: int = 256,
        noverlap: int = 128,
        window: str = "hamming",
        interpolate: bool = True,
        alpha: float = 0.05,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Compute Welch PSD with chi-square confidence intervals.

        Returns
        -------
        freqs, psd, ci_lower, ci_upper
        """
        freqs, psd = self.welch_psd(
            fs=fs,
            nperseg=nperseg,
            noverlap=noverlap,
            window=window,
            interpolate=interpolate,
        )
        if freqs.size == 0:
            return freqs, psd, psd, psd

        step = nperseg - noverlap
        n_segments = max(1, int(np.floor((psd.size * step) / nperseg)))
        nu = 2 * n_segments
        ci_lower = (nu * psd) / chi2.ppf(1 - alpha / 2, nu)
        ci_upper = (nu * psd) / chi2.ppf(alpha / 2, nu)
        return freqs, psd, ci_lower, ci_upper

    def _band_power_exact(
        self,
        freqs: np.ndarray,
        power: np.ndarray,
        f0: float,
        f1: float,
    ) -> float:
        """
        Band power by trapezoidal integration with endpoint interpolation.
        Returns NaN if inputs are empty or the band contains no frequencies.
        Output is scaled by 1000.0.
        """
        if freqs.size == 0:
            return np.nan
        mask = (freqs > f0) & (freqs < f1)
        if not np.any(mask):
            return np.nan
        p0 = np.interp(f0, freqs, power)
        p1 = np.interp(f1, freqs, power)
        f_band = np.concatenate(([f0], freqs[mask], [f1]))
        p_band = np.concatenate(([p0], power[mask], [p1]))
        return float(1000.0 * np.trapezoid(p_band, f_band))

    # ------------------------------------------------------------------
    # HRV metrics — discovered automatically via @hrv_metric
    # ------------------------------------------------------------------

    @hrv_metric
    def count(self) -> int:
        """Number of valid IBIs after NaN and artifact removal."""
        return int(self._ibi_clean_ms().size)

    @hrv_metric
    def mean(self) -> float:
        """Mean IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.mean(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def std(self) -> float:
        """Standard deviation of IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def min(self) -> float:
        """Minimum IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.min(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def max(self) -> float:
        """Maximum IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.max(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def median(self) -> float:
        """Median IBI (ms)."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.median(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def rmssd(self) -> float:
        """Root mean square of successive differences (ms)."""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        d = np.diff(ibi_ms)
        return float(np.sqrt(np.mean(d * d)))

    @hrv_metric
    def sdnn(self) -> float:
        """SDNN (ms): standard deviation of IBI."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def sdsd(self) -> float:
        """SDSD (ms): standard deviation of successive differences."""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        return float(np.std(np.diff(ibi_ms)))

    @hrv_metric
    def sd1(self) -> float:
        """SD1 (ms) — short-term Poincaré variability."""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        return float(np.std((ibi_ms[:-1] - ibi_ms[1:]) / np.sqrt(2.0)))

    @hrv_metric
    def sd2(self) -> float:
        """SD2 (ms) — long-term Poincaré variability."""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        return float(np.std((ibi_ms[:-1] + ibi_ms[1:]) / np.sqrt(2.0)))

    @hrv_metric
    def sd_ratio(self) -> float:
        """SD1/SD2 ratio (dimensionless)."""
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2) or s2 == 0:
            return np.nan
        return float(s1 / s2)

    @hrv_metric
    def ellipse_area(self) -> float:
        """Area of the Poincaré ellipse (π · SD1 · SD2) in ms²."""
        s1, s2 = self.sd1(), self.sd2()
        if np.isnan(s1) or np.isnan(s2):
            return np.nan
        return float(np.pi * s1 * s2)

    @hrv_metric
    def vlf_power(self) -> float:
        """VLF band power (0.003–0.04 Hz) from Welch PSD."""
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, 0.003, 0.04)

    @hrv_metric
    def lf_power(self) -> float:
        """LF band power (0.04–0.15 Hz) from Welch PSD."""
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, 0.04, 0.15)

    @hrv_metric
    def hf_power(self) -> float:
        """HF band power (0.15–0.40 Hz) from Welch PSD."""
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, 0.15, 0.4)

    @hrv_metric
    def lf_hf_ratio(self) -> float:
        """LF/HF ratio (dimensionless)."""
        lf, hf = self.lf_power(), self.hf_power()
        return float(lf / hf) if hf > 0 else np.nan


# ======================================================================
# CardioSeries — data owner
# ======================================================================


class CardioSeries(CardioMetricsMixin):
    """
    Container for R-peak times and per-interval labels, with HRV metric methods.

    Conceptual model
    ----------------
    A CardioSeries owns a sequence of R-peak timestamps (seconds, dataset time
    base). Inter-beat intervals (IBIs) are derived on demand from those times.

    Data arrays
    -----------
    times:  1D float array of R-peak times in seconds.
    labels: 1D object array of per-interval labels (same length as times).
            Alignment: labels[i] describes the interval between times[i] and
            times[i+1]. The final element is present for alignment but unused.

    Label lifecycle
    ---------------
    All label assignment is the sole responsibility of classify_ibi().
    The ibi property is a pure computation and never mutates labels.
    Call classify_ibi() after any mutation to times.

    Relationship to views
    ---------------------
    CardioSeries.view() and CardioSeries.__getitem__() return CardioSeriesView
    objects. Views do NOT inherit from CardioSeries — they use composition and
    share metric methods via CardioMetricsMixin. Use CardioSeriesLike for type
    annotations where either is acceptable.
    """

    def __init__(self, times: np.ndarray) -> None:
        self.times = np.asarray(times, dtype=float)
        self.labels = np.full(self.times.shape, "N", dtype=object)
        self._pd: Optional["PhysioData"] = None
        self._stream: Optional[str] = None

    # ------------------------------------------------------------------
    # Construction / detection
    # ------------------------------------------------------------------

    @classmethod
    def from_timeseries(
        cls,
        ts,
        *,
        min_peak_distance_ms: float = 300.0,
        classify: bool = True,
    ) -> "CardioSeries":
        """
        Detect R-peaks from an ECG TimeSeries and construct a CardioSeries.

        Steps
        -----
        1. Estimate sampling rate from ts.times
        2. Detect candidate peaks with scipy.signal.find_peaks
        3. Apply a lightweight sub-sample timing correction
        4. Initialise labels to "N"
        5. Optionally classify IBIs via classify_ibi()

        Parameters
        ----------
        ts:
            ECG time series with .times and .values attributes.
        min_peak_distance_ms:
            Minimum expected R-R distance in milliseconds.
        classify:
            If True, run classify_ibi() after peak detection.
        """
        times = np.asarray(ts.times, dtype=float)
        values = np.asarray(ts.values, dtype=float)

        if times.size < 2 or values.size < 2:
            logger.warning("ECG TimeSeries too short for peak detection.")
            return cls(np.array([], dtype=float))

        time_deltas = np.diff(times)
        time_deltas = time_deltas[time_deltas > 0]
        if time_deltas.size == 0:
            raise ValueError(
                "Cannot estimate sampling rate from ECG times (no positive deltas)."
            )
        sampling_rate_hz = 1.0 / float(np.mean(time_deltas))

        min_distance_samples = max(
            1, int((min_peak_distance_ms / 1000.0) * sampling_rate_hz)
        )
        peak_height_threshold = float(np.median(values) + 1.5 * np.std(values))

        peak_indices, _ = signal.find_peaks(
            values,
            height=peak_height_threshold,
            distance=min_distance_samples,
        )

        if peak_indices.size == 0:
            logger.warning("No R-peaks detected.")
            return cls(np.array([], dtype=float))

        pre_values = values[np.clip(peak_indices - 1, 0, values.size - 1)]
        post_values = values[np.clip(peak_indices + 1, 0, values.size - 1)]
        peak_values = values[peak_indices]
        local_contrast = np.maximum(
            np.abs(peak_values - pre_values),
            np.abs(post_values - peak_values),
        )
        local_contrast[local_contrast == 0] = 1e-12
        correction_sec = (
            (post_values - pre_values) / sampling_rate_hz / (2.0 * local_contrast)
        )
        peak_times = times[peak_indices] + correction_sec

        series = cls(np.asarray(peak_times, dtype=float))
        series.labels[:] = "N"
        if classify:
            series.classify_ibi()
        return series

    # ------------------------------------------------------------------
    # IBI — pure computation, no side effects
    # ------------------------------------------------------------------

    @property
    def ibi(self) -> np.ndarray:
        """
        Inter-beat intervals in seconds, with a trailing NaN for alignment.

        len(ibi) == len(times). ibi[i] is the interval between times[i] and
        times[i+1]. The final element is always NaN.

        This property is a pure computation — it never mutates self.labels.
        Call classify_ibi() after any mutation to times.
        """
        if self.times.size < 2:
            return np.asarray([], dtype=float)
        return np.concatenate([np.diff(self.times), np.array([np.nan], dtype=float)])

    # ------------------------------------------------------------------
    # Classification — sole owner of label state
    # ------------------------------------------------------------------

    def classify_ibi(
        self,
        *,
        window_length: int = 51,
        n_std: float = 4.0,
        max_ibi_sec: float = 2.0,
    ) -> None:
        """
        Classify IBIs and assign labels. This is the sole method that mutates
        self.labels. Call it after any change to self.times.

        Labels produced
        ---------------
        "N"   — normal
        "L"   — long (above rolling upper threshold)
        "S"   — short (below rolling lower threshold)
        "TL"  — too long (> max_ibi_sec); excluded from statistics
        "SL"  — short-then-long pattern
        "SNS" — short-normal-short pattern
        "T"   — degenerate (NaN or <= 0)

        Parameters
        ----------
        window_length:
            Size of the centered rolling window (beats) for local mean/std.
        n_std:
            Threshold multiplier: mean ± n_std × std defines S/L boundaries.
        max_ibi_sec:
            Absolute ceiling; any IBI above this is labeled TL before rolling
            statistics are computed, so artifacts do not distort thresholds.
        """
        ibi_sec = self.ibi  # pure, no side effects
        labels = self.labels
        n = ibi_sec.size

        if n == 0:
            return

        # Step 1: degenerate and too-long
        degenerate = np.isnan(ibi_sec) | (ibi_sec <= 0)
        labels[degenerate] = "T"
        too_long = ibi_sec > max_ibi_sec
        labels[too_long] = "TL"

        # Step 2: IBI array for statistics (exclude T and TL)
        ibi_stats = ibi_sec.astype(float, copy=True)
        ibi_stats[degenerate | too_long] = np.nan
        if ibi_stats.size >= 2 and np.isnan(ibi_stats[-1]):
            last_valid = ibi_stats[~np.isnan(ibi_stats)]
            if last_valid.size > 0:
                ibi_stats[-1] = last_valid[-1]

        if not np.any(~np.isnan(ibi_stats)):
            return

        # Step 3: short-series fallback
        if n < window_length:
            mean = np.nanmean(ibi_stats)
            std = np.nanstd(ibi_stats)
            lo, hi = mean - n_std * std, mean + n_std * std
            for i in range(n):
                if labels[i] in ("T", "TL"):
                    continue
                labels[i] = "L" if ibi_sec[i] > hi else "S" if ibi_sec[i] < lo else "N"
            return

        # Step 4: rolling statistics
        half = window_length // 2
        padded = np.pad(ibi_stats, (half, half), mode="edge")
        windows = np.lib.stride_tricks.sliding_window_view(padded, window_length)
        local_mean = np.nanmean(windows, axis=1)[:n]
        local_std = np.nanstd(windows, axis=1)[:n]
        lo = local_mean - n_std * local_std
        hi = local_mean + n_std * local_std

        # Step 5: pointwise classification
        for i in range(n):
            if labels[i] in ("T", "TL"):
                continue
            labels[i] = (
                "L" if ibi_sec[i] > hi[i] else "S" if ibi_sec[i] < lo[i] else "N"
            )

        # Step 6: sequence heuristics
        for i in range(n - 1):
            if labels[i] == "S" and labels[i + 1] == "L":
                labels[i] = "SL"
        for i in range(n - 2):
            if labels[i] == "S" and labels[i + 1] == "N" and labels[i + 2] == "S":
                labels[i] = "SNS"

        # Step 7: summary
        unique, counts = np.unique(labels, return_counts=True)
        logger.info(f"IBI classification summary (n_IBI={n}):")
        for lab, cnt in zip(unique, counts):
            logger.info(f"  {lab}: {cnt}")

    # ------------------------------------------------------------------
    # Editing / replacement
    # ------------------------------------------------------------------

    def replace_from_timeseries(
        self,
        ts,
        *,
        start: float,
        end: float,
        min_peak_distance_ms: float = 300.0,
        classify: bool = True,
    ) -> None:
        """
        Re-detect R-peaks inside [start, end] and merge with peaks outside.

        Designed for interactive editing: keeps R-peaks outside the window,
        replaces those inside with freshly detected ones, then optionally
        re-runs global classification.
        """
        if start >= end:
            raise ValueError("replace_from_timeseries: start must be < end")

        if self.times.size == 0:
            new = CardioSeries.from_timeseries(
                ts, min_peak_distance_ms=min_peak_distance_ms, classify=classify
            )
            self.times = new.times
            self.labels = new.labels
            return

        new = CardioSeries.from_timeseries(
            ts, min_peak_distance_ms=min_peak_distance_ms, classify=False
        )
        new_labels = np.full(new.times.shape, "N", dtype=object)

        keep = (self.times < start) | (self.times > end)
        merged_times = np.concatenate([self.times[keep], new.times])
        merged_labels = np.concatenate([self.labels[keep], new_labels])

        if merged_times.size == 0:
            self.times = merged_times
            self.labels = merged_labels
            return

        order = np.argsort(merged_times)
        self.times = merged_times[order]
        self.labels = merged_labels[order]

        if classify:
            self.classify_ibi()

    # ------------------------------------------------------------------
    # Views / slicing
    # ------------------------------------------------------------------

    def __getitem__(self, epoch_label: str) -> "CardioSeriesView":
        """
        Return an epoch-restricted view using PhysioData.epochs.

        Raises
        ------
        RuntimeError
            If this CardioSeries is not linked to a PhysioData instance.
        KeyError
            If the requested epoch does not exist.
        """
        if self._pd is None:
            raise RuntimeError(
                "CardioSeries is not connected to a PhysioData instance. "
                "Assign CardioSeries._pd = physiodata."
            )
        if epoch_label not in self._pd.epochs:
            raise KeyError(f"No epoch '{epoch_label}' in PhysioData.")
        ep = self._pd.epochs[epoch_label]
        idx = np.where((self.times >= ep.start) & (self.times <= ep.end))[0]
        view = CardioSeriesView(self, idx)
        view._pd = self._pd
        view._stream = self._stream
        view._epoch = epoch_label
        return view

    def view(self, starttime: float, endtime: float) -> "CardioSeriesView":
        """Return a zero-copy view restricted to [starttime, endtime]."""
        idx = np.where((self.times >= starttime) & (self.times <= endtime))[0]
        v = CardioSeriesView(self, idx)
        v._pd = self._pd
        v._stream = self._stream
        v._epoch = None
        return v

    # ------------------------------------------------------------------
    # Epoch aggregation
    # ------------------------------------------------------------------

    def hrv_epoch_table(
        self,
        physiodata: "PhysioData",
    ) -> Tuple[np.ndarray, List[str], np.ndarray]:
        """
        Compute all HRV metrics for every active epoch in physiodata.

        Returns
        -------
        labels : np.ndarray  (n_epochs,)  — epoch names
        cols   : list[str]               — metric names in METRIC_ORDER
        values : np.ndarray  (n_epochs, n_metrics)  — float64, NaN for missing
        """
        labels_list: List[Any] = []
        rows: List[Dict[str, float]] = []

        for label, ep in physiodata.epochs.items():
            if getattr(ep, "active", False):
                labels_list.append(label)
                rows.append(self.metric_table_epoch(ep.start, ep.end))

        if not rows:
            return np.array([], dtype=object), [], np.empty((0, 0), dtype=float)

        keys = set().union(*(d.keys() for d in rows))
        cols = [c for c in self.METRIC_ORDER if c in keys]
        cols.extend(sorted(keys - set(cols)))

        col_idx = {c: j for j, c in enumerate(cols)}
        values = np.full((len(rows), len(cols)), np.nan, dtype=float)
        for i, d in enumerate(rows):
            for k, v in d.items():
                j = col_idx.get(k)
                if j is not None:
                    values[i, j] = float(v)

        return np.asarray(labels_list, dtype=object), cols, values

    def __repr__(self) -> str:
        return f"CardioSeries(n={self.times.size}, stream={self._stream!r})"


# ======================================================================
# CardioSeriesView — zero-copy view, composition not inheritance
# ======================================================================


class CardioSeriesView(CardioMetricsMixin):
    """
    Zero-copy view into a parent CardioSeries.

    Uses composition: holds a reference to the parent and an index array.
    Does NOT inherit from CardioSeries — it cannot own data, classify IBIs,
    or replace peaks. Methods that only make sense on the full series
    (classify_ibi, replace_from_timeseries, from_timeseries, hrv_epoch_table)
    are deliberately absent.

    All HRV metric methods are inherited from CardioMetricsMixin and operate
    correctly on the view's times and labels.

    Use CardioSeriesLike for type annotations where either a CardioSeries or a
    CardioSeriesView may be passed.

    Identity metadata
    -----------------
    _pd     : PhysioData linkage (propagated from parent)
    _stream : band / stream identifier
    _epoch  : epoch label (set when produced by CardioSeries.__getitem__)
    """

    def __init__(self, parent: CardioSeries, indices: np.ndarray) -> None:
        self._parent = parent
        self._idx = np.asarray(indices, dtype=int)
        self._pd: Optional["PhysioData"] = parent._pd
        self._stream: Optional[str] = parent._stream
        self._epoch: Optional[str] = None

    # ------------------------------------------------------------------
    # Data interface (composition, not ownership)
    # ------------------------------------------------------------------

    @property
    def times(self) -> np.ndarray:
        """View of parent R-peak times (seconds)."""
        return self._parent.times[self._idx]

    @property
    def labels(self) -> np.ndarray:
        """View of parent labels aligned to this view's IBI indexing."""
        return self._parent.labels[self._idx]

    @property
    def ibi(self) -> np.ndarray:
        """
        IBIs in seconds derived from this view's times, with a trailing NaN.
        Pure computation — never mutates parent labels.
        """
        t = self.times
        if t.size < 2:
            return np.asarray([np.nan], dtype=float)
        return np.concatenate([np.diff(t), np.array([np.nan], dtype=float)])

    # ------------------------------------------------------------------
    # Slicing
    # ------------------------------------------------------------------

    def view(self, starttime: float, endtime: float) -> "CardioSeriesView":
        """Create a sub-view restricted to [starttime, endtime]."""
        mask = (self.times >= starttime) & (self.times <= endtime)
        sub = CardioSeriesView(self._parent, self._idx[mask])
        sub._pd = self._pd
        sub._stream = self._stream
        sub._epoch = None
        return sub

    def __repr__(self) -> str:
        return (
            f"CardioSeriesView(n={self.times.size}, "
            f"stream={self._stream!r}, epoch={self._epoch!r})"
        )
