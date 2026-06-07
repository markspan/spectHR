# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path
import hashlib
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
from spectHR.analysis import get_metrics


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

        # Polarity detection is deferred to here so it can use a real
        # epoch as the analysis segment rather than a blind middle-third.
        self._fix_ecg_polarity()

    def _fix_ecg_polarity(self) -> None:
        """Detect and correct ECG polarity for all ECG series not already handled.

        Runs after epochs are built so a task-specific epoch can be used
        as the analysis segment. The first non-``"experiment"`` active epoch
        is preferred; if none exists, falls back to the middle third.

        Series whose ``_polarity_fixed`` flag is True are skipped;
        the flag is set here after detection so re-entrant calls are safe.
        """
        from spectHR.Tools.ECGProcessing import detect_ecg_polarity

        segment = None
        for name, epoch in self.epochs.items():
            if name != "experiment" and epoch.active:
                segment = epoch
                break

        for ts_name, ts in self.timeseries.items():
            if not ts_name.lower().startswith("ecg"):
                continue
            if ts._polarity_fixed:
                continue

            try:
                polarity = detect_ecg_polarity(
                    ts.times, ts.values, segment=segment
                )
            except Exception as exc:
                logger.warning(
                    "ECG polarity detection failed for %s: %s", ts_name, exc
                )
                continue

            if polarity == "inverted":
                ts.flip()
                logger.info(
                    "ECG polarity: %s detected as inverted → flipped "
                    "(segment: %s)",
                    ts_name,
                    segment if segment is not None else "middle third",
                )
            else:
                logger.info(
                    "ECG polarity: %s detected as normal (segment: %s)",
                    ts_name,
                    segment if segment is not None else "middle third",
                )
            ts._polarity_fixed = True

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

    def epoched_parameters_table(
        self,
        psd_method=None,
        rsa_lag_s: float = 1.0,
        rsa_max_ibi_deviation=None,
        rsa_max_rate_deviation=None,
        b_point_guard_ms: float = 30.0,
    ) -> "tuple[np.ndarray, list[str], np.ndarray]":
        """Compute every per-epoch parameter for every active epoch.

        Iterates over ``self.epochs`` and, for each active epoch, builds an
        :class:`~spectHR.analysis.epoch_context.EpochContext` over the active
        ``CardioSeries`` (``self.hrv``) restricted to that epoch's bounds.
        Each registered ``@epoch_metric`` — time-domain HRV, standard band
        powers, and beat-by-beat BP / RESP parameters — contributes one scalar
        column; the results are assembled into a rectangular matrix.

        Parameters
        ----------
        psd_method : PsdMethod or None
            Workspace-configured PSD method.  Carried on the EpochContext and
            read by the band-power metrics (and the dynamic non-standard-band
            loop) so the table values match what the PSD plot displays.  When
            ``None`` the band-power columns are ``NaN``.
        b_point_guard_ms : float
            Width (ms) of the guard zone before the ICG C-point excluded from the
            PEP B-point search (default 30; workspace ``IcgAnalysis``).

        Returns
        -------
        labels : np.ndarray, shape (n_epochs,)
            Epoch names, in iteration order.
        cols : list[str]
            Metric names, sorted alphabetically.
        values : np.ndarray, shape (n_epochs, n_metrics), dtype float64
            Metric values; NaN where a metric could not be computed.

        Returns three empty containers when no active epochs exist or no
        active HRV series is loaded.
        """
        from spectHR.analysis.psd._band_power import band_power_rectangular
        from spectHR.analysis.frequency_metrics import STANDARD_BAND_POWER_COLUMNS
        from spectHR.analysis.epoch_context import EpochContext

        hrv = self.hrv
        if hrv is None:
            return np.array([], dtype=object), [], np.empty((0, 0), dtype=float)

        # Every registered ``@epoch_metric``: time-domain HRV, the standard band
        # powers, and the beat-by-beat BP / RESP parameters.  Each is called with
        # the per-epoch EpochContext and contributes one scalar column.
        metrics = get_metrics()

        # Optional waveform channels for the beat-by-beat CARSPAN parameters.
        # Both are R-peak-gated; the EpochContext gates them on the per-epoch
        # view's ``.times``.  Absent channels make those metrics report NaN.
        try:
            bp_ts = self["bp"].timeseries
        except (KeyError, AttributeError, TypeError):
            bp_ts = None
        try:
            rsp_ts = self["rsp"].timeseries
        except (KeyError, AttributeError, TypeError):
            rsp_ts = None
        rsp_series = self.rsp_map.get(self.active_band) if self.active_band else None

        # ICG dZ/dt channel for the pre-ejection-period metric. VU-AMS EDF
        # exports store it as ``dzdt-[vuams]``; locate it by name prefix so
        # PEP is computed whenever an ICG derivative is present (NaN otherwise).
        icg_ts = None
        for _name, _ts in self.timeseries.items():
            _nl = _name.lower()
            if _nl.startswith("dzdt") or _nl.startswith("dz/dt"):
                icg_ts = _ts
                break

        # ECG waveform for Q-onset detection: improves PEP from R-to-B to the
        # true clinical Q-onset-to-B interval.
        try:
            ecg_ts_for_pep = self["ecg"].timeseries
        except (KeyError, AttributeError, TypeError):
            ecg_ts_for_pep = None

        labels_list: list = []
        rows: list[dict[str, float]] = []

        for label, ep in self.epochs.items():
            if ep.active:
                labels_list.append(label)
                view = hrv.view(ep.start, ep.end)
                rsp_phases = (
                    rsp_series.view(ep.start, ep.end)
                    if rsp_series is not None else None
                )
                ctx = EpochContext(
                    view, psd_method=psd_method, bp_ts=bp_ts, rsp_ts=rsp_ts,
                    rsp_phases=rsp_phases, rsa_lag_s=rsa_lag_s,
                    rsa_max_ibi_deviation=rsa_max_ibi_deviation,
                    rsa_max_rate_deviation=rsa_max_rate_deviation,
                    icg_ts=icg_ts, ecg_ts=ecg_ts_for_pep,
                    b_point_guard_ms=b_point_guard_ms,
                )
                row: dict[str, float] = {}

                # ---- registered single-valued metrics -------------------
                for name, fn in metrics.items():
                    try:
                        row[name] = float(fn(ctx))
                    except Exception:
                        row[name] = float("nan")

                # ---- hybrid: dynamic band powers for non-standard bands -
                # The standard bands (FullRange/VLF/LF/HF) are covered by the
                # decorated metrics above; any extra or renamed band still gets
                # its ``{name}_power`` column here, reusing the cached PSD.
                if psd_method is not None and ctx.psd is not None:
                    psd_res = ctx.psd
                    for band_name, band_spec in psd_method.bands.items():
                        col = f"{band_name.lower()}_power"
                        if col in STANDARD_BAND_POWER_COLUMNS:
                            continue
                        try:
                            row[col] = band_power_rectangular(
                                psd_res.freqs, psd_res.power,
                                band_spec.low, band_spec.high,
                            )
                        except Exception:
                            pass   # leave absent → NaN in the matrix

                rows.append(row)

        if not rows:
            return np.array([], dtype=object), [], np.empty((0, 0), dtype=float)

        keys = set().union(*(d.keys() for d in rows))
        cols = sorted(keys)
        col_idx = {c: j for j, c in enumerate(cols)}

        values = np.full((len(rows), len(cols)), np.nan, dtype=float)
        for i, d in enumerate(rows):
            for k, v in d.items():
                j = col_idx.get(k)
                values[i, j] = float(v)

        return np.asarray(labels_list, dtype=object), cols, values

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
        # IBI classification - defaults track DEFAULT_IBI_PARAMS so the three
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
        n_std : float
            Threshold width in standard deviations (default 4.0).
        max_ibi_sec : float
            Absolute IBI ceiling; longer intervals are labelled "TL"
            and excluded from statistics (default 2.0 s).

        Respiration segmentation
        ------------------------
        respiration_per_epoch : bool
            When ``True``, run respiration segmentation once per active
            epoch and concatenate; lets the prominence threshold adapt
            to each epoch's typical breathing depth. See
            :meth:`_respiration_per_epoch` for details.

        """
        if not self.band_map:
            logger.info("No band_map defined - skipping ECG preprocessing.")
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
                cs.link(self, band)
                self.hrv_map[band] = cs
            elif getattr(cs, "rtops_locked", False):
                # R-peak times are locked (loaded from a .evt file) - keep
                # them as-is. The ECG was still filtered above for display.
                logger.info(
                    f"Band '{band}': R-peak times locked, skipping re-detection."
                )
                # Still classify so IBI labels are set from the locked R-top
                # times; without this, all beats stay at the default "N".
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

        Run :meth:`RespirationSeries.from_timeseries` on each active,
        valid epoch separately, then concatenate the results. This lets
        the MAD-based prominence threshold adapt to each epoch's typical
        breathing depth rather than using one global estimate.

        The ``"experiment"`` epoch is skipped when it spans the full
        recording (the loader placeholder before task epochs are defined).
        If no usable task epochs remain, falls back to whole-signal
        segmentation so the call is never a no-op.
        """
        if rsp_ts.times.size < 5 or not getattr(self, "epochs", None):
            return RespirationSeries.from_timeseries(rsp_ts)

        total_start = float(rsp_ts.times[0])
        total_end = float(rsp_ts.times[-1])
        starts_all, ends_all, labels_all = [], [], []

        for name, epoch in self.epochs.items():
            if not epoch.active:
                continue
            if not epoch.is_valid:
                continue

            ep_start = float(epoch.start)
            ep_end = float(epoch.end)

            # Skip the default 'experiment' epoch when it still spans
            # the whole recording - running per-epoch on a single epoch
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
            # No task epoch contributed any phases - fall through to the
            # whole-recording analysis so the user still gets something
            # rather than an empty RespirationSeries.
            return RespirationSeries.from_timeseries(rsp_ts)

        return RespirationSeries(
            np.concatenate(starts_all),
            np.concatenate(ends_all),
            np.concatenate(labels_all),
        )

    def retrigger(
        self, *, min_peak_distance_ms: float = 300.0, classify: bool = True
    ) -> None:
        """Re-detect R-peaks for the active band, per active epoch.

        Rebuilds the active band's :class:`CardioSeries` from scratch:
        starts from an empty series, then re-detects peaks inside each
        active epoch's bounds and merges them. Used by the UI's
        "Retrigger ECG" action; kept here so the detection logic lives in
        the model layer rather than the window.
        """
        if self.active_band is None:
            raise RuntimeError("No active band selected")

        ecg_ts = self["ecg"].timeseries
        cs = CardioSeries.from_timeseries(
            ecg_ts,
            min_peak_distance_ms=min_peak_distance_ms,
            classify=False,
        )
        # Start empty so each epoch's detection is merged in cleanly below.
        cs.times = np.array([np.nan])
        cs.labels = np.array(["TL"], dtype=object)
        cs.link(self, self.active_band)
        self.hrv_map[self.active_band] = cs

        for epoch in self.epochs.values():
            if not epoch.active:
                continue
            ecg_view = ecg_ts.view(epoch.start, epoch.end)
            cs.replace_from_timeseries(
                ecg_view,
                start=epoch.start,
                end=epoch.end,
                min_peak_distance_ms=min_peak_distance_ms,
                classify=False,
            )

        if classify:
            cs.classify_ibi()

    def ensure_preprocessed(self, *, respiration_per_epoch: bool = False) -> bool:
        """Make sure the dataset is ready for analysis after a cold load.

        Runs ECG preprocessing when no HRV series exists yet and selects a
        default active band when none is set. Returns ``True`` if anything
        changed (so the caller can re-persist). Idempotent: a fully
        prepared dataset is left untouched.
        """
        changed = False
        if not self.hrv_map or self.active_band is None:
            if getattr(self, "has_ecg", False):
                self.preprocess_ecg(respiration_per_epoch=respiration_per_epoch)
                changed = True
            if self.active_band is None and self.band_map:
                self.active_band = next(iter(self.band_map))
                changed = True
        return changed

    def migrate_cached(self) -> bool:
        """Repair datasets pickled before later loader fixes. Idempotent.

        Returns ``True`` when a migration mutated the dataset, so the
        caller knows to re-save the cache file.

        Migration 1 - locked R-tops saved without IBI classification:
            Caches saved before the locked-branch ``classify_ibi()`` fix
            have every R-top label at the default ``"N"`` (impossible for
            real ECG of any length). Re-classify in place.

        Migration 2 - CARSPAN epoch-start convention:
            Caches saved before the epoch-start fix have epoch starts equal
            to the EVT marker time instead of the last R-peak before it.
            Detected by any non-experiment epoch start matching a
            "Start Epoch #N" time in the TaskSeries; corrected to the
            preceding R-peak.
        """
        resaved = False

        # ---- Migration 1 ------------------------------------------------
        for cs in self.hrv_map.values():
            if (
                getattr(cs, "rtops_locked", False)
                and cs.times.size > 1
                and all(lbl == "N" for lbl in cs.labels)
            ):
                logger.info(
                    "Migration 1: classifying locked R-tops saved without "
                    "IBI classification."
                )
                cs.classify_ibi()
                resaved = True

        # ---- Migration 2 ------------------------------------------------
        if "TaskSeries" in self.events:
            task_ev = self.events["TaskSeries"]
            start_marker_times = {
                float(t)
                for t, lbl in zip(task_ev.times, task_ev.labels)
                if str(lbl).lower().startswith("start ")
            }
            old_convention = any(
                abs(ep.start - smt) < 0.001
                for name, ep in self.epochs.items()
                if name != "experiment"
                for smt in start_marker_times
            )
            if old_convention:
                logger.info(
                    "Migration 2: updating CARSPAN epoch starts to the last "
                    "R-peak before each start marker."
                )
                for cs in self.hrv_map.values():
                    for name, ep in self.epochs.items():
                        if name == "experiment":
                            continue
                        if any(
                            abs(ep.start - smt) < 0.001
                            for smt in start_marker_times
                        ):
                            preceding = cs.times[cs.times < ep.start]
                            if preceding.size > 0:
                                ep.start = float(preceding[-1])
                resaved = True

        return resaved

    # ------------------------------------------------------------ #

    def save(self, path: Path) -> None:
        """Save the PhysioData object to disk as a pickle (.pkl).

        The object is serialised to memory first.  If a file already
        exists at *path* and its MD5 matches the new bytes, the write is
        skipped entirely -- avoiding unnecessary disk I/O and preventing
        the file's mtime from advancing when nothing actually changed.
        """
        path = Path(path).with_suffix(".pkl")
        data = pickle.dumps(self, protocol=pickle.HIGHEST_PROTOCOL)
        new_hash = hashlib.md5(data).digest()

        if path.exists():
            try:
                old_hash = hashlib.md5(path.read_bytes()).digest()
                if old_hash == new_hash:
                    return
            except OSError:
                pass  # can't read the old file - just overwrite

        path.write_bytes(data)
        logger.debug(f"PhysioData saved to {path}")
