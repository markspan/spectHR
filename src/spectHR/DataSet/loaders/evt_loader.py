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

    if not any("[Data]" in line for line in lines):
        lines.insert(0, "[Data]\n")

    # --------------------------------------------------
    # Parse [Data] section
    # --------------------------------------------------
    in_data = False
    event_codes = []
    times = []

    for line in lines:
        if line.strip() == "[Data]":
            in_data = True
            continue

        if not in_data:
            continue

        parts = line.strip().split()
        if len(parts) < 2:
            continue

        try:
            code = int(parts[0])
            time = float(parts[1])
        except ValueError:
            continue

        event_codes.append(code)
        times.append(time)

    if not times:
        raise ValueError("EVT file contains no valid data.")

    event_codes = np.asarray(event_codes)
    times = np.asarray(times)

    # --------------------------------------------------
    # Determine RTop code (most frequent)
    # --------------------------------------------------
    rtop_code = Counter(event_codes).most_common(1)[0][0]
    logger.info(f"RTop event code assumed to be {rtop_code}")

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
