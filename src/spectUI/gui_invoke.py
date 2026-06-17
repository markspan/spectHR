# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run a callable on the GUI thread from any worker thread.

Qt widgets may only be created and used on the thread that owns the
``QApplication``.  File loading, however, runs on a background
``QThread`` (see ``MainWindow._load_file``), and the CARSPAN ``.evt``
loader may need to pop up :class:`~spectUI.widgets.EventCodeWindow`
mid-load to ask the user which event codes mark epoch boundaries.

:func:`run_in_gui_thread` bridges that gap: called from a worker thread
it ships the callable to the GUI thread via a ``BlockingQueuedConnection``
signal, blocks the worker until the callable (and any dialog event loop
inside it) returns, and hands the result back.  Called from the GUI
thread itself, or before a ``QApplication`` exists, it simply invokes
the callable directly, so headless/test use keeps working.
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal, Slot, QThread

T = TypeVar("T")


class _GuiInvoker(QObject):
    """Private QObject whose slot executes submitted jobs on its own thread.

    The instance is created at import time, which happens on the main
    thread during application start-up, so the slot always runs on the
    GUI thread.  The ``BlockingQueuedConnection`` makes the emitting
    (worker) thread wait until the slot has finished.
    """

    invoke = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.invoke.connect(self._run, Qt.BlockingQueuedConnection)

    @Slot(object)
    def _run(self, job: Callable[[], None]) -> None:
        job()


_invoker = _GuiInvoker()


def run_in_gui_thread(fn: Callable[[], T]) -> T:
    """Execute ``fn`` on the GUI thread and return its result.

    Blocks the calling worker thread until ``fn`` returns.  Exceptions
    raised inside ``fn`` are re-raised in the caller.  When already on
    the GUI thread (or when no ``QApplication`` is running) ``fn`` is
    called directly, which also makes this safe for headless scripts
    and unit tests.
    """
    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() is _invoker.thread():
        return fn()

    result: list[Any] = []
    error:  list[BaseException] = []

    def job() -> None:
        try:
            result.append(fn())
        except BaseException as exc:  # noqa: BLE001, re-raised in caller
            error.append(exc)

    _invoker.invoke.emit(job)
    if error:
        raise error[0]
    return result[0]
