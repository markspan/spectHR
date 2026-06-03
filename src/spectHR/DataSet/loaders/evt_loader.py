# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from spectHR.DataSet.loaders.registry import register_loader
from spectHR.DataSet.loaders.nff_loader import load_nff
from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.DataSet.Series.CardioSeries import CardioSeries
from spectHR.Tools.Logger import logger

# NOTE: ``EventCodeWindow`` lives in ``spectUI`` (it's a PySide6 dialog).
# We resolve it lazily inside ``_load_evt_data`` so that ``import spectHR`` works
# in headless environments - only the GUI path through .evt files with
# multiple non-RTop codes needs Qt.

# CARSPAN internal unit scale factors.
# IBI is stored in units of 0.1 ms; divide by 10 000 to get seconds.
_IBI_SCALE_TO_SECONDS = 10_000.0
# BPSys (and any future BP channel) is stored in units of 0.1 mmHg;
# divide by 10 to get mmHg.
_BP_SCALE_TO_MMHG = 10.0

@register_loader(".evt")
def load_evt(physiodata, filename: str, **kwargs: Any) -> None:
    """
    Load a CARSPAN .evt file; if a matching .nff ECG file exists, load it too.
    """
    evt_path = Path(filename)
    logger.info(f"Loading EVT: {evt_path}")
    _load_evt_data(physiodata, evt_path)
    physiodata.has_ecg = False

    nff_path = evt_path.with_suffix('.nff')
    if nff_path.exists():
        load_nff(physiodata, nff_path)
        logger.info(f"Loaded NFF ECG: {nff_path.name}")
        # Lock R-peak times: the .evt timestamps are authoritative when an
        # accompanying .nff ECG signal exists. Otherwise preprocess_ecg()
        # would re-detect peaks from the ECG and overwrite the .evt times.
        for cs in physiodata.hrv_map.values():
            cs.rtops_locked = True
    else:
        logger.info(f"No NFF file found at: {nff_path}")


def _load_evt_data(physiodata, filename: Path) -> None:
    """Load R-peak times and epoch markers from a CARSPAN .evt file.

    Opens a GUI code-selector (EventCodeWindow) when the file contains
    more than two distinct non-RTop event codes so the researcher can
    identify which codes mark epoch starts and stops.
    """

    logger.info(f"Parsing EVT: {filename.name}")

    # --------------------------------------------------
    # Read file
    # --------------------------------------------------
    with filename.open("r") as f:
        lines = f.readlines()

    # Section headers vary in case and spelling across CARSPAN exports
    # (``[Data]``/``[DATA]``, ``[Event file]``/``[Event File]``), so every
    # comparison below is done case-insensitively. Legacy exports may carry
    # no ``[Data]`` header at all; in that case the whole file is data.
    has_data_header = any(
        line.strip().lower().startswith("[data") for line in lines
    )

    # --------------------------------------------------
    # Phase 1 + 2: single pass over the file.
    #   Phase 1 - header sections ([Events], [Timeseries]) before the data.
    #   Phase 2 - the data rows themselves.
    # --------------------------------------------------
    in_events = False
    in_timeseries = False
    in_data = not has_data_header  # legacy: no header → treat everything as data

    rtop_code: int | None = None        # set from [Events] RPeak key if present
    timeseries_cols: dict[str, int] = {}  # column name → 0-based data-row index

    event_codes: list[int] = []
    times: list[float] = []
    data_rows: list[list[str]] = []     # raw split parts of each accepted data row

    for line in lines:
        stripped = line.strip()
        low = stripped.lower()

        # ``[End]`` marks end-of-data; stop reading entirely.
        if low.startswith("[end"):
            break

        # Any other bracketed line switches the active section.
        if low.startswith("["):
            in_events = low.startswith("[events")
            in_timeseries = low.startswith("[timeseries")
            in_data = low.startswith("[data")
            continue

        if in_events:
            # Find the R-peak code. Match the key prefix ``rpeak``
            # case-insensitively (``RPeak``, ``Rpeaks``, ``RPEAK`` all match).
            if "=" in stripped:
                key, _, val = stripped.partition("=")
                if key.strip().lower().startswith("rpeak"):
                    try:
                        rtop_code = int(val.strip())
                    except ValueError:
                        pass
            continue

        if in_timeseries:
            # Build the ordered extra-column map. Columns 0=code, 1=time;
            # extra time-series columns start at index 2.
            if "=" in stripped:
                name = stripped.split("=", 1)[1].strip()
                if name:
                    timeseries_cols[name] = 2 + len(timeseries_cols)
            continue

        if not in_data:
            continue

        parts = stripped.split()
        if len(parts) < 2:
            continue
        try:
            code = int(parts[0])
            time = float(parts[1])
        except ValueError:
            continue

        event_codes.append(code)
        times.append(time)
        data_rows.append(parts)

    if not times:
        raise ValueError("EVT file contains no valid data.")

    event_codes = np.asarray(event_codes)
    times = np.asarray(times)

    # --------------------------------------------------
    # Determine RTop code
    # --------------------------------------------------
    # Prefer the explicit [Events] RPeak code; fall back to the most
    # frequent code when no [Events] section declared one.
    if rtop_code is None:
        rtop_code = int(Counter(event_codes.tolist()).most_common(1)[0][0])
        logger.info(f"RTop event code inferred by frequency: {rtop_code}")
    else:
        logger.info(f"RTop event code from [Events] section: {rtop_code}")

    # --------------------------------------------------
    # Extract extra time-series columns (IBI, BPSys, ...)
    # --------------------------------------------------
    # Only R-peak rows carry the extra columns; epoch-marker rows (e.g. code
    # 11/21) have just code+time and are skipped by the width guard.
    extra_cols: dict[str, list[float]] = {name: [] for name in timeseries_cols}
    n_extra = len(timeseries_cols)
    for parts in data_rows:
        if int(parts[0]) != rtop_code:
            continue
        if len(parts) < 2 + n_extra:
            continue
        for name, idx in timeseries_cols.items():
            try:
                extra_cols[name].append(float(parts[idx]))
            except (ValueError, IndexError):
                pass

    # Scale to physical units and stash for a follow-up task. These arrays are
    # not yet wired into CardioSeries / a BPSeries (see deferral notes below);
    # they are logged at DEBUG so their presence is visible during loading.
    for name, raw in extra_cols.items():
        if not raw:
            continue
        arr = np.asarray(raw, dtype=float)
        upper = name.upper()
        if upper.startswith("IBI"):
            scaled = arr / _IBI_SCALE_TO_SECONDS  # 0.1 ms → seconds
            logger.debug(
                "EVT extra column %s: %d values, %.4f–%.4f s (deferred)",
                name, arr.size, scaled.min(), scaled.max(),
            )
            # TODO: populate a ``stored_ibi`` array on CardioSeries for
            # artifact-aware IBI access once that task is implemented.
            # See chat-mode handover document for design.
        elif upper.startswith("BP"):
            scaled = arr / _BP_SCALE_TO_MMHG  # 0.1 mmHg → mmHg
            logger.debug(
                "EVT extra column %s: %d values, %.1f–%.1f mmHg (deferred)",
                name, arr.size, scaled.min(), scaled.max(),
            )
            # TODO: construct BPSeries(times=rtop_times, sbp=sbp_values) and
            # store in physiodata.bp_map[band] once BPSeries is implemented.
            # See chat-mode handover document for design.
        else:
            logger.debug(
                "EVT extra column %s: %d values, stored raw (deferred)",
                name, arr.size,
            )

    rtop_mask = event_codes == rtop_code
    rtop_times = times[rtop_mask]

    if rtop_times.size == 0:
        raise ValueError("No RTops found in EVT file.")

    # --------------------------------------------------
    # Create CardioSeries
    # --------------------------------------------------
    # Seed a minimal band model when loading .evt without an accompanying
    # .xdf. PhysioData always initialises band_map and active_band in
    # __init__; we only fill them here when still empty (evt-only load).
    if not physiodata.band_map:
        physiodata.band_map = {"ecg": {"ecg": "ecg"}}
    if physiodata.active_band is None:
        physiodata.active_band = "ecg"

    band = physiodata.active_band

    cs = CardioSeries(rtop_times)
    cs._pd = physiodata
    physiodata.hrv_map[band] = cs

    # --------------------------------------------------
    # Determine epoch boundaries
    # --------------------------------------------------
    other_codes = event_codes[~rtop_mask]
    other_times = times[~rtop_mask]

    # Default: single epoch
    start_times = [float(times[0])]
    end_times = [float(times[-1])]

    unique_other_codes = np.unique(other_codes)

    if unique_other_codes.size > 2:
        # ----------------------------------------------
        # GUI-based code selection
        # ----------------------------------------------
        # Lazy import keeps ``spectHR`` headless-safe - the dialog lives
        # in ``spectUI`` and only this branch (a .evt file with multiple
        # non-RTop codes) reaches it.
        from spectUI.widgets.EventCodeWindow import EventCodeWindow

        window = EventCodeWindow(
            other_codes,
            ignore=rtop_code,
        )
        window.exec()

        start_codes = window.start_codes
        stop_codes = window.stop_codes

        if start_codes and stop_codes:
            start_times = other_times[np.isin(other_codes, start_codes)]
            end_times = other_times[np.isin(other_codes, stop_codes)]

            if start_times.size != end_times.size:
                raise ValueError(
                    "Selected start/stop codes produce mismatched epochs."
                )
        else:
            logger.info("No codes selected - using full recording as single epoch")

    elif unique_other_codes.size == 2:
        # Deterministic pairing
        start_times = other_times[::2]
        end_times = other_times[1::2]

        if start_times.size != end_times.size:
            raise ValueError(
                "Mismatched start/stop events in EVT file."
            )

    # Epoch-start convention: replace each start-marker time with the
    # timestamp of the last R-peak strictly before it. This matches the
    # way CARSPAN counts the preceding beat as the first of an epoch.
    # If no R-peak precedes a marker (e.g. the fallback single epoch),
    # the original marker time is kept.
    adjusted_start_times = []
    for st in start_times:
        preceding = rtop_times[rtop_times < st]
        if preceding.size > 0:
            adjusted = float(preceding[-1])
            logger.debug(
                f"Epoch start adjusted: {st:.3f} s → {adjusted:.3f} s "
                f"(last R-peak before marker)"
            )
            adjusted_start_times.append(adjusted)
        else:
            # No R-peak before this marker; keep the original marker time.
            adjusted_start_times.append(float(st))
    start_times = np.asarray(adjusted_start_times)

    # --------------------------------------------------
    # Register epochs
    # --------------------------------------------------
    raw_times = np.concatenate((start_times, end_times))
    n = len(start_times)
    raw_labels = (
        [f"Start Epoch #{i+1}" for i in range(n)] +
        [f"End Epoch #{i+1}"   for i in range(n)]
    )
    
    physiodata.events["TaskSeries"] = EventSeries(raw_times, raw_labels)
    logger.info(
        "EVT: loaded %d R-tops and %d epoch(s)", rtop_times.size, len(start_times),
    )
