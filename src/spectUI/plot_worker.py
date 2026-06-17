# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Background-thread infrastructure for heavy plot-dock computation.

Qt rules applied here
---------------------
- QObject (and all Qt widgets / canvases) **must** be created on the main thread.
- Pure Python / numpy / scipy computation is thread-safe under the GIL.

The pattern for every heavy dock
---------------------------------
1. ``DockScheduler.submit()`` runs ``prefetch()`` on the global thread pool.
2. When done, ``_Signals.finished`` is emitted from the worker thread; Qt
   queues the delivery back to the main thread automatically (cross-thread
   signal / queued connection).
3. The ``on_done`` callback (main thread) creates the widget with
   ``_precomputed=<result>`` so no heavy work ever blocks the event loop.

Stale-result cancellation
-------------------------
Each ``submit()`` call increments a per-dock *generation* counter.
Workers carry a ``gen_check`` closure.  When a worker finishes, it only
emits its signal if the generation it started with still matches the
scheduler's current counter.  Calling ``submit()`` a second time (because
the user switched datasets or edited the workspace) bumps the counter, so
the first worker's result is silently discarded, no stale data reaches the
widget.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    """Cross-thread signal carrier owned by the main thread."""

    finished = Signal(object)
    failed   = Signal(object)


class PlotWorker(QRunnable):
    """Run *fn()* on a pool thread; deliver the result via *signals*."""

    def __init__(self, fn, signals: _Signals, gen_check) -> None:
        super().__init__()
        self._fn        = fn
        self._signals   = signals
        self._gen_check = gen_check
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            if self._gen_check():
                self._signals.failed.emit(exc)
            return
        if self._gen_check():
            self._signals.finished.emit(result)


class DockScheduler:
    """One-at-a-time background worker per dock with stale-result cancellation.

    Parameters
    ----------
    None.  Instantiate once inside ``MainWindow.__init__`` after
    ``QApplication`` exists so ``QThreadPool.globalInstance()`` is valid.

    Busy / idle hooks
    -----------------
    Register zero-argument callables with :meth:`on_busy` / :meth:`on_idle`.
    ``on_busy`` is called when ``_inflight`` transitions 0 → 1 (work starts);
    ``on_idle`` is called when it transitions N → 0 (all work done).
    Each call to ``on_busy`` will be paired with exactly one ``on_idle`` call,
    so they can safely wrap a Qt override-cursor push/pop.
    """

    def __init__(self) -> None:
        self._pool:        QThreadPool         = QThreadPool.globalInstance()
        self._gen:         dict[str, int]      = {}
        self._inflight:    set[_Signals]       = set()
        self._current_sig: dict[str, _Signals] = {}  # dock_name → live signal
        self._busy_cbs:    list                = []
        self._idle_cbs:    list                = []

    def on_busy(self, cb) -> None:
        """Register *cb* to be called when this scheduler becomes busy."""
        self._busy_cbs.append(cb)

    def on_idle(self, cb) -> None:
        """Register *cb* to be called when this scheduler becomes idle."""
        self._idle_cbs.append(cb)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        dock_name:  str,
        compute_fn,
        on_done,
        on_error=None,
    ) -> None:
        """Submit *compute_fn* to the thread pool for *dock_name*.

        Parameters
        ----------
        dock_name:  Stable dock object-name string (from the ``_DOCK_*``
                    constants in MainWindow) used to track generations.
        compute_fn: Zero-argument callable; returns the precomputed data.
                    Called on a pool thread, must NOT touch Qt objects.
        on_done:    ``callback(result)`` called on the **main thread** with
                    the value returned by *compute_fn*.
        on_error:   Optional ``callback(exc)`` called on the **main thread**
                    when *compute_fn* raises.
        """
        gen = self._gen.get(dock_name, 0) + 1
        self._gen[dock_name] = gen

        # Drop the previous signal for this dock from inflight, its worker
        # will finish with gen_check()=False and never emit, so the closure
        # references (layout, views, workspace) would otherwise leak forever.
        old = self._current_sig.pop(dock_name, None)
        if old is not None:
            self._inflight.discard(old)

        was_idle = not self._inflight
        sig = _Signals()
        self._inflight.add(sig)
        self._current_sig[dock_name] = sig
        if was_idle:
            for cb in self._busy_cbs:
                cb()

        def _done(result, _sig=sig):
            self._inflight.discard(_sig)
            if not self._inflight:
                for cb in self._idle_cbs:
                    cb()
            on_done(result)

        def _fail(exc, _sig=sig):
            self._inflight.discard(_sig)
            if not self._inflight:
                for cb in self._idle_cbs:
                    cb()
            if on_error:
                on_error(exc)

        sig.finished.connect(_done)
        sig.failed.connect(_fail)

        this_gen = gen
        self._pool.start(
            PlotWorker(
                compute_fn,
                sig,
                lambda: self._gen.get(dock_name) == this_gen,
            )
        )

    def invalidate(self, dock_name: str | None = None) -> None:
        """Mark in-flight results for *dock_name* (or all docks) as stale.

        Any worker currently running will still complete, but its
        ``gen_check`` will return ``False`` so the result is silently
        discarded rather than delivered to ``on_done``.

        Call this alongside every ``_plot_sig.clear()`` so a worker
        that started for a previous dataset cannot deliver into a new
        one if the dock hasn't been re-activated yet.
        """
        if dock_name is not None:
            if dock_name in self._gen:
                self._gen[dock_name] += 1
            old = self._current_sig.pop(dock_name, None)
            if old is not None:
                self._inflight.discard(old)
        else:
            self._gen = {k: v + 1 for k, v in self._gen.items()}
            self._inflight.clear()
            self._current_sig.clear()
