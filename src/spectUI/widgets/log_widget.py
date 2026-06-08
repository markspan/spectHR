# Copyright (C) 2025 Mark Span <m.m.span@rug.nl>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Docked log output widget.

:class:`LogWidget` is a self-contained QWidget that:

* Installs a Python :class:`logging.Handler` on the ``spectHR`` logger.
* Receives log records via a Qt signal so worker-thread records are
  delivered safely on the main thread (no ``invokeMethod`` gymnastics).
* Colour-codes records by level (DEBUG=grey, INFO=black, WARNING=orange,
  ERROR=red, CRITICAL=bold dark-red).
* Provides a level-filter combo and a clear button.

Usage — once, during ``MainWindow.__init__``::

    log_dock.setWidget(LogWidget())

``LogWidget`` wires itself to the ``spectHR`` logger on construction and
unwires on destruction, so no external bookkeeping is needed.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Level → display colour
# ---------------------------------------------------------------------------

_COLOURS: dict[int, str] = {
    logging.DEBUG:    "#888888",
    logging.INFO:     "#111111",
    logging.WARNING:  "#c07000",
    logging.ERROR:    "#cc0000",
    logging.CRITICAL: "#880000",
}


# ---------------------------------------------------------------------------
# Thread-safe logging bridge
# ---------------------------------------------------------------------------

class _Bridge(QObject):
    """QObject that owns the cross-thread signal.

    Lives on the main thread (created inside ``LogWidget.__init__``).
    Qt automatically queues signal deliveries when sender and receiver
    live on different threads, so worker-thread ``logging.Handler.emit``
    calls are marshalled to the main thread without any manual locking.
    """
    record = Signal(str, int)   # (formatted message, levelno)


class _Handler(logging.Handler):
    """Logging handler that forwards records to *bridge.record*."""

    def __init__(self, bridge: _Bridge) -> None:
        super().__init__(logging.DEBUG)
        self._bridge = bridge
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._bridge.record.emit(self.format(record), record.levelno)
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class LogWidget(QWidget):
    """Docked log output with colour coding and a level filter."""

    _LOGGER_NAME = "spectHR"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # --- text area ---
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(2_000)
        font = QFont("Courier New")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self._text.setFont(font)

        # --- controls ---
        self._level_box = QComboBox()
        for name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            self._level_box.addItem(name)
        self._level_box.setCurrentText("INFO")
        self._level_box.currentTextChanged.connect(self._on_level_changed)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self._text.clear)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Level:"))
        bar.addWidget(self._level_box)
        bar.addStretch()
        bar.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addLayout(bar)
        layout.addWidget(self._text)

        # --- logging bridge (created on main thread → signal is queued) ---
        self._bridge  = _Bridge(self)
        self._handler = _Handler(self._bridge)
        self._bridge.record.connect(self._append)

        root = logging.getLogger(self._LOGGER_NAME)
        root.addHandler(self._handler)

    def __del__(self) -> None:
        logging.getLogger(self._LOGGER_NAME).removeHandler(self._handler)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _append(self, message: str, levelno: int) -> None:
        colour = _COLOURS.get(levelno, "#111111")
        bold   = levelno >= logging.CRITICAL
        style  = f"color:{colour};" + ("font-weight:bold;" if bold else "")
        # HTML-escape the message to prevent tag injection from log content
        safe = (message
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
        self._text.appendHtml(f'<span style="{style}">{safe}</span>')

    def _on_level_changed(self, name: str) -> None:
        level = getattr(logging, name, logging.INFO)
        self._handler.setLevel(level)
        # Raise the logger's own level so records below the threshold
        # are dropped before reaching any handler.
        logging.getLogger(self._LOGGER_NAME).setLevel(level)
