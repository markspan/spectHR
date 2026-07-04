# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Background session loading for the main window.

Extracted from ``MainWindow`` so the window no longer owns the QThread dance:

* :class:`LoadWorker` - the ``QObject`` that parses a file (and runs the
  raw-file preprocessing pipeline) on a worker thread.
* :class:`SessionLoader` - owns the ``LoadWorker`` + ``QThread`` lifecycle,
  re-emits ``loaded`` / ``failed`` on the GUI thread, and cleans up the thread
  afterwards.  Callers decide *which* path to load (raw vs cache); this class
  just runs it off the event loop.
* :func:`session_summary` - a human-readable multi-line summary for the log.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from spectHR.dataset.loaders import load as _load_session
from spectHR.dataset.preprocessing import (
    apply_beat_detection,
    apply_bp_calibration,
    apply_breath_phases,
    apply_canonical_channels,
    apply_ecg_polarity,
    apply_rsp_source,
)
from spectHR.logger import logger
from spectHR.session import Session


class LoadWorker(QObject):
    """Loads a recording file on a worker thread.

    Emits ``finished`` with the ready ``Session`` on success, or ``failed``
    with a human-readable error string on failure.  The owner is responsible
    for moving this object to a ``QThread`` before calling ``run()`` (see
    :class:`SessionLoader`).
    """

    finished = Signal(object, float)   # (Session, elapsed_seconds)
    failed   = Signal(str,   str)      # (path_str, error_message)

    def __init__(self, path: Path, params) -> None:
        super().__init__()
        self._path   = path
        self._params = params

    def run(self) -> None:
        t0 = time.monotonic()
        try:
            session = _load_session(self._path)
            # A cached ``.pkl`` is an already-processed Session (it may carry
            # the user's R-peak edits), re-running the pipeline would, e.g.,
            # flip an already-corrected ECG a second time, and recomputing
            # breath phases on every cache load would defeat the cache.  Only
            # raw files get the conditioning pipeline; the ``.pkl`` is trusted
            # to already hold the derived data (breath phases included).
            if self._path.suffix.lower() != ".pkl":
                session = apply_canonical_channels(session)            # alias keys first
                session = apply_ecg_polarity(session,   self._params)  # before detection
                session = apply_rsp_source(session,     self._params)
                session = apply_bp_calibration(session, self._params)
                session = apply_beat_detection(session, self._params)
                session = apply_breath_phases(session,  self._params)  # needs beats
            self.finished.emit(session, time.monotonic() - t0)
        except Exception as exc:   # noqa: BLE001, surfaced to the UI, never crash the thread
            self.failed.emit(str(self._path), str(exc))


class SessionLoader(QObject):
    """Owns the load worker + thread lifecycle for one main window.

    Re-emits :attr:`loaded` / :attr:`failed` from the worker; the caller wires
    those to its own handlers.  Only one load runs at a time; :meth:`is_running`
    lets the caller drop a request that arrives mid-load.
    """

    loaded = Signal(object, float)   # (Session, elapsed_seconds)
    failed = Signal(str,   str)      # (path_str, error_message)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: LoadWorker | None = None

    def is_running(self) -> bool:
        """True while a load is in flight."""
        return self._thread is not None and self._thread.isRunning()

    def start(self, path: Path, params) -> None:
        """Load *path* on a worker thread, applying the pipeline for raw files.

        Emits :attr:`loaded` / :attr:`failed` when done.  Does nothing if a
        load is already running (guard with :meth:`is_running` to decide).
        """
        self._worker = LoadWorker(path, params)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.loaded)
        self._worker.failed.connect(self.failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)

        self._thread.start()

    def _on_thread_finished(self) -> None:
        """Release the finished loader thread.

        ``deleteLater`` destroys the underlying C++ QThread, so the Python
        references must be dropped here as well, otherwise the next
        :meth:`start` call would touch a dead wrapper and raise
        ``RuntimeError: Internal C++ object already deleted``.
        """
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None


def session_summary(session: Session) -> str:
    """Return a multi-line human-readable summary of *session* for the log."""
    lines: list[str] = []

    # Duration, prefer the experiment epoch, fall back to sample axes
    exp   = session.epochs.get("experiment")
    dur_s = (exp.end - exp.start) if exp else max(
        (s.times[-1] for s in session.samples.values() if len(s.times)),
        default=0.0,
    )
    h, rem  = divmod(int(dur_s), 3600)
    m, s    = divmod(rem, 60)
    dur_str = (f"{h} h {m:02d} min" if h else
               f"{m} min {s:02d} s"  if m else
               f"{s} s")
    lines.append(f"  Duration : {int(dur_s):,} s  ({dur_str})")

    # Sample channels with sampling rate
    if session.samples:
        ch_parts = []
        for name, sig in sorted(session.samples.items()):
            rate = getattr(sig, "srate", None)
            ch_parts.append(f"{name} ({rate:.0f} Hz)" if rate else name)
        lines.append(f"  Samples  : {', '.join(ch_parts)}")

    # R-peaks / mean HR
    hrv = session.hrv
    if hrv is not None and len(hrv.times):
        ibi  = hrv.ibi
        fin  = ibi[np.isfinite(ibi)]
        hr   = f"  |  mean HR {60.0 / fin.mean():.1f} bpm" if len(fin) else ""
        lines.append(f"  R-peaks  : {len(hrv.times):,}{hr}")

    # Epochs
    if session.epochs:
        names = ", ".join(session.epochs)
        lines.append(f"  Epochs   : {names}  ({len(session.epochs)} total)")

    return "\n".join(lines)
