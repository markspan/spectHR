# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Interaction state for the pre-processing timeline view.

These containers hold everything about *how the user is looking at* the
recording — the visible time window, an in-progress overview drag, and the
per-axis y-zoom — without holding any of the recording itself.  Keeping
them separate from :class:`~spectHR.session.Session` means the data model
stays pure and immutable while the view stays mutable and cheap, and it
lets the navigation arithmetic be unit-tested with no Qt or matplotlib in
sight.

V2 stored the equivalent of :class:`WindowState` on the ``PhysioData``
object as ``data.view``.  Here it lives on the widget instead, so two
docks never silently fight over one shared window and the session can be
handed to headless analysis code untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class YAxisState:
    """Manual y-limits for one axis, or ``auto`` to let matplotlib decide.

    The breathing overlay supports keyboard y-zoom (``+`` / ``-`` / arrows);
    each axis that does keeps one of these so the chosen limits survive a
    redraw.  ``auto=True`` means "ignore ``ymin`` / ``ymax`` and autoscale".
    """

    auto: bool = True
    ymin: float | None = None
    ymax: float | None = None

    def reset(self) -> None:
        """Return to autoscaling and forget any manual limits."""
        self.auto = True
        self.ymin = None
        self.ymax = None


@dataclass
class WindowState:
    """The visible time window plus any transient overview-drag gesture.

    Attributes
    ----------
    x_min, x_max
        Boundaries of the visible window, in seconds.
    drag_mode
        ``None`` when no overview drag is active, else ``"left"``,
        ``"right"`` or ``"center"`` to say which part of the window
        rectangle the user grabbed.
    initial_xmin, initial_xmax
        Window boundaries captured at the moment the drag started, so a
        ``"center"`` drag can translate the whole window rigidly.
    y
        Per-axis :class:`YAxisState`, keyed by a short axis tag.  Only the
        breathing overlay (``"br"``) is tracked today, but the dict keeps
        the door open for more.
    """

    x_min: float
    x_max: float
    drag_mode: str | None = None
    initial_xmin: float | None = None
    initial_xmax: float | None = None
    y: dict[str, YAxisState] = field(default_factory=lambda: {"br": YAxisState()})

    # --- derived ---

    def width(self) -> float:
        """Window width in seconds."""
        return self.x_max - self.x_min

    def center(self) -> float:
        """Midpoint of the window in seconds."""
        return 0.5 * (self.x_min + self.x_max)

    # --- drag lifecycle ---

    def begin_drag(self, mode: str) -> None:
        """Record the start of an overview drag in *mode*.

        Snapshots the current window into ``initial_xmin`` / ``initial_xmax``
        so a centre drag can be applied as a rigid translation.
        """
        self.drag_mode = mode
        self.initial_xmin = self.x_min
        self.initial_xmax = self.x_max

    def end_drag(self) -> bool:
        """Clear drag state; return ``True`` if a drag was actually active."""
        was_active = self.drag_mode is not None
        self.drag_mode = None
        self.initial_xmin = None
        self.initial_xmax = None
        return was_active
