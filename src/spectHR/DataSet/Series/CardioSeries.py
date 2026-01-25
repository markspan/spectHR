# CardioSeries.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

import scipy.signal as signal
from scipy.interpolate import interp1d
from scipy.stats import chi2

from spectHR.DataSet.HRVMetrics import HRVMetric, hrv_metric
from spectHR.Tools.Logger import logger

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData


class CardioSeries(HRVMetric):
    """
    Container for R-peak times and per-interval labels, with HRV metric methods.

    Conceptual model
    ----------------
    A `CardioSeries` represents a sequence of R-peak timestamps (seconds, dataset time base).
    From these timestamps, inter-beat intervals (IBIs; i.e., RR intervals) are derived on demand.

    This class intentionally stores:
    - `times`: R-peak times (float seconds)
    - `labels`: per-interval labels (object array of strings), aligned to `ibi` indexing.

    Important alignment detail
    --------------------------
    `ibi` is derived as `np.diff(times)` plus a trailing NaN so that:
        len(ibi) == len(times)

    This means:
    - `ibi[i]` corresponds to the interval between `times[i]` and `times[i+1]`
    - `labels[i]` labels that interval
    - the final element `ibi[-1]` is `NaN` and `labels[-1]` is present but usually ignored

    Integration with PhysioData and views
    -------------------------------------
    - This class can optionally be linked to a `PhysioData` instance via `_pd`.
    - Epoch slicing is supported via `__getitem__`, returning a zero-copy `CardioSeriesView`
      that carries identity metadata: `_pd`, `_stream`, `_epoch`.

    Notes on mutability
    -------------------
    - `times` and `labels` are mutable arrays.
    - Methods like `replace_from_timeseries` mutate in-place.
    - Views (`CardioSeriesView`) are zero-copy and therefore reflect parent mutations.

    Attributes
    ----------
    times:
        1D array of R-peak times in seconds.
    labels:
        1D array of labels aligned to `ibi` indexing (same length as `times`).
    _pd:
        Optional `PhysioData` linkage used for epoch slicing (`__getitem__`).
    _stream:
        Optional identifier for the originating stream/band.
    """

    METRIC_ORDER = [
        "count", "mean", "median", "min", "max", "std",
        "rmssd", "sdnn", "sdsd",
        "sd1", "sd2", "sd_ratio", "ellipse_area",
        "vlf_power", "lf_power", "hf_power", "lf_hf_ratio",
    ]

    def __init__(self, times: np.ndarray):
        """
        Parameters
        ----------
        times:
            R-peak times in seconds. Will be converted to float numpy array.
        """
        self.times = np.asarray(times, dtype=float)
        self.labels = np.full(self.times.shape, "N", dtype=object)

        # Assigned externally (e.g., by PhysioData integration)
        self._pd: Optional[PhysioData] = None

        # Optional identity for this series (useful if multiple bands)
        self._stream: Optional[str] = None

    # ---------------------------------------------------------------------
    # Construction / detection
    # ---------------------------------------------------------------------

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

        This is a convenience constructor that:
        1) estimates sampling rate from `ts.times`
        2) detects candidate peaks using `scipy.signal.find_peaks`
        3) applies a simple sub-sample timing correction
        4) initializes labels to "N"
        5) optionally classifies IBIs via :meth:`classify_ibi`

        Parameters
        ----------
        ts:
            ECG time series object providing:
            - `ts.times`: 1D array of timestamps in seconds
            - `ts.values`: 1D array of ECG samples (same length as times)
        min_peak_distance_ms:
            Minimum expected R-R distance in milliseconds; converted to a minimum
            number of samples for `find_peaks(distance=...)`.
        classify:
            If True, run :meth:`classify_ibi` after peak detection.

        Returns
        -------
        CardioSeries
            New instance with detected `times` and initialized `labels`.

        Notes
        -----
        - The peak detection threshold used here is a heuristic:
              median(values) + 1.5 * std(values)
          This may not generalize to all ECG preprocessing pipelines.
        - For very short or invalid time bases, peak detection is skipped
          or a ValueError is raised.
        """
        times = np.asarray(ts.times, dtype=float)
        values = np.asarray(ts.values, dtype=float)

        if times.size < 2 or values.size < 2:
            logger.warning("ECG TimeSeries too short for peak detection.")
            return cls(np.array([], dtype=float))

        # --------------------------------------------------
        # Sampling rate estimation (robust to duplicates/non-monotonic samples)
        # --------------------------------------------------
        time_deltas = np.diff(times)
        time_deltas = time_deltas[time_deltas > 0]
        if time_deltas.size == 0:
            raise ValueError("Cannot estimate sampling rate from ECG times (no positive deltas).")

        sampling_rate_hz = 1.0 / float(np.mean(time_deltas))

        # --------------------------------------------------
        # Peak detection
        # --------------------------------------------------
        min_distance_samples = int((min_peak_distance_ms / 1000.0) * sampling_rate_hz)
        min_distance_samples = max(1, min_distance_samples)

        # Heuristic amplitude threshold
        peak_height_threshold = float(np.median(values) + 1.5 * np.std(values))

        peak_indices, _ = signal.find_peaks(
            values,
            height=peak_height_threshold,
            distance=min_distance_samples,
        )

        if peak_indices.size == 0:
            logger.warning("No R-peaks detected.")
            return cls(np.array([], dtype=float))

        # --------------------------------------------------
        # Sub-sample peak timing correction
        # --------------------------------------------------
        # A lightweight correction based on local neighborhood slope/contrast.
        # This is not a full parabolic interpolation; it is a pragmatic adjustment.
        pre_values = values[np.clip(peak_indices - 1, 0, values.size - 1)]
        post_values = values[np.clip(peak_indices + 1, 0, values.size - 1)]
        peak_values = values[peak_indices]

        local_contrast = np.maximum(np.abs(peak_values - pre_values), np.abs(post_values - peak_values))
        local_contrast[local_contrast == 0] = 1e-12

        correction_sec = (post_values - pre_values) / sampling_rate_hz / (2.0 * local_contrast)
        peak_times = times[peak_indices] + correction_sec

        # --------------------------------------------------
        # Build CardioSeries
        # --------------------------------------------------
        series = cls(np.asarray(peak_times, dtype=float))
        series.labels[:] = "N"

        if classify:
            series.classify_ibi()

        return series

    # ---------------------------------------------------------------------
    # Derived signals / helpers
    # ---------------------------------------------------------------------

    @property
    def ibi(self) -> np.ndarray:
        """
        Inter-beat intervals (IBIs) derived from R-peak times in seconds.

        Returns
        -------
        np.ndarray
            1D array of IBIs in seconds, with a trailing NaN to keep alignment:
                len(ibi) == len(times)

        Important
        ---------
        This property does not permanently delete any samples. It *does* apply
        a hard threshold for "too long" intervals (> 2 seconds) by:
        - setting those IBI values to NaN, and
        - setting the corresponding labels to "TL"

        If you need a different policy (e.g., do not mutate labels inside a property),
        consider refactoring this into an explicit cleaning method.
        """
        if self.times.size < 2:
            return np.asarray([], dtype=float)

        ibi_sec = np.concatenate([np.diff(self.times), np.array([np.nan], dtype=float)])

        # Policy: mark too-long intervals as invalid
        too_long_mask = ibi_sec > 2.0
        if np.any(too_long_mask):
            self.labels[too_long_mask] = "TL"
            ibi_sec[too_long_mask] = np.nan

        return ibi_sec

    def _ibi_clean_ms(self) -> np.ndarray:
        """
        Return cleaned IBI values in milliseconds, excluding NaNs.

        Returns
        -------
        np.ndarray
            1D float array of IBIs in milliseconds, with NaNs removed.
        """
        ibi_sec = self.ibi
        return 1000.0 * ibi_sec[~np.isnan(ibi_sec)]

    # ---------------------------------------------------------------------
    # Classification
    # ---------------------------------------------------------------------

    def classify_ibi(
        self,
        *,
        window_length: int = 51,
        n_std: float = 4.0,
        max_ibi_sec: float = 2.0,
    ) -> None:
        """
        Classify inter-beat intervals (IBIs) using local statistics and heuristics.

        This method assigns a label to each IBI (aligned to `self.ibi` indexing)
        based on deviations from local or global statistics.

        Classification strategy
        -----------------------
        1. IBIs are derived from `self.ibi`, which intentionally includes a trailing
        NaN to preserve alignment with R-peak times.
        2. Degenerate IBIs (NaN or <= 0) are immediately labeled "T".
        3. For statistical classification:
        - If the number of intervals is smaller than `window_length`,
            rolling statistics are not meaningful; global mean/std are used.
        - Otherwise, centered rolling mean/std are computed using a sliding window.
        4. IBIs are labeled pointwise using mean ± n_std * std thresholds.
        5. Sequence heuristics are applied afterward to detect specific patterns.

        Labels produced
        ---------------
        - "N"   : normal
        - "L"   : long IBI (above threshold)
        - "S"   : short IBI (below threshold)
        - "TL"  : too long IBI (> max_ibi_sec)
        - "SL"  : short-then-long pattern
        - "SNS" : short-normal-short pattern
        - "T"   : degenerate / invalid interval

        Notes
        -----
        - This method mutates `self.labels` in place.
        - The final (trailing) IBI is never meaningfully classified but is kept
        for alignment consistency.
        - All numerical edge cases are handled explicitly to avoid RuntimeWarnings.
        """
        ibi_sec = self.ibi
        labels = self.labels
        n_intervals = ibi_sec.size

        if n_intervals == 0:
            return

        # --------------------------------------------------
        # Step 1: mark degenerate IBIs
        # --------------------------------------------------
        degenerate_mask = np.isnan(ibi_sec) | (ibi_sec <= 0)
        labels[degenerate_mask] = "T"

        # --------------------------------------------------
        # Step 2: prepare IBI array for statistics
        # --------------------------------------------------
        # NOTE:
        # `ibi` ends with a trailing NaN by design (alignment).
        # For statistical computations only, we replace that NaN
        # with the last valid IBI so that padding does not create
        # all-NaN rolling windows.
        ibi_for_stats = ibi_sec.astype(float, copy=True)
        if ibi_for_stats.size >= 2 and np.isnan(ibi_for_stats[-1]):
            ibi_for_stats[-1] = ibi_for_stats[-2]

        # --------------------------------------------------
        # Step 3: short-series fallback (no rolling window)
        # --------------------------------------------------
        valid_mask = ~np.isnan(ibi_for_stats)

        if not np.any(valid_mask):
            # No valid IBIs to classify; all are degenerate
            # Labels have already been set to "T"
            return

        if n_intervals < window_length:
            mean = np.nanmean(ibi_for_stats)
            std = np.nanstd(ibi_for_stats)

            lower_bound = mean - n_std * std
            upper_bound = mean + n_std * std

            for i in range(n_intervals):
                if labels[i] == "T":
                    continue
                if ibi_sec[i] > max_ibi_sec:
                    labels[i] = "TL"
                elif ibi_sec[i] > upper_bound:
                    labels[i] = "L"
                elif ibi_sec[i] < lower_bound:
                    labels[i] = "S"
                else:
                    labels[i] = "N"

            return

        # --------------------------------------------------
        # Step 4: rolling statistics (centered window)
        # --------------------------------------------------
        half_window = window_length // 2
        ibi_padded = np.pad(ibi_for_stats, (half_window, half_window), mode="edge")

        windows = np.lib.stride_tricks.sliding_window_view(
            ibi_padded, window_length
        )

        local_mean = np.nanmean(windows, axis=1)[:n_intervals]
        local_std = np.nanstd(windows, axis=1)[:n_intervals]

        lower_bound = local_mean - n_std * local_std
        upper_bound = local_mean + n_std * local_std

        # --------------------------------------------------
        # Step 5: pointwise classification
        # --------------------------------------------------
        for i in range(n_intervals):
            if labels[i] == "T":
                continue
            if ibi_sec[i] > max_ibi_sec:
                labels[i] = "TL"
            elif ibi_sec[i] > upper_bound[i]:
                labels[i] = "L"
            elif ibi_sec[i] < lower_bound[i]:
                labels[i] = "S"
            else:
                labels[i] = "N"

        # --------------------------------------------------
        # Step 6: sequence heuristics
        # --------------------------------------------------
        for i in range(n_intervals - 1):
            if labels[i] == "S" and labels[i + 1] == "L":
                labels[i] = "SL"

        for i in range(n_intervals - 2):
            if labels[i] == "S" and labels[i + 1] == "N" and labels[i + 2] == "S":
                labels[i] = "SNS"

        # --------------------------------------------------
        # Step 7: logging summary
        # --------------------------------------------------
        unique, counts = np.unique(labels, return_counts=True)
        summary = dict(zip(unique, counts))
        logger.info(f"IBI classification summary (n_IBI={n_intervals}):")
        for label, count in summary.items():
            logger.info(f" {label}: {count}")

    # ---------------------------------------------------------------------
    # Editing / replacement
    # ---------------------------------------------------------------------

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
        Re-detect R-peaks from an ECG TimeSeries (or view) and replace peaks in a window.

        This method is designed for interactive editing workflows:
        - Keep R-peaks outside [start, end]
        - Replace (remove and reinsert) R-peaks inside [start, end] with newly detected peaks
        - Set labels for replaced peaks to "N"
        - Optionally re-run global IBI classification

        Parameters
        ----------
        ts:
            ECG signal, possibly already restricted to an epoch. Must provide `.times` and `.values`.
        start:
            Start time of the replacement window (seconds, dataset time base).
        end:
            End time of the replacement window (seconds, dataset time base).
        min_peak_distance_ms:
            Minimum expected R-R distance used during peak detection.
        classify:
            If True, run :meth:`classify_ibi` once after the merge.

        Raises
        ------
        ValueError
            If start >= end.

        Notes
        -----
        - If there are no existing peaks, this method behaves like replacing everything.
        - If no new peaks are found in the window, the old peaks are still removed.
          This supports "clear this epoch/window" semantics.
        """
        if start >= end:
            raise ValueError("replace_from_timeseries: start must be < end")

        # No existing peaks -> just rebuild
        if self.times.size == 0:
            new_series = CardioSeries.from_timeseries(
                ts,
                min_peak_distance_ms=min_peak_distance_ms,
                classify=classify,
            )
            self.times = new_series.times
            self.labels = new_series.labels
            return

        # Detect new peaks (do not classify yet; do it once after merging)
        new_series = CardioSeries.from_timeseries(
            ts,
            min_peak_distance_ms=min_peak_distance_ms,
            classify=False,
        )
        new_times = new_series.times
        new_labels = np.full(new_times.shape, "N", dtype=object)

        # Keep old peaks outside window
        keep_mask = (self.times < start) | (self.times > end)
        kept_times = self.times[keep_mask]
        kept_labels = self.labels[keep_mask]

        # Merge and sort
        merged_times = np.concatenate([kept_times, new_times])
        merged_labels = np.concatenate([kept_labels, new_labels])

        if merged_times.size == 0:
            self.times = merged_times
            self.labels = merged_labels
            return

        order = np.argsort(merged_times)
        self.times = merged_times[order]
        self.labels = merged_labels[order]

        if classify:
            self.classify_ibi()

    # ---------------------------------------------------------------------
    # Views / slicing
    # ---------------------------------------------------------------------

    def __getitem__(self, epoch_label: str) -> "CardioSeriesView":
        """
        Return an epoch view using PhysioData.epochs.

        Parameters
        ----------
        epoch_label:
            Name/key of the epoch in `self._pd.epochs`.

        Returns
        -------
        CardioSeriesView
            Zero-copy view containing indices within the epoch.

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
        """
        Create an identity-neutral view by time range.

        Parameters
        ----------
        starttime:
            Start time in seconds (inclusive).
        endtime:
            End time in seconds (inclusive).

        Returns
        -------
        CardioSeriesView
            Zero-copy view with propagated `_pd` and `_stream` metadata; `_epoch` is None.
        """
        idx = np.where((self.times >= starttime) & (self.times <= endtime))[0]
        view = CardioSeriesView(self, idx)
        view._pd = self._pd
        view._stream = self._stream
        view._epoch = None
        return view

    # ---------------------------------------------------------------------
    # Frequency domain
    # ---------------------------------------------------------------------

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
        Compute Welch PSD of the IBI series with chi-square confidence intervals.

        Parameters
        ----------
        fs:
            Resampling frequency (Hz) used for interpolating uneven IBIs to a uniform grid.
        nperseg:
            Segment length for Welch.
        noverlap:
            Overlap between segments.
        window:
            Welch window function name (passed to SciPy).
        interpolate:
            If True, interpolate the IBI series onto a uniform time grid at `fs`.
        alpha:
            Significance level for the (1-alpha) confidence interval.

        Returns
        -------
        freqs, psd, ci_lower, ci_upper:
            Arrays of frequencies, PSD estimate, and lower/upper confidence bounds.

        Notes
        -----
        - The degrees-of-freedom estimate used here is a heuristic based on segment count.
          If you require exact CI calibration, compute effective DOF based on window and overlap.
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
        # Heuristic segment count; kept consistent with original code intent.
        n_segments = max(1, int(np.floor((psd.size * step) / nperseg)))
        nu = 2 * n_segments  # DOF approximation

        ci_lower = (nu * psd) / chi2.ppf(1 - alpha / 2, nu)
        ci_upper = (nu * psd) / chi2.ppf(alpha / 2, nu)

        return freqs, psd, ci_lower, ci_upper

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
        Compute Welch PSD on the IBI series (ms), optionally interpolated to uniform sampling.

        Parameters
        ----------
        fs:
            Target resampling frequency (Hz) for interpolation of unevenly spaced IBIs.
        nperseg:
            Segment length for Welch.
        noverlap:
            Segment overlap.
        window:
            Window function name (passed to SciPy's Welch).
        interpolate:
            If True, interpolate the IBI series (ms) to a uniform time grid at `fs`.

        Returns
        -------
        freqs, power:
            Arrays of frequencies and power spectral density values.

        Failure modes
        -------------
        Returns empty arrays if:
        - There are no usable IBI samples
        - Interpolation fails due to insufficient times or numerical issues
        """
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size == 0:
            return np.ndarray(0), np.ndarray(0)

        # Adapt segment sizes to short signals
        if ibi_ms.size < nperseg:
            nperseg = ibi_ms.size
            noverlap = int(ibi_ms.size / 2) if ibi_ms.size >= 2 else 0

        # Align times to IBI samples used (ibi_ms excludes NaNs; we approximate by slicing)
        # This is consistent with the original design but is a simplification:
        # if many NaNs exist, `times[:ibi_ms.size]` may not correspond exactly.
        ibi_times = self.times[:ibi_ms.size]

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

    # ---------------------------------------------------------------------
    # HRV metrics
    # ---------------------------------------------------------------------

    @hrv_metric
    def count(self) -> int:
        """Number of valid IBIs (ms) after NaN removal."""
        ibi_ms = self._ibi_clean_ms()
        return int(ibi_ms.size)

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
        """
        Root mean square of successive differences (RMSSD) in ms.

        Computed as:
            sqrt(mean(diff(IBI_ms)^2))
        """
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        successive_diffs_ms = np.diff(ibi_ms)
        return float(np.sqrt(np.mean(successive_diffs_ms * successive_diffs_ms)))

    @hrv_metric
    def sdnn(self) -> float:
        """SDNN (ms): standard deviation of IBI."""
        ibi_ms = self._ibi_clean_ms()
        return float(np.std(ibi_ms)) if ibi_ms.size else np.nan

    @hrv_metric
    def sdsd(self) -> float:
        """SDSD (ms): standard deviation of successive differences of IBI."""
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        successive_diffs_ms = np.diff(ibi_ms)
        return float(np.std(successive_diffs_ms))

    @hrv_metric
    def sd1(self) -> float:
        """
        SD1 (ms) of the Poincaré plot.

        SD1 reflects short-term variability and is computed from:
            (IBI[i] - IBI[i+1]) / sqrt(2)
        """
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        x1, x2 = ibi_ms[:-1], ibi_ms[1:]
        transverse = (x1 - x2) / np.sqrt(2.0)
        return float(np.std(transverse))

    @hrv_metric
    def sd2(self) -> float:
        """
        SD2 (ms) of the Poincaré plot.

        SD2 reflects longer-term variability and is computed from:
            (IBI[i] + IBI[i+1]) / sqrt(2)
        """
        ibi_ms = self._ibi_clean_ms()
        if ibi_ms.size < 2:
            return np.nan
        x1, x2 = ibi_ms[:-1], ibi_ms[1:]
        longitudinal = (x1 + x2) / np.sqrt(2.0)
        return float(np.std(longitudinal))

    @hrv_metric
    def sd_ratio(self) -> float:
        """SD1/SD2 ratio (dimensionless)."""
        sd1_ms, sd2_ms = self.sd1(), self.sd2()
        if np.isnan(sd1_ms) or np.isnan(sd2_ms) or sd2_ms == 0:
            return np.nan
        return float(sd1_ms / sd2_ms)

    @hrv_metric
    def ellipse_area(self) -> float:
        """Area of the Poincaré ellipse (π * SD1 * SD2) in ms²."""
        sd1_ms, sd2_ms = self.sd1(), self.sd2()
        if np.isnan(sd1_ms) or np.isnan(sd2_ms):
            return np.nan
        return float(np.pi * sd1_ms * sd2_ms)

    @hrv_metric
    def vlf_power(self) -> float:
        """VLF band power from Welch PSD (units scaled by 1000 per original code)."""
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, 0.003, 0.04)

    @hrv_metric
    def lf_power(self) -> float:
        """LF band power from Welch PSD (units scaled by 1000 per original code)."""
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, 0.04, 0.15)

    @hrv_metric
    def hf_power(self) -> float:
        """HF band power from Welch PSD (units scaled by 1000 per original code)."""
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, 0.15, 0.4)

    @hrv_metric
    def lf_hf_ratio(self) -> float:
        """LF/HF ratio (dimensionless)."""
        lf = self.lf_power()
        hf = self.hf_power()
        return float(lf / hf) if hf > 0 else np.nan

    # ---------------------------------------------------------------------
    # Epoch aggregation
    # ---------------------------------------------------------------------

    def hrv_epoch_table(self, physiodata: PhysioData) -> pd.DataFrame:
        """
        Compute an HRV metric table for all active epochs in a PhysioData instance.

        Parameters
        ----------
        physiodata:
            `PhysioData` containing an `.epochs` mapping of epoch objects
            with `.start`, `.end`, and `.active` attributes.

        Returns
        -------
        pandas.DataFrame
            Index: epoch label
            Columns: HRV metrics (ordered by `METRIC_ORDER` if present)
        """
        rows: List[Dict[str, float]] = []
        for label, ep in physiodata.epochs.items():
            if getattr(ep, "active", False):
                rows.append({"epoch": label, **self.metric_table_epoch(ep.start, ep.end)})

        df = pd.DataFrame(rows).set_index("epoch")

        if hasattr(self, "METRIC_ORDER"):
            cols = [c for c in self.METRIC_ORDER if c in df.columns]
            df = df[cols]

        if "count" in df.columns:
            df["count"] = df["count"].astype("Int64")

        return df

    # ---------------------------------------------------------------------
    # Internal utilities
    # ---------------------------------------------------------------------

    def _band_power_exact(
        self,
        freqs: np.ndarray,
        power: np.ndarray,
        f0: float,
        f1: float,
    ) -> float:
        """
        Compute band power by trapezoidal integration with endpoint interpolation.

        Parameters
        ----------
        freqs:
            Frequency axis (Hz), as returned by Welch.
        power:
            PSD values aligned to `freqs`.
        f0, f1:
            Band edges (Hz). Integration is performed over (f0, f1) with endpoints
            included via linear interpolation.

        Returns
        -------
        float
            Band power scaled by 1000.0 to preserve the original code’s output scale.
            Returns NaN if inputs are empty or if the band contains no frequencies.
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


class CardioSeriesView(CardioSeries):
    """
    Zero-copy view into a parent CardioSeries.

    A `CardioSeriesView` does not own data arrays. Instead, it carries:
    - `_parent`: reference to the parent `CardioSeries`
    - `_idx`: integer indices into the parent arrays

    Identity metadata
    -----------------
    Views may carry additional identity metadata for downstream logic/UI:
    - `_pd`: PhysioData linkage (propagated from parent)
    - `_stream`: stream/band identifier
    - `_epoch`: epoch label for views produced by epoch slicing (`__getitem__`)

    Notes on behavior
    -----------------
    - Mutations to the parent’s `times` or `labels` are reflected in the view.
    - View-level methods that require contiguous numeric arrays may create
      a temporary `CardioSeries` copy (e.g., Welch PSD).
    """

    def __init__(self, parent: CardioSeries, indices: np.ndarray):
        """
        Parameters
        ----------
        parent:
            The parent `CardioSeries` instance.
        indices:
            Indices into the parent arrays that define the view.
        """
        self._parent = parent
        self._idx = np.asarray(indices, dtype=int)

        # Identity metadata (assigned by parent/view logic)
        self._pd: Optional[PhysioData] = parent._pd
        self._stream: Optional[str] = parent._stream
        self._epoch: Optional[str] = None

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
        View-local IBIs (seconds), aligned to view `times`.

        Returns
        -------
        np.ndarray
            IBIs derived from the view's `times`, with a trailing NaN to keep
            alignment (len == len(times)).

        Policy
        ------
        This view applies the same hard threshold as the parent:
        - IBIs > 2 seconds are set to NaN (labels are not mutated here).
        """
        t = self.times
        if t.size < 2:
            return np.asarray([np.nan], dtype=float)

        ibi_sec = np.diff(t)
        too_long_mask = ibi_sec > 2.0
        if np.any(too_long_mask):
            ibi_sec = ibi_sec.astype(float, copy=True)
            ibi_sec[too_long_mask] = np.nan

        return np.concatenate([ibi_sec, np.array([np.nan], dtype=float)])

    def view(self, starttime: float, endtime: float) -> "CardioSeriesView":
        """
        Create a sub-view from this view by time range.

        Parameters
        ----------
        starttime:
            Start time in seconds (inclusive).
        endtime:
            End time in seconds (inclusive).

        Returns
        -------
        CardioSeriesView
            Sub-view referencing the same parent.
        """
        mask = (self.times >= starttime) & (self.times <= endtime)
        sub_view = CardioSeriesView(self._parent, self._idx[mask])
        sub_view._pd = self._pd
        sub_view._stream = self._stream
        sub_view._epoch = None
        return sub_view

    def welch_psd(self, **kwargs):
        """
        Compute Welch PSD for this view.

        Implementation detail
        ---------------------
        Welch expects a contiguous numeric series. This method constructs a temporary
        `CardioSeries` from the view's `times` and delegates to the parent implementation.
        """
        tmp = CardioSeries(self.times)
        tmp._pd = self._pd
        tmp._stream = self._stream
        return tmp.welch_psd(**kwargs)

    def __repr__(self) -> str:
        return f"CardioSeriesView(n={self.times.size}, stream={self._stream!r}, epoch={self._epoch!r})"
