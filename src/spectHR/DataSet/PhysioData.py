from __future__ import annotations

from pathlib import Path
import pickle
from typing import Any, Dict

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.DataSet.Series.RespirationSeries import RespirationSeries
from spectHR.DataSet.Epoch import Epoch, Phase  
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
    - epochs     : dict[str, Epoch]      (global)
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

    # ------------------------------------------------------------
    # Construction & loading
    # ------------------------------------------------------------
    def __init__(self, filename: str, **kwargs: Any) -> None:
        self.filename = filename
        self.basename = Path(filename).stem

        # Core containers (always defined)
        self.timeseries: Dict[str, TimeSeries] = {}
        self.events: Dict[str, EventSeries] = {}

        self.epochs: Dict[str, Epoch] = {}
        self.phases: dict[str, Phase] = {}

        self.band_map: dict[str, dict[str, str]] = {}
        self.active_band: str | None = None
        self.hrv_map: dict[str, CardioSeries] = {}
        self.rsp_map: dict[str, RespirationSeries] = {}

        # Load using registered loader
        loader = get_loader(filename)
        if loader is None:
            raise ValueError(f"No loader registered for file: {filename}")

        loader(self, filename, **kwargs)

        # Optional back-reference for convenience (never required)
        for ts in self.timeseries.values():
            ts._pd = self  # soft reference

        self._normalize_times_and_build_epochs()

    # ------------------------------------------------------------
    # Time normalization & epoch construction
    # ------------------------------------------------------------
    def _normalize_times_and_build_epochs(self) -> None:
        """
        Normalize all TimeSeries so the global earliest time maps to t=0.

        Build ONE global epoch table from all EventSeries.

        Epoch parsing convention
        ------------------------
        - "start <label>" starts an epoch
        - "stop <label>" or "end <label>" ends an epoch
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

            bounds_start = 0.0
            bounds_end = float(latest - earliest)
        else:
            # Safe fallback if no signals exist
            earliest = 0.0
            bounds_start = 0.0
            bounds_end = 1.0

        epochs: Dict[str, Epoch] = {
            "experiment": Epoch(active=True, start=bounds_start, end=bounds_end)
        }

        # Parse marker streams
        for ev in self.events.values():
            times = ev.times - earliest
            labels = ev.labels
            ongoing: Dict[str, float] = {}

            for t, raw in zip(times, labels):
                text = str(raw).strip().lower()
                if text.startswith("end "):
                    text = "stop " + text[4:]

                if text.startswith("start "):
                    label = text[6:].strip()
                    ongoing[label] = float(t)

                elif text.startswith("stop "):
                    label = text[5:].strip()
                    start = ongoing.pop(label, bounds_start)
                    epochs[label] = Epoch(active=True, start=start, end=float(t))

            # Epochs without explicit stop
            for label, start in ongoing.items():
                epochs[label] = Epoch(active=True, start=float(start), end=bounds_end)

        self.epochs = epochs

        logger.info(
            f"Built {len(self.epochs)} epochs. "
            f"Normalized time range: {bounds_start:.3f}–{bounds_end:.3f} s."
        )

    # ------------------------------------------------------------
    # Dataset access
    # ------------------------------------------------------------
    def __getitem__(self, key: str) -> StreamAccessor:
        """
        Dataset access.

        Supports
        --------
        - Physical access:
            data["ecg-[band]"]
        - Band-aware logical access:
            data["ecg"], data["rsp"] (via active_band + band_map)
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

    # ------------------------------------------------------------
    # Derived data access
    # ------------------------------------------------------------
    @property
    def hrv(self) -> CardioSeries | None:
        """
        CardioSeries for the active band (if available).
        """
        if self.active_band is None:
            return None
        return self.hrv_map.get(self.active_band)

    # ------------------------------------------------------------
    # ECG preprocessing (NEW)
    # ------------------------------------------------------------
    def preprocess_ecg(
        self,
        *,
        # Filtering
        filter_type: str = "highpass",
        filter_cutoff: float = 1.0,
        filter_order: int | None = None,
        # Peak detection
        min_peak_distance_ms: float = 300.0,
        classify: bool = True,
    ) -> None:
        """
        Preprocess ECG for all ECG bands.

        Steps (per band)
        ----------------
        1. Filter ECG TimeSeries
        2. Detect R-peaks
        3. Create or update CardioSeries
        4. Create or update RespirationSeries
        All operations are in-place.
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
                    classify=classify,
                )
                cs._pd = self
                cs._stream = band
                self.hrv_map[band] = cs
            else:
                for name, epoch in self.epochs.items():
                    if not epoch.active:
                        continue
                    if not epoch.is_valid:
                        continue

                    start, end = epoch.bounds   # (start, end)

                    cs.replace_from_timeseries(
                        ecg_ts,
                        start=start,
                        end=end,
                        min_peak_distance_ms=min_peak_distance_ms,
                        classify=classify,
                    )
            # --- RESPIRATION preprocessing (new) ---
            try:
                rsp_ts = self["rsp"].timeseries
            except KeyError:
                rsp_ts = None

            if rsp_ts is not None:
                logger.info(f"Preprocessing RESP band '{band}'")
                resp = RespirationSeries.from_timeseries(rsp_ts)
                resp._pd = self
                resp._stream = band
                self.rsp_map[band] = resp

                # --------------------------------------------------
                # Derive Phase objects from RespirationSeries
                # --------------------------------------------------
                if rsp_ts is not None and resp is not None and len(resp) > 0:

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

                    # Store band-specific phases (namespaced)
                    self.phases[f"inh-{band}"] = Phase(
                        active=True,
                        intervals=inh_intervals,
                    )

                    self.phases[f"exh-{band}"] = Phase(
                        active=True,
                        intervals=exh_intervals,
                    )
                    
        self.active_band = original_band or bands[0]

    # ------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------
    def save(self, path: Path) -> None:
        """
        Save the PhysioData object to disk as a pickle (.pkl).
        """
        path = Path(path).with_suffix(".pkl")
        with path.open("wb") as f:
            pickle.dump(self, f)

        logger.info(f"PhysioData saved to {path}")
