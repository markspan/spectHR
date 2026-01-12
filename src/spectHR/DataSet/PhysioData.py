from __future__ import annotations

from pathlib import Path
import pickle
from typing import Any, Dict

from spectHR.DataSet.Series.TimeSeries import TimeSeries
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.DataSet.Epoch import Epoch
from spectHR.DataSet.loaders import get_loader
from spectHR.DataSet.StreamAccessor import StreamAccessor
from spectHR.Tools.Logger import logger


class PhysioData:
    """
    Core physiological dataset.

    Owns
    ----
    - timeseries: dict[str, TimeSeries]
    - events:     dict[str, EventSeries]
    - epochs:     dict[str, Epoch]  (global)
    - band_map:   dict[band, {"ecg": streamname, "rsp": streamname, ...}]
    - active_band: str | None
    - hrv_map:    dict[band, CardioSeries]
    """

    def __init__(self, filename: str, **kwargs: Any) -> None:
        self.filename = filename
        self.basename = Path(filename).stem

        # Always defined
        self.band_map: dict[str, dict[str, str]] = {}
        self.active_band: str | None = None

        self.timeseries: Dict[str, TimeSeries] = {}
        self.events: Dict[str, EventSeries] = {}
        self.epochs: Dict[str, Epoch] = {}
        self.hrv_map: dict[str, CardioSeries] = {}

        loader = get_loader(filename)
        if loader is None:
            raise ValueError(f"No loader registered for file: {filename}")

        loader(self, filename, **kwargs)

        # Backref for timeseries (if downstream code wants it)
        for ts in self.timeseries.values():
            ts._pd = self  # optional, but convenient

        self._normalize_times_and_build_epochs()

    # ------------------------------------------------------------
    def _normalize_times_and_build_epochs(self) -> None:
        """
        Normalize timeseries so global earliest time maps to 0.
        Build ONE global epoch table from marker streams.

        Epoch parsing convention
        ------------------------
        - "start <label>" starts an epoch
        - "stop <label>" or "end <label>" ends an epoch
        - missing stop: epoch runs until end of recording
        """
        if self.timeseries:
            earliest = min(ts.times[0] for ts in self.timeseries.values() if ts.times.size)
            latest = max(ts.times[-1] for ts in self.timeseries.values() if ts.times.size)

            for ts in self.timeseries.values():
                if ts.times.size:
                    ts.times = ts.times - earliest

            bounds_start = 0.0
            bounds_end = float(latest - earliest)
        else:
            # No timeseries loaded: define safe default experiment window
            bounds_start = 0.0
            bounds_end = 1.0
            earliest = 0.0

        epochs: Dict[str, Epoch] = {
            "experiment": Epoch(active=True, start=bounds_start, end=bounds_end)
        }

        # Parse all event streams (normalize using same earliest)
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

            # Missing stops → run to end of recording
            for label, start in ongoing.items():
                epochs[label] = Epoch(active=True, start=float(start), end=bounds_end)

        self.epochs = epochs

        logger.info(
            f"Built {len(self.epochs)} epochs. Normalized time range: "
            f"{bounds_start:.3f}–{bounds_end:.3f} s."
        )

    # ------------------------------------------------------------
    def __getitem__(self, key: str) -> StreamAccessor:
        """
        Dataset access.

        Supports:
        - Direct physical access: data["ecg-[Polar]"]
        - Band-aware logical access: data["ecg"] or data["rsp"] using active_band + band_map
        """
        k = key.lower()

        # Band-aware logical access
        if k in ("ecg", "rsp"):
            if self.active_band is None:
                raise KeyError(f"No active band set for '{k}'")
            if not self.band_map:
                raise KeyError("No band_map defined in PhysioData")

            band_streams = self.band_map.get(self.active_band, {})
            stream_name = band_streams.get(k)
            if stream_name is None:
                raise KeyError(f"No '{k}' stream for band '{self.active_band}'")

            ts = self.timeseries.get(stream_name)
            if ts is None:
                raise KeyError(f"band_map points to missing timeseries '{stream_name}'")

            return StreamAccessor(ts, self, stream_name)

        # Direct physical access
        if key not in self.timeseries:
            raise KeyError(f"No timeseries '{key}'")

        return StreamAccessor(self.timeseries[key], self, key)

    @property
    def hrv(self) -> CardioSeries | None:
        """
        Return HRV (CardioSeries) for the active band. None if unavailable.
        """
        if self.active_band is None:
            return None
        return self.hrv_map.get(self.active_band, None)

    def save(self, path: Path) -> None:
        """
        Save the PhysioData object as a pickle file. Ensures .pkl suffix.
        """
        if not isinstance(path, Path):
            path = Path(path)

        path = path.with_suffix(".pkl")
        with path.open("wb") as f:
            pickle.dump(self, f)

        logger.info(f"PhysioData saved to {path}")
