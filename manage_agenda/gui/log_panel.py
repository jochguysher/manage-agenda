"""The log: the full panel (a dock, for the details) and the summary under the sidebar."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from manage_agenda.gui.bridge import Bridge
from manage_agenda.gui.widgets import AutoNamed
from manage_agenda.i18n import t

MAX_LINES = 5000


class LogPanel(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logPanel")
        self.setReadOnly(True)
        self.setMaximumBlockCount(MAX_LINES)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

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


class LogSummary(AutoNamed, QWidget):
    """The log at a glance, under the sidebar: one short line per echo or record - the
    fact itself, without timestamp or level, elided to the sidebar's width, the full text
    as tooltip - a mark for warnings and errors, and a Details… button for the full panel."""

    MAX_ENTRIES = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)
        header = QHBoxLayout()
        self.title = QLabel(t("gui.log_panel_title"), self)
        self.title.setProperty("role", "card_title")
        self.details_button = QPushButton(t("gui.log.details"), self)
        self.details_button.setFlat(True)
        self.details_button.setToolTip(t("gui.log.details_tip"))
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.details_button)
        layout.addLayout(header)
        self.list = QListWidget(self)
        self.list.setObjectName("logSummary")  # styled by gui/theme.py
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setWordWrap(False)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.list, 1)

    def name_prefix(self):
        return "log"

    @Slot(str)
    def append_line(self, text):
        self._add(text, "")

    @Slot(str, int)
    def append_record(self, text, levelno):
        # The panel's records read "HH:MM:SS LEVEL message": here the message alone.
        parts = text.split(" ", 2)
        message = parts[2] if len(parts) == 3 else text
        mark = "✖ " if levelno >= logging.ERROR else "⚠ " if levelno >= logging.WARNING else ""
        self._add(message, mark, tooltip=text)

    def _add(self, text, mark, tooltip=None):
        text = str(text)
        first = text.strip().splitlines()[0] if text.strip() else ""
        if not first:
            return
        item = QListWidgetItem(mark + first)
        item.setToolTip((tooltip or text).strip())  # the whole record, time and level included
        self.list.addItem(item)
        while self.list.count() > self.MAX_ENTRIES:
            self.list.takeItem(0)
        self.list.scrollToBottom()

    def lines(self):
        """Every line shown, for tests."""
        return [self.list.item(row).text() for row in range(self.list.count())]
