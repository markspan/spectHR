# CardioSeries.py
from __future__ import annotations

from typing import TYPE_CHECKING, List, Dict
import numpy as np
import pandas as pd
from scipy.signal import welch
from scipy.interpolate import interp1d
from scipy.stats import chi2

from spectHR.DataSet.HRVMetrics import HRVMetric, hrv_metric

if TYPE_CHECKING:
    from spectHR.DataSet.PhysioData import PhysioData


class CardioSeries(HRVMetric):
    """
    Stores R-peak times and labels.

    Design role
    -----------
    - Owns R-peak times/labels
    - Does NOT build epochs itself; uses PhysioData.epochs when linked
    - Produces zero-copy views (CardioSeriesView)
    - Views can carry identity metadata: (_pd, _stream, _epoch)
    """

    METRIC_ORDER = [
        "count", "mean", "median", "min", "max", "std",
        "rmssd", "sdnn", "sdsd",
        "sd1", "sd2", "sd_ratio", "ellipse_area",
        "vlf_power", "lf_power", "hf_power", "lf_hf_ratio",
    ]

    def __init__(self, times: np.ndarray):
        self.times = np.asarray(times, dtype=float)
        self.labels = np.full(self.times.shape, "N", dtype=object)

        # Assigned externally (e.g., by calcPeaks / PhysioData integration)
        self._pd: PhysioData | None = None

        # Optional identity for the series itself (useful if multiple bands)
        self._stream: str | None = None

    @property
    def ibi(self) -> np.ndarray:
        if self.times.size < 2:
            return np.asarray([], dtype=float)
        diff = np.diff(self.times)
        return np.concatenate([diff, np.array([np.nan])])

    def __getitem__(self, epoch_label: str) -> "CardioSeriesView":
        """
        Epoch slicing via PhysioData. Requires self._pd linkage.
        Returns a view stamped with identity.
        """
        if self._pd is None:
            raise RuntimeError(
                "CardioSeries is not connected to a PhysioData instance. "
                "Assign HRV._pd = physiodata."
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
        Identity-neutral view by time.
        If self._pd is present, we propagate pd/stream but epoch remains None.
        """
        idx = np.where((self.times >= starttime) & (self.times <= endtime))[0]
        view = CardioSeriesView(self, idx)
        view._pd = self._pd
        view._stream = self._stream
        view._epoch = None
        return view

    def _ibi_clean_ms(self) -> np.ndarray:
        x = self.ibi
        return 1000.0 * x[~np.isnan(x)]

    def welch_psd_with_ci(
        self,
        *,
        fs: float = 4.0,
        nperseg: int = 256,
        noverlap: int = 128,
        window: str = "hamming",
        interpolate: bool = True,
        alpha: float = 0.05,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
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

        lower = (nu * psd) / chi2.ppf(1 - alpha / 2, nu)
        upper = (nu * psd) / chi2.ppf(alpha / 2, nu)

        return freqs, psd, lower, upper

    def welch_psd(
        self,
        *,
        fs: float = 4.0,
        nperseg: int = 256,
        noverlap: int = 128,
        window: str = "hamming",
        interpolate: bool = True,
    ) -> tuple[np.ndarray, np.ndarray]:
        ibi = self._ibi_clean_ms()
        if ibi.size == 0:
            return np.ndarray(0), np.ndarray(0)

        if ibi.size < nperseg:
            nperseg = ibi.size
            noverlap = int(ibi.size / 2) if ibi.size >= 2 else 0

        times = self.times[:ibi.size]

        try:
            if interpolate and times.size >= 2:
                t_uniform = np.arange(times[0], times[-1], 1.0 / fs)
                ibi = interp1d(
                    times,
                    ibi,
                    kind="linear",
                    fill_value="extrapolate",
                )(t_uniform)
        except Exception:
            return np.ndarray(0), np.ndarray(0)

        freqs, power = welch(
            ibi,
            fs=fs,
            scaling="density",
            nfft=1024,
            nperseg=nperseg,
            noverlap=noverlap,
            window=window,
        )
        return freqs, power

    # ---------------- HRV metrics ----------------

    @hrv_metric
    def count(self) -> int:
        x = self._ibi_clean_ms()
        return int(x.size)

    @hrv_metric
    def mean(self) -> float:
        x = self._ibi_clean_ms()
        return float(np.mean(x)) if x.size else np.nan

    @hrv_metric
    def std(self) -> float:
        x = self._ibi_clean_ms()
        return float(np.std(x)) if x.size else np.nan

    @hrv_metric
    def min(self) -> float:
        x = self._ibi_clean_ms()
        return float(np.min(x)) if x.size else np.nan

    @hrv_metric
    def max(self) -> float:
        x = self._ibi_clean_ms()
        return float(np.max(x)) if x.size else np.nan

    @hrv_metric
    def median(self) -> float:
        x = self._ibi_clean_ms()
        return float(np.median(x)) if x.size else np.nan

    @hrv_metric
    def rmssd(self) -> float:
        x = self._ibi_clean_ms()
        if x.size < 2:
            return np.nan
        diff = np.diff(x)
        return float(np.sqrt(np.mean(diff * diff)))

    @hrv_metric
    def sdnn(self) -> float:
        x = self._ibi_clean_ms()
        return float(np.std(x)) if x.size else np.nan

    @hrv_metric
    def sdsd(self) -> float:
        x = self._ibi_clean_ms()
        if x.size < 2:
            return np.nan
        diff = np.diff(x)
        return float(np.std(diff))

    @hrv_metric
    def sd1(self) -> float:
        x = self._ibi_clean_ms()
        if x.size < 2:
            return np.nan
        x1, x2 = x[:-1], x[1:]
        m = (x1 - x2) / np.sqrt(2)
        return float(np.std(m))

    @hrv_metric
    def sd2(self) -> float:
        x = self._ibi_clean_ms()
        if x.size < 2:
            return np.nan
        x1, x2 = x[:-1], x[1:]
        m = (x1 + x2) / np.sqrt(2)
        return float(np.std(m))

    @hrv_metric
    def sd_ratio(self) -> float:
        s1, s2 = self.sd1(), self.sd2()
        return float(s1 / s2) if s2 != 0 and not np.isnan(s1) and not np.isnan(s2) else np.nan

    @hrv_metric
    def ellipse_area(self) -> float:
        s1, s2 = self.sd1(), self.sd2()
        return float(np.pi * s1 * s2) if not np.isnan(s1) and not np.isnan(s2) else np.nan

    @hrv_metric
    def vlf_power(self) -> float:
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, 0.003, 0.04)

    @hrv_metric
    def lf_power(self) -> float:
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, 0.04, 0.15)

    @hrv_metric
    def hf_power(self) -> float:
        freqs, power = self.welch_psd()
        return self._band_power_exact(freqs, power, 0.15, 0.4)

    @hrv_metric
    def lf_hf_ratio(self) -> float:
        lf = self.lf_power()
        hf = self.hf_power()
        return lf / hf if hf > 0 else np.nan

    def hrv_epoch_table(self, physiodata: PhysioData) -> pd.DataFrame:
        rows: List[Dict[str, float]] = []
        for label, ep in physiodata.epochs.items():
            if ep.active:
                rows.append({"epoch": label, **self.metric_table_epoch(ep.start, ep.end)})

        df = pd.DataFrame(rows).set_index("epoch")

        if hasattr(self, "METRIC_ORDER"):
            cols = [c for c in self.METRIC_ORDER if c in df.columns]
            df = df[cols]

        if "count" in df.columns:
            df["count"] = df["count"].astype("Int64")

        return df

    def _band_power_exact(
        self,
        freqs: np.ndarray,
        power: np.ndarray,
        f0: float,
        f1: float,
    ) -> float:
        if freqs.size == 0:
            return np.nan

        mask = (freqs > f0) & (freqs < f1)
        if not np.any(mask):
            return np.nan

        p0 = np.interp(f0, freqs, power)
        p1 = np.interp(f1, freqs, power)

        f_band = np.concatenate(([f0], freqs[mask], [f1]))
        p_band = np.concatenate(([p0], power[mask], [p1]))

        return 1000.0 * np.trapezoid(p_band, f_band)


class CardioSeriesView(CardioSeries):
    """
    Zero-copy view into a CardioSeries.

    Identity
    --------
    Carries:
    - _pd
    - _stream
    - _epoch
    """

    def __init__(self, parent: CardioSeries, indices: np.ndarray):
        self._parent = parent
        self._idx = np.asarray(indices, dtype=int)

        # Identity metadata (assigned by parent/view logic)
        self._pd: PhysioData | None = parent._pd
        self._stream: str | None = parent._stream
        self._epoch: str | None = None

    @property
    def times(self) -> np.ndarray:
        return self._parent.times[self._idx]

    @property
    def labels(self) -> np.ndarray:
        return self._parent.labels[self._idx]

    @property
    def ibi(self) -> np.ndarray:
        t = self.times
        if t.size < 2:
            return np.asarray([np.nan])
        diff = np.diff(t)
        return np.concatenate([diff, np.array([np.nan])])

    def view(self, starttime: float, endtime: float) -> "CardioSeriesView":
        mask = (self.times >= starttime) & (self.times <= endtime)
        view = CardioSeriesView(self._parent, self._idx[mask])
        view._pd = self._pd
        view._stream = self._stream
        view._epoch = None
        return view

    def welch_psd(self, **kwargs):
        tmp = CardioSeries(self.times)
        tmp._pd = self._pd
        tmp._stream = self._stream
        return tmp.welch_psd(**kwargs)

    def __repr__(self) -> str:
        return f"CardioSeriesView(n={self.times.size}, stream={self._stream!r}, epoch={self._epoch!r})"
