# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
spectHR.DataSet.epoch_builders – Functions that turn marker streams into
epochs.

Two builders live here:

* :func:`build_epochs_from_markers`
    Standard ``"start <name>"`` / ``"stop <name>"`` parsing used by
    :class:`PhysioData` after every loader has run.

* :func:`build_keyboard_epoch_events`
    XDF-specific fallback: when the file has no explicit start/stop
    markers but does have a ``Keyboard`` stream, derive consecutive
    epochs from the ``"<key> pressed"`` markers.
"""

from __future__ import annotations

from spectHR.DataSet.epoch_builders.start_stop import build_epochs_from_markers
from spectHR.DataSet.epoch_builders.keyboard import build_keyboard_epoch_events

__all__ = [
    "build_epochs_from_markers",
    "build_keyboard_epoch_events",
]
