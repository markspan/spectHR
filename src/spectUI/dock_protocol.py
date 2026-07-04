# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The dock contract the coordinator and main window rely on.

Every live data dock (one that takes a :class:`~spectHR.session.Session`) is
duck-typed by :class:`~spectUI.coordinator.DataCoordinator`: it must accept a
session, react to a parameter-only change, repaint, and report visibility.
Rather than leave that contract implicit, it is a ``typing.Protocol`` here, so
a non-conforming dock is a type error and, for the load-bearing methods, a
loud failure at registration instead of a silent one at runtime.

Two kinds of contract:

* **Core** (:class:`DataDock`, :class:`TimelineDock`), what every dock (and
  every timeline dock) *must* provide.  :meth:`DataCoordinator.register`
  enforces :class:`DataDock` at registration.
* **Capabilities** (:class:`EmitsEpochsChanged`, :class:`EmitsAnnotation`,
  :class:`EmitsPlotsExport`), *optional* cross-dock signals a dock may expose.
  The host wires them with ``isinstance`` checks against these protocols, so
  the capability names live in one place instead of scattered string literals.

All protocols are ``@runtime_checkable`` so the wiring can use ``isinstance``;
runtime checks verify only that the named members exist (not their signatures),
which is exactly what the host needs.  Signal members are annotated for type
checkers only, hence the ``TYPE_CHECKING`` import of ``SignalInstance``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from spectHR.session import Session

if TYPE_CHECKING:
    from PySide6.QtCore import SignalInstance


@runtime_checkable
class DataDock(Protocol):
    """Contract every live data dock must satisfy.

    ``config`` is the host's :class:`~spectUI.parameters.Parameters` (or
    ``None``); it is intentionally loose so the headless side stays unaware of
    the concrete settings class.
    """

    def set_session(self, session: Session, config: Any = ...) -> None: ...

    def apply_config(self, config: Any) -> None: ...

    def refresh(self) -> None: ...

    def isVisible(self) -> bool: ...


@runtime_checkable
class TimelineDock(DataDock, Protocol):
    """A :class:`DataDock` whose visible window is coupled across siblings."""

    viewChanged: SignalInstance

    def current_window(self) -> "tuple[float, float] | None": ...

    def apply_window(self, x_min: float, x_max: float) -> None: ...


# --------------------------------------------------------------------------- #
# Optional cross-dock capabilities                                            #
# --------------------------------------------------------------------------- #

@runtime_checkable
class EmitsEpochsChanged(Protocol):
    """Emits when an epoch's active state is toggled (Poincaré, epoch editor)."""

    epochsChanged: SignalInstance


@runtime_checkable
class EmitsAnnotation(Protocol):
    """Emits a beat time to jump to in the pre-processing editor."""

    annotationActivated: SignalInstance


@runtime_checkable
class EmitsPlotsExport(Protocol):
    """Emits a target directory so the host can export the open dock plots."""

    plotsExportRequested: SignalInstance
