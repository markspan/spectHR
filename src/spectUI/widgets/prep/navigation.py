# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Pure timeline-navigation arithmetic.

:class:`TimelineNavigator` turns the toolbar verbs — zoom in, zoom out,
pan, jump to the ends — into new ``[x_min, x_max]`` windows, clamped to the
signal extent.  It holds a reference to a
:class:`~spectUI.widgets.prep.state.WindowState` and a zero-argument
``extent`` callable returning ``(t_first, t_last)`` of the underlying
signal (or ``None`` when nothing is loaded).

It deliberately knows nothing about Qt, matplotlib, or the
:class:`~spectHR.session.Session`: every method mutates the window in place
and returns ``True`` when the window changed, so the widget can decide
whether a redraw is worth scheduling.  That makes the whole zoom/pan/clamp
contract unit-testable in plain Python.
"""
from __future__ import annotations

from typing import Callable

from spectUI.widgets.prep.state import WindowState

# Window-width multipliers for the zoom buttons.  Matching V2: zooming in
# keeps two-thirds of the current span, zooming out grows it by half.
_ZOOM_IN_FACTOR = 2.0 / 3.0
_ZOOM_OUT_FACTOR = 1.5

Extent = Callable[[], "tuple[float, float] | None"]


class TimelineNavigator:
    """Compute clamped window moves for a :class:`WindowState`.

    Parameters
    ----------
    state
        The window to mutate.
    extent
        Zero-argument callable returning ``(t_first, t_last)`` of the
        signal, or ``None`` when no signal is loaded.  Read fresh on every
        call so the navigator never holds a stale recording length.
    """

    def __init__(self, state: WindowState, extent: Extent) -> None:
        self._state = state
        self._extent = extent

    # ------------------------------------------------------------------
    # Clamping
    # ------------------------------------------------------------------

    def constrain(self, x_min: float, x_max: float) -> tuple[float, float]:
        """Clamp ``[x_min, x_max]`` to the signal extent, preserving width.

        A window wider than the whole recording collapses to the full
        extent.  Otherwise the window is slid inward (not truncated) so its
        width is kept exactly — the behaviour V2 users expect when panning
        into either end.
        """
        ext = self._extent()
        if ext is None:
            return x_min, x_max
        lo, hi = ext
        width = x_max - x_min
        if width >= hi - lo:
            return lo, hi
        if x_min < lo:
            x_min, x_max = lo, lo + width
        elif x_max > hi:
            x_min, x_max = hi - width, hi
        return x_min, x_max

    def _apply(self, x_min: float, x_max: float) -> bool:
        """Write a constrained window into the state; report whether it moved."""
        x_min, x_max = self.constrain(x_min, x_max)
        if x_min == self._state.x_min and x_max == self._state.x_max:
            return False
        self._state.x_min = x_min
        self._state.x_max = x_max
        return True

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def zoom_in(self) -> bool:
        """Shrink the window around its centre to two-thirds of its width."""
        cx = self._state.center()
        half = 0.5 * self._state.width() * _ZOOM_IN_FACTOR
        return self._apply(cx - half, cx + half)

    def zoom_out(self) -> bool:
        """Grow the window around its centre to 1.5× its width."""
        cx = self._state.center()
        half = 0.5 * self._state.width() * _ZOOM_OUT_FACTOR
        return self._apply(cx - half, cx + half)

    # ------------------------------------------------------------------
    # Pan
    # ------------------------------------------------------------------

    def pan_left(self) -> bool:
        """Shift the window one full width toward the start."""
        w = self._state.width()
        return self._apply(self._state.x_min - w, self._state.x_max - w)

    def pan_right(self) -> bool:
        """Shift the window one full width toward the end."""
        w = self._state.width()
        return self._apply(self._state.x_min + w, self._state.x_max + w)

    # ------------------------------------------------------------------
    # Jump to ends
    # ------------------------------------------------------------------

    def go_to_start(self) -> bool:
        """Move to the start of the recording, keeping the window width."""
        ext = self._extent()
        if ext is None:
            return False
        return self._apply(ext[0], ext[0] + self._state.width())

    def go_to_end(self) -> bool:
        """Move to the end of the recording, keeping the window width."""
        ext = self._extent()
        if ext is None:
            return False
        return self._apply(ext[1] - self._state.width(), ext[1])

    # ------------------------------------------------------------------
    # Centre on a point
    # ------------------------------------------------------------------

    def center_on(self, t: float) -> bool:
        """Centre the window on time *t*, keeping the window width."""
        half = 0.5 * self._state.width()
        return self._apply(t - half, t + half)
