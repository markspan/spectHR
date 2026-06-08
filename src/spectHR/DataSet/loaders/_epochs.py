# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Epoch building utilities shared by all loaders."""
from __future__ import annotations

from spectHR.session import Epoch


def build_epochs(
    marker_times: list[float],
    marker_labels: list[str],
    *,
    t_start: float,
    t_end: float,
) -> dict[str, Epoch]:
    """Build a ``{label: Epoch}`` dict from start/stop marker pairs.

    Conventions:
    - ``"start <name>"`` opens an epoch.
    - ``"stop <name>"`` or ``"end <name>"`` closes it.
    - Unclosed epochs run to ``t_end``.
    - Always produces an ``"experiment"`` epoch spanning ``[t_start, t_end]``.
    """
    epochs: dict[str, Epoch] = {
        "experiment": Epoch("experiment", t_start, t_end),
    }
    ongoing: dict[str, float] = {}

    paired = sorted(zip(marker_times, marker_labels), key=lambda x: x[0])
    for t, raw in paired:
        text = str(raw).strip().lower()
        if text.startswith("end "):
            text = "stop " + text[4:]
        if text.startswith("start "):
            name = text[6:].strip()
            ongoing[name] = float(t)
        elif text.startswith("stop "):
            name = text[5:].strip()
            start = ongoing.pop(name, t_start)
            epochs[name] = Epoch(name, start, float(t))

    for name, start in ongoing.items():
        epochs[name] = Epoch(name, float(start), t_end)

    return epochs
