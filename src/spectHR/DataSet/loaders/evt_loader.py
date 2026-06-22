# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from spectHR.DataSet.loaders.registry import register_loader
from spectHR.DataSet.loaders.nff_loader import _load_nff_samples
from spectHR.DataSet.loaders.code_selection import resolve_epoch_codes
from spectHR.logger import logger

_IBI_SCALE_TO_SECONDS = 10_000.0
_BP_SCALE_TO_MMHG = 10.0


@register_loader(".evt")
def load_evt(path: Path, **kwargs: Any) -> "Session":
    """Load a CARSPAN .evt file (+ paired .nff if present) as a Session."""
    from spectHR.session import Session, Events, Samples
    from spectHR.DataSet.loaders._epochs import build_epochs

    evt_path = Path(path)
    logger.info(f"Loading EVT: {evt_path}")

    rtop_times, marker_times, marker_labels = _parse_evt(evt_path)

    # ---- paired NFF? -------------------------------------------------------
    #
    # The NFF sample clock and the EVT event clock share one absolute time
    # base (e.g. both start at ~286.7 s for example1).  We rebase the whole
    # recording to start at 0 for display, which means shifting the NFF
    # samples *and the EVT events by the same offset*, shifting only the
    # samples (as an earlier version did) left the R-tops ~t_min_nff seconds
    # adrift of the ECG.
    samples: dict[str, Samples] = {}
    t_shift = 0.0
    nff_path = evt_path.with_suffix(".nff")
    if nff_path.exists():
        raw_samples, _cal = _load_nff_samples(nff_path)
        if raw_samples:
            t_shift = min(float(s.times[0]) for s in raw_samples.values() if s.times.size)
            samples = {k: Samples(s.times - t_shift, s.values, s.name)
                       for k, s in raw_samples.items()}
        logger.info(f"Loaded paired NFF: {nff_path.name}")

    # Rebase the EVT events into the same 0-based frame as the NFF samples.
    if t_shift:
        rtop_times = rtop_times - t_shift
        marker_times = [t - t_shift for t in marker_times]

    # ---- R-peak events -----------------------------------------------------
    labels = np.full(rtop_times.shape, "N", dtype=object)
    hrv = Events(rtop_times, labels)

    # ---- time bounds -------------------------------------------------------
    all_times = rtop_times.tolist() + marker_times
    t_start = float(min(all_times)) if all_times else 0.0
    t_end   = float(max(all_times)) if all_times else 0.0

    if samples:
        t_end = max(t_end, max(
            float(s.times[-1]) for s in samples.values() if s.times.size
        ))

    # ---- epochs -------------------------------------------------------------
    epochs = build_epochs(marker_times, marker_labels, t_start=t_start, t_end=t_end)

    return Session(
        name=evt_path.stem,
        samples=samples,
        events={"hrv": hrv},
        epochs=epochs,
    )


def _parse_evt(filename: Path):
    """Return ``(rtop_times, marker_times, marker_labels)``."""
    with filename.open("r") as f:
        lines = f.readlines()

    has_data_header = any(l.strip().lower().startswith("[data") for l in lines)

    in_events = False
    in_timeseries = False
    in_data = not has_data_header

    rtop_code: int | None = None
    # Begin/End epoch-marker codes, in declaration order (BeginBlock/EndBlock,
    # Beginperiod/Enderiod, …).  Paired by position: the k-th Begin* with the
    # k-th End*.
    begin_codes: list[int] = []
    end_codes: list[int] = []
    timeseries_cols: dict[str, int] = {}
    event_codes: list[int] = []
    times_raw: list[float] = []
    data_rows: list[list[str]] = []

    for line in lines:
        stripped = line.strip()
        low = stripped.lower()

        if low.startswith("[end"):
            break
        if low.startswith("["):
            in_events     = low.startswith("[events")
            in_timeseries = low.startswith("[timeseries")
            in_data       = low.startswith("[data")
            continue

        if in_events and "=" in stripped:
            key, _, val = stripped.partition("=")
            key_l = key.strip().lower()
            try:
                code = int(val.strip())
            except ValueError:
                continue
            if key_l.startswith("rpeak"):
                rtop_code = code
            elif key_l.startswith("begin"):
                begin_codes.append(code)
            elif key_l.startswith("end"):
                end_codes.append(code)
            continue

        if in_timeseries and "=" in stripped:
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
            t    = float(parts[1])
        except ValueError:
            continue

        event_codes.append(code)
        times_raw.append(t)
        data_rows.append(parts)

    if not times_raw:
        raise ValueError("EVT file contains no valid data.")

    event_codes_arr = np.asarray(event_codes)
    times_arr       = np.asarray(times_raw)

    if rtop_code is None:
        rtop_code = int(Counter(event_codes_arr.tolist()).most_common(1)[0][0])
        logger.info(f"RTop event code inferred by frequency: {rtop_code}")
    else:
        logger.info(f"RTop event code from [Events] section: {rtop_code}")

    rtop_mask  = event_codes_arr == rtop_code
    rtop_times = times_arr[rtop_mask]

    if rtop_times.size == 0:
        raise ValueError("No RTops found in EVT file.")

    # ---- epoch markers ------------------------------------------------------
    marker_times: list[float]  = []
    marker_labels: list[str]   = []

    pairs = list(zip(begin_codes, end_codes))
    if pairs:
        # One epoch per Begin/End *couple*, numbered across all declared pairs
        # in declaration order then time order: e.g. one Block couple (11/12)
        # then two period couples (21/22) → epoch #1, #2, #3.
        k = 0
        for bcode, ecode in pairs:
            b_times = sorted(times_arr[event_codes_arr == bcode].tolist())
            e_times = sorted(times_arr[event_codes_arr == ecode].tolist())
            for bt, et in zip(b_times, e_times):
                k += 1
                marker_times.append(float(bt)); marker_labels.append(f"start epoch #{k}")
                marker_times.append(float(et)); marker_labels.append(f"stop epoch #{k}")
        logger.info("EVT: %d epoch couple(s) from [Events] declarations", k)
    else:
        # No declared Begin/End codes: fall back to resolving the non-rtop
        # codes (single-pair heuristic, or the UI code-selection dialog).
        other_codes = event_codes_arr[~rtop_mask]
        other_times = times_arr[~rtop_mask]
        unique_other = np.unique(other_codes)
        if unique_other.size > 2:
            start_codes, stop_codes = resolve_epoch_codes(other_codes, rtop_code)
            if start_codes and stop_codes:
                for t in other_times[np.isin(other_codes, start_codes)]:
                    marker_times.append(float(t)); marker_labels.append("start epoch")
                for t in other_times[np.isin(other_codes, stop_codes)]:
                    marker_times.append(float(t)); marker_labels.append("stop epoch")
        elif unique_other.size == 2:
            for i in range(min(other_times[::2].size, other_times[1::2].size)):
                marker_times.extend([float(other_times[i*2]), float(other_times[i*2+1])])
                marker_labels.extend([f"start epoch #{i+1}", f"stop epoch #{i+1}"])

    # Adjust epoch starts to last R-peak before marker (CARSPAN convention)
    adjusted: list[float] = []
    for i, (t, label) in enumerate(zip(marker_times, marker_labels)):
        if label.startswith("start"):
            preceding = rtop_times[rtop_times < t]
            adjusted.append(float(preceding[-1]) if preceding.size > 0 else t)
        else:
            adjusted.append(t)
    marker_times = adjusted

    logger.info("EVT: loaded %d R-tops and %d epoch marker(s)",
                rtop_times.size, len(marker_times) // 2)

    return rtop_times, marker_times, marker_labels
