# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless-safe hook for resolving ambiguous CARSPAN epoch codes.

A CARSPAN ``.evt`` file with more than two distinct non-RTop event codes
is ambiguous: a human has to say which codes mark epoch starts and which
mark stops. That choice is a *UI* concern, so the loader must not import a
dialog — doing so would invert the dependency (``spectHR`` → ``spectUI``)
and break headless / batch use of the library.

Instead the loader asks whatever resolver has been registered here. The
UI registers its dialog-backed resolver once at start-up
(:func:`register_code_resolver`); headless callers leave it unset and the
loader falls back to a single full-recording epoch.
"""
from __future__ import annotations

from typing import Callable, Sequence

# resolver(other_codes, rtop_code) -> (start_codes, stop_codes)
# Empty lists mean "use the whole recording as a single epoch".
CodeResolver = Callable[[Sequence[int], int], "tuple[list[int], list[int]]"]

_resolver: CodeResolver | None = None


def register_code_resolver(resolver: CodeResolver | None) -> None:
    """Register the callable the ``.evt`` loader uses to resolve epoch codes.

    Passing ``None`` clears the hook, restoring headless single-epoch
    behaviour.
    """
    global _resolver
    _resolver = resolver


def resolve_epoch_codes(
    other_codes: Sequence[int], rtop_code: int
) -> "tuple[list[int], list[int]]":
    """Resolve start/stop codes via the registered resolver.

    Returns ``([], [])`` when no resolver is registered (headless), so the
    caller falls back to treating the whole recording as one epoch.
    """
    if _resolver is None:
        return [], []
    return _resolver(other_codes, rtop_code)
