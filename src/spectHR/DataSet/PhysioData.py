from __future__ import annotations

from pathlib import Path
import pickle
from typing import Any

import numpy as np

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.DataSet.Series.IBIClassificationParams import DEFAULT_IBI_PARAMS
from spectHR.DataSet.Series.RespirationSeries import RespirationSeries
from spectHR.DataSet.Epoch import Epoch, Phase
from spectHR.DataSet.epoch_builders import build_epochs_from_markers
from spectHR.DataSet.loaders import get_loader
from spectHR.DataSet.StreamAccessor import StreamAccessor
from spectHR.Tools.Logger import logger


class PhysioData:
    """
    Core physiological dataset.

    Owns
    ----
    - timeseries : dict[str, TimeSeries]
    - events     : dict[str, EventSeries]
    - epochs     : dict[str, Epoch]  (global)
    - band_map   : dict[band, dict[str, str]]
    - active_band: str | None
    - hrv_map    : dict[band, CardioSeries]

    Responsibilities
    ----------------
    - Load raw data via registered loaders
    - Normalize time base
    - Build epochs from marker streams
    - Coordinate derived series (HRV, respiration, etc.)
    """

    # ------------------------------------------------------------ #
    # Construction & loading                                        #
    # ------------------------------------------------------------ #

    def __init__(self, filename: str, **kwargs: Any) -> None:
        self.filename = filename
        self.basename = Path(filename).stem

        # Core containers (always defined)
        self.timeseries:  dict[str, TimeSeries]        = {}
        self.events:      dict[str, EventSeries]       = {}
        self.epochs:      dict[str, Epoch]             = {}
        self.phases:      dict[str, Phase]             = {}
        self.band_map:    dict[str, dict[str, str]]    = {}
        self.active_band: str | None                   = None
        self.hrv_map:     dict[str, CardioSeries]      = {}
        self.rsp_map:     dict[str, RespirationSeries] = {}

        # Load using registered loader
        loader = get_loader(filename)
        if loader is None:
            raise ValueError(f"No loader registered for file: {filename}")
        loader(self, filename, **kwargs)

        # Optional back-reference for convenience (never required)
        for ts in self.timeseries.values():
            ts._pd = self  # soft reference

        self._normalize_times_and_build_epochs()

    # ------------------------------------------------------------ #
    # Time normalization & epoch construction                       #
    # ------------------------------------------------------------ #

    def _normalize_times_and_build_epochs(self) -> None:
        """
        Normalize all TimeSeries so the global earliest time maps to t=0.
        Build ONE global epoch table from all EventSeries.

        Epoch parsing convention
        ------------------------
        - "start <label>"          starts an epoch
        - "stop <label>" or
          "end <label>"            ends an epoch
        - missing stop → epoch runs until end of recording
        """
        if self.timeseries:
            earliest = min(
                ts.times[0] for ts in self.timeseries.values() if ts.times.size
            )
            latest = max(
                ts.times[-1] for ts in self.timeseries.values() if ts.times.size
            )
            for ts in self.timeseries.values():
                if ts.times.size:
                    ts.times = ts.times - earliest
            # Pre-populated R-peak series (e.g. CARSPAN .evt with .nff) carry
            # absolute timestamps from the loader and must follow the same
            # shift, otherwise rtops sit on a different clock than the ECG.
            for cs in self.hrv_map.values():
                if cs.times.size:
                    cs.times = cs.times - earliest
            bounds_start = 0.0
            bounds_end   = float(latest - earliest)
        else:
            # Safe fallback if no signals exist
            earliest     = 0.0
            bounds_start = 0.0
            bounds_end   = 1.0

        # Delegate the start/stop marker parsing to the shared builder so the
        # rules live in one place (spectHR.DataSet.epoch_builders.start_stop).
        self.epochs = build_epochs_from_markers(
            self.events,
            earliest=earliest,
            bounds_start=bounds_start,
            bounds_end=bounds_end,
        )
        logger.info(
            f"Built {len(self.epochs)} epochs. "
            f"Normalized time range: {bounds_start:.3f}–{bounds_end:.3f} s."
        )

    # ------------------------------------------------------------ #
    # Dataset access                                                #
    # ------------------------------------------------------------ #

    def __getitem__(self, key: str) -> StreamAccessor:
        """
        Dataset access.

        Supports
        --------
        - Physical access:       data["ecg-[band]"]
        - Band-aware logical:    data["ecg"], data["rsp"]
          (via active_band + band_map)
        """
        k = key.lower()

        # Band-aware logical access
        if k in ("ecg", "rsp"):
            if self.active_band is None:
                raise KeyError(f"No active band set for '{k}'")
            band_streams = self.band_map.get(self.active_band)
            if band_streams is None:
                raise KeyError(f"No band_map entry for band '{self.active_band}'")
            stream_name = band_streams.get(k)
            if stream_name is None:
                raise KeyError(f"No '{k}' stream for band '{self.active_band}'")
            ts = self.timeseries.get(stream_name)
            if ts is None:
                raise KeyError(f"band_map points to missing timeseries '{stream_name}'")
            return StreamAccessor(ts, self, stream_name)

        # Direct physical access
        ts = self.timeseries.get(key)
        if ts is None:
            raise KeyError(f"No timeseries '{key}'")
        return StreamAccessor(ts, self, key)

    # ------------------------------------------------------------ #
    # Derived data access                                           #
    # ------------------------------------------------------------ #

    @property
    def hrv(self) -> CardioSeries | None:
        """CardioSeries for the active band (if available)."""
        if self.active_band is None:
            return None
        return self.hrv_map.get(self.active_band)

    # ------------------------------------------------------------ #
    # PSD configuration                                             #
    # ------------------------------------------------------------ #

    def set_psd_method(self, psd_method) -> None:
        """Assign *psd_method* to every master CardioSeries in this dataset.

        ``hrv_map`` is the canonical ``{band_id → CardioSeries}`` mapping
        for the dataset. Setting ``psd_method`` on each master series is
        enough because ``CardioSeriesView`` delegates the attribute to
        its parent — so per-epoch views built later via
        ``CardioSeries[epoch_label]`` automatically see the same value.

        The library owns this walk so the UI can stay shape-agnostic:
        callers just do ``dataset.set_psd_method(method)``.
        """
        for series in self.hrv_map.values():
            series.psd_method = psd_method

    # ------------------------------------------------------------ #
    # ECG preprocessing                                             #
    # ------------------------------------------------------------ #

    def preprocess_ecg(
        self,
        *,
        # Filtering
        filter_type:   str   = "highpass",
        filter_cutoff: float = 1.0,
        filter_order:  int | None = None,
        # Peak detection
        min_peak_distance_ms: float = 300.0,
        # IBI classification — defaults track DEFAULT_IBI_PARAMS so the three
        # entry points (preprocess_ecg, from_timeseries, replace_from_timeseries)
        # stay in lock-step automatically.
        window_length: int   = DEFAULT_IBI_PARAMS.window_length,
        n_std:         float = DEFAULT_IBI_PARAMS.n_std,
        max_ibi_sec:   float = DEFAULT_IBI_PARAMS.max_ibi_sec,
        classify:      bool  = True,
        # Respiration segmentation
        respiration_per_epoch: bool = False,
    ) -> None:
        """
        Preprocess ECG for the active band.

        Steps
        -----
        1. Filter ECG TimeSeries
        2. Detect R-peaks → build or update CardioSeries
        3. Classify IBIs using the supplied thresholds
        4. Build RespirationSeries if accelerometer data is available

        IBI classification parameters
        ------------------------------
        window_length : int
            Centered rolling window size in beats (default 51).
            Loaded from workspace["CardioParameters"]["IbiClassification"]
            ["window_length"].
        n_std : float
            Threshold width in standard deviations (default 4.0).
        max_ibi_sec : float
            Absolute ceiling; intervals longer than this are labeled "TL"
            and excluded from all statistics (default 2.0 s).

        Respiration segmentation
        ------------------------
        respiration_per_epoch : bool
            When True, run :meth:`RespirationSeries.from_timeseries` once
            per active epoch and concatenate the results, rather than
            once over the whole recording. The peak-detection prominence
            in ``from_timeseries`` is data-driven from the signal's MAD,
            so running it per epoch lets the threshold adapt to each
            epoch's typical breath amplitude — useful when rest and task
            periods have substantially different breathing depth or
            baseline noise. The default ``experiment`` epoch is skipped
            when it still covers the full recording (a no-op fall-back
            so the flag stays safe before task epochs are defined).
            Loaded from ``workspace["RespirationAnalysis"]["per_epoch"]``.

        All parameters default to the same values as classify_ibi() so
        that calling preprocess_ecg() without arguments is safe.
        """
        if not self.band_map:
            logger.info("No band_map defined — skipping ECG preprocessing.")
            return

        original_band = self.active_band
        bands = list(self.band_map.keys())
        logger.info(f"Preprocessing ECG for {len(bands)} band(s): {bands}")

        for band in bands:
            self.active_band = band
            logger.info(f"Preprocessing ECG band '{band}'")
            self.has_ecg = True

            ecg_ts = self["ecg"].timeseries

            # 1. Filtering
            ecg_ts.filter(
                filter_type=filter_type,
                cutoff=filter_cutoff,
                order=filter_order,
                inplace=True,
            )

            # 2. CardioSeries construction / update
            cs = self.hrv_map.get(band)
            if cs is None:
                cs = CardioSeries.from_timeseries(
                    ecg_ts,
                    min_peak_distance_ms=min_peak_distance_ms,
                    window_length=window_length,
                    n_std=n_std,
                    max_ibi_sec=max_ibi_sec,
                    classify=classify,
                )
                cs._pd     = self
                cs._stream = band
                self.hrv_map[band] = cs
            elif getattr(cs, "rtops_locked", False):
                # R-peak times came from an authoritative source (e.g. CARSPAN
                # .evt) — keep them as-is.  The ECG was still filtered above
                # for display, but no re-detection runs over the epochs.
                logger.info(
                    f"Band '{band}': R-peak times locked, skipping re-detection."
                )
                # Classification must still run so that IBI labels (N, TL, S, L,
                # etc.) are populated from the EVT R-top times.  Without this,
                # all beats remain at the default "N" label set in __init__,
                # causing metrics that exclude artefact intervals (TL, SL, …)
                # to use incorrect data — and the user would need to make a
                # dummy edit in the preprocessing UI to trigger classify_ibi()
                # indirectly via RTopController.
                if classify and cs.times.size > 0:
                    cs.classify_ibi(
                        window_length=window_length,
                        n_std=n_std,
                        max_ibi_sec=max_ibi_sec,
                    )
            else:
                for name, epoch in self.epochs.items():
                    if not epoch.active:
                        continue
                    if not epoch.is_valid:
                        continue
                    start, end = epoch.bounds
                    cs.replace_from_timeseries(
                        ecg_ts,
                        start=start,
                        end=end,
                        min_peak_distance_ms=min_peak_distance_ms,
                        window_length=window_length,
                        n_std=n_std,
                        max_ibi_sec=max_ibi_sec,
                        classify=classify,
                    )

            # 3. Respiration preprocessing
            try:
                rsp_ts = self["rsp"].timeseries
            except KeyError:
                rsp_ts = None

            if rsp_ts is not None:
                logger.info(f"Preprocessing RESP band '{band}'")
                if respiration_per_epoch:
                    resp = self._respiration_per_epoch(rsp_ts)
                else:
                    resp = RespirationSeries.from_timeseries(rsp_ts)
                resp._pd     = self
                resp._stream = band
                self.rsp_map[band] = resp

                if len(resp) > 0:
                    inh_intervals = [
                        (s, e)
                        for s, e, lab in zip(resp.starts, resp.ends, resp.labels)
                        if lab == "INH"
                    ]
                    exh_intervals = [
                        (s, e)
                        for s, e, lab in zip(resp.starts, resp.ends, resp.labels)
                        if lab == "EXH"
                    ]
                    self.phases[f"inh-{band}"] = Phase(
                        active=True, intervals=inh_intervals
                    )
                    self.phases[f"exh-{band}"] = Phase(
                        active=True, intervals=exh_intervals
                    )

        self.active_band = original_band or bands[0]

    def _respiration_per_epoch(self, rsp_ts) -> "RespirationSeries":
        """Run respiration segmentation once per epoch and concatenate.

        See :meth:`preprocess_ecg` (``respiration_per_epoch=True``) for
        why we'd want this: the prominence threshold in
        :meth:`RespirationSeries.from_timeseries` is data-driven from
        the signal's own MAD/sigma, so processing per epoch lets it
        adapt to each epoch's breathing amplitude rather than averaging
        rest and task into one global threshold.

        The default ``experiment`` epoch is skipped when its bounds still
        match the full rsp time series (the placeholder that loaders
        seed before the user defines task epochs); otherwise every
        ``active`` and ``is_valid`` epoch contributes its detected
        INH/EXH phases. If no usable epochs remain, falls back to the
        whole-signal segmentation so the call is never a no-op when the
        user explicitly asked for per-epoch mode.
        """
        # Local import to avoid a circular reference at module-load time.
        from spectHR.DataSet.Series.RespirationSeries import RespirationSeries

        if rsp_ts.times.size < 5 or not getattr(self, "epochs", None):
            return RespirationSeries.from_timeseries(rsp_ts)

        total_start = float(rsp_ts.times[0])
        total_end = float(rsp_ts.times[-1])
        starts_all, ends_all, labels_all = [], [], []

        for name, epoch in self.epochs.items():
            if not getattr(epoch, "active", True):
                continue
            if hasattr(epoch, "is_valid") and not epoch.is_valid:
                continue

            ep_start = float(epoch.start)
            ep_end = float(epoch.end)

            # Skip the default 'experiment' epoch when it still spans
            # the whole recording — running per-epoch on a single epoch
            # equal to the full signal would just reproduce the
            # whole-recording case.
            covers_full = (
                abs(ep_start - total_start) < 1.0
                and abs(ep_end - total_end) < 1.0
            )
            if str(name).lower() == "experiment" and covers_full:
                continue

            sliced = rsp_ts.view(ep_start, ep_end)
            if sliced.times.size < 5:
                continue

            resp_ep = RespirationSeries.from_timeseries(sliced)
            if len(resp_ep) == 0:
                continue
            starts_all.append(resp_ep.starts)
            ends_all.append(resp_ep.ends)
            labels_all.append(resp_ep.labels)

        if not starts_all:
            # No task epoch contributed any phases — fall through to the
            # whole-recording analysis so the user still gets something
            # rather than an empty RespirationSeries.
            return RespirationSeries.from_timeseries(rsp_ts)

        return RespirationSeries(
            np.concatenate(starts_all),
            np.concatenate(ends_all),
            np.concatenate(labels_all),
        )

    # ------------------------------------------------------------ #
    # Persistence                                                   #
    # ------------------------------------------------------------ #

    def save(self, path: Path) -> None:
        """Save the PhysioData object to disk as a pickle (.pkl)."""
        path = Path(path).with_suffix(".pkl")
        with path.open("wb") as f:
            pickle.dump(self, f)
        logger.info(f"PhysioData saved to {path}")