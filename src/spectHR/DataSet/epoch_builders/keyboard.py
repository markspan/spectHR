# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
keyboard.py – XDF-specific fallback epoch builder.

When an XDF recording lacks explicit ``"start <x>"`` / ``"stop <x>"`` markers
but does carry a ``Keyboard`` event stream, we synthesise consecutive,
non-overlapping epochs from key-press events:

* Every ``"<key> pressed"`` marker starts a new epoch named after that key.
* The epoch ends at the next key-press, or at the end of the recording for
  the final one.
* If the same key is pressed more than once its epochs are numbered
  (``"a #1"``, ``"a #2"``, …) so the output dictionary keys stay unique.

The function mutates its input ``physiodata`` so the synthesised epoch
markers participate in the standard ``build_epochs_from_markers`` pass that
runs later.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from spectHR.DataSet.Series.EventSeries import EventSeries
from spectHR.Tools.Logger import logger


# Every keyboard marker we care about ends with this exact suffix.
_PRESSED_SUFFIX = " pressed"


def _has_existing_epoch_markers(events: dict) -> bool:
    """
    True if any marker label already starts with ``"start "`` or ``"stop "``.

    The keyboard fallback only fires when *no* such markers exist; otherwise
    the recording already provides its own epoch boundaries.
    """
    for ev in events.values():
        for label in ev.labels:
            text = str(label).strip().lower()
            if text.startswith(("start ", "stop ")):
                return True
    return False


def _find_keyboard_event_series(events: dict) -> EventSeries | None:
    """Return the case-insensitive ``"keyboard"`` EventSeries, or None."""
    for name, ev in events.items():
        if name.lower() == "keyboard":
            return ev
    return None


def _recording_end_time(physiodata, fallback: float) -> float:
    """Return the latest TimeSeries timestamp, or ``fallback`` if none exist."""
    if not physiodata.timeseries:
        return float(fallback)
    finite_ends = [
        ts.times[-1] for ts in physiodata.timeseries.values() if ts.times.size
    ]
    return float(max(finite_ends)) if finite_ends else float(fallback)


def _make_unique_epoch_names(base_names: list[str]) -> list[str]:
    """
    Disambiguate repeated names in *base_names*.

    Single occurrences keep their bare name; repeats become
    ``"<key>#1"``, ``"<key>#2"``, ... in original encounter order.
    """
    occurrences = Counter(base_names)
    seen: dict[str, int] = {}
    unique: list[str] = []

    for base in base_names:
        if occurrences[base] == 1:
            unique.append(base)
        else:
            seen[base] = seen.get(base, 0) + 1
            unique.append(f"{base}#{seen[base]}")

    return unique


def build_keyboard_epoch_events(physiodata) -> EventSeries | None:
    """
    Synthesise ``Start <name>`` / ``Stop <name>`` markers from ``Keyboard``
    key-press events when no real epoch markers are present.

    Side-effect
    -----------
    On success this function adds an entry ``"KeyboardEpochs"`` to
    ``physiodata.events``.  If no fallback is needed (or possible) the
    function is a no-op.

    Returns
    -------
    EventSeries | None
        The synthesised marker stream, or ``None`` when nothing was done.
        The return value is mainly useful for tests and diagnostics - the
        caller normally ignores it because the side-effect on
        ``physiodata.events`` is what drives later epoch parsing.
    """
    if _has_existing_epoch_markers(physiodata.events):
        return None

    keyboard_ev = _find_keyboard_event_series(physiodata.events)
    if keyboard_ev is None:
        return None

    # Pick out every label that ends with " pressed".
    pressed_mask = np.asarray(
        [str(lbl).lower().endswith(_PRESSED_SUFFIX) for lbl in keyboard_ev.labels],
        dtype=bool,
    )
    pressed_times = keyboard_ev.times[pressed_mask]
    pressed_labels = np.asarray(keyboard_ev.labels, dtype=object)[pressed_mask]

    if pressed_times.size == 0:
        logger.info(
            "Keyboard stream found but contains no 'pressed' markers - "
            "no fallback epochs created."
        )
        return None

    # Strip " pressed" → bare key name.
    base_names = [str(lbl)[: -len(_PRESSED_SUFFIX)].strip() for lbl in pressed_labels]
    epoch_names = _make_unique_epoch_names(base_names)

    # Recording end: last timestamp across all loaded timeseries, or the
    # last pressed-marker time if no timeseries exist.
    recording_end = _recording_end_time(physiodata, fallback=pressed_times[-1])

    # Build alternating Start / Stop entries.  The standard
    # ``build_epochs_from_markers`` consumes these later.
    raw_times: list[float] = []
    raw_labels: list[str] = []

    for i, (start_time, name) in enumerate(zip(pressed_times, epoch_names)):
        end_time = (
            float(pressed_times[i + 1]) if i + 1 < pressed_times.size else recording_end
        )
        raw_times.extend([float(start_time), end_time])
        raw_labels.extend([f"Start {name}", f"Stop {name}"])

    keyboard_epochs = EventSeries(np.asarray(raw_times, dtype=float), raw_labels)
    physiodata.events["KeyboardEpochs"] = keyboard_epochs

    logger.info(
        f"Keyboard fallback: created {pressed_times.size} epoch(s) "
        f"from 'pressed' markers - {epoch_names}"
    )
    return keyboard_epochs
