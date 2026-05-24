# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
start_stop.py – Standard ``start <name>`` / ``stop <name>`` epoch builder.

Originally lived inside ``PhysioData._normalize_times_and_build_epochs``.
Extracted into its own module so the parsing rules are easy to find,
easy to test in isolation, and don't bury the time-normalisation logic
in PhysioData.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from spectHR.DataSet.Epoch import Epoch
from spectHR.DataSet.Series.EventSeries import EventSeries


def build_epochs_from_markers(
    events:        Mapping[str, EventSeries],
    *,
    earliest:      float,
    bounds_start:  float,
    bounds_end:    float,
) -> dict[str, Epoch]:
    """
    Parse every ``EventSeries`` for ``start <name>`` / ``stop <name>`` pairs
    and turn them into Epoch objects.

    Convention
    ----------
    * ``"start <label>"``                begins an epoch.
    * ``"stop <label>"`` or ``"end <label>"``  ends the matching epoch.
    * Missing stop markers leave the epoch running until ``bounds_end``.
    * One synthetic ``"experiment"`` epoch always exists and spans
      ``[bounds_start, bounds_end]``.

    Time normalisation
    ------------------
    Marker timestamps are shifted by ``-earliest`` so they align with the
    already-normalised TimeSeries clocks.

    Parameters
    ----------
    events : mapping of name → EventSeries
        The marker streams collected by the loader (``physiodata.events``).
    earliest : float
        Reference time (s) that maps to ``0.0`` after normalisation.
    bounds_start, bounds_end : float
        Edges of the global ``"experiment"`` epoch, already normalised.

    Returns
    -------
    dict[str, Epoch]
        ``{epoch_label: Epoch}``, always containing the ``"experiment"``
        entry plus one entry per matched start/stop pair.
    """
    epochs: dict[str, Epoch] = {
        "experiment": Epoch(active=True, start=bounds_start, end=bounds_end),
    }

    # Track epochs that have seen a "start" but not yet a "stop".
    ongoing: dict[str, float] = {}

    for ev in events.values():
        normalised_times = ev.times - earliest
        labels: Iterable[object] = ev.labels

        for t, raw in zip(normalised_times, labels):
            text = str(raw).strip().lower()
            # Permit both "stop <x>" and the historical "end <x>" alias.
            if text.startswith("end "):
                text = "stop " + text[4:]

            if text.startswith("start "):
                label = text[6:].strip()
                ongoing[label] = float(t)
            elif text.startswith("stop "):
                label = text[5:].strip()
                start = ongoing.pop(label, bounds_start)
                epochs[label] = Epoch(active=True, start=start, end=float(t))

    # Anything still in `ongoing` had a start but no matching stop - close
    # those epochs at the end of the recording.
    for label, start in ongoing.items():
        epochs[label] = Epoch(active=True, start=float(start), end=bounds_end)

    return epochs
