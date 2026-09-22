"""The log panel: what the core echoes and logs while a job runs."""

from __future__ import annotations

import logging

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QPlainTextEdit

from manage_agenda.gui.bridge import Bridge

MAX_LINES = 5000


class LogPanel(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(MAX_LINES)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    @Slot(str)
    def append_line(self, text):
        self.appendPlainText(text)

    @Slot(str, int)
    def append_record(self, text, levelno):
        prefix = "! " if levelno >= logging.WARNING else "  "
        self.appendPlainText(prefix + text)

    def lines(self):
        """Every line shown, for tests."""
        return self.toPlainText().splitlines()


class QtLogHandler(logging.Handler):
    """A logging handler that forwards records to the panel through the bridge - it only
    emits a signal, so it is safe on the worker thread. Deliberately without the
    `manage_agenda_handler` mark base.setup_logging() uses to find and replace its own
    handlers: this one must survive a later setup_logging() call."""

    def __init__(self, bridge: Bridge, level=logging.INFO):
        super().__init__(level)
        self.bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            self.bridge.log_record.emit(self.format(record), record.levelno)
        except Exception:  # pragma: no cover - logging must never raise into the flow
            self.handleError(record)
