# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
:class:`TimelineModel`, the per-load state shared by every timeline dock.

A timeline dock always needs the same four things: the loaded
:class:`~spectHR.session.Session`, the visible :class:`WindowState`, the
:class:`TimelineNavigator` that zooms / pans it, and the recording
``extent`` navigation clamps to.  This base bundles them (and builds the
window + navigator from a signal extent) so concrete docks subclass it and
add only their own derived data, the ECG channels for the pre-processor,
the heart-rate series for the tachogram, and so on.

The widget holds one ``TimelineModel | None``: present means *loaded*,
``None`` means *nothing yet*, one question instead of a dozen ``is None``
checks.
"""
from __future__ import annotations

from dataclasses import dataclass

from spectHR.session import Session
from spectUI.widgets.timeline.navigation import TimelineNavigator
from spectUI.widgets.timeline.state import WindowState


@dataclass
class TimelineModel:
    """Session + visible window + navigator + recording extent.

    Subclasses add their derived data and provide a ``build`` classmethod
    that resolves the channel(s), computes the ``extent`` and calls
    :meth:`open_window`.
    """

    session: Session
    window: WindowState
    navigator: TimelineNavigator
    extent: tuple[float, float] | None

    @staticmethod
    def open_window(
        extent: tuple[float, float] | None,
    ) -> "tuple[WindowState, TimelineNavigator]":
        """Build a full-extent window and a navigator clamped to *extent*.

        The signal extent never changes during a session, so the navigator
        closes over a constant rather than re-reading a channel on every move.
        """
        t0, t1 = extent if extent is not None else (0.0, 1.0)
        window = WindowState(x_min=t0, x_max=t1)
        navigator = TimelineNavigator(window, lambda e=extent: e)
        return window, navigator
