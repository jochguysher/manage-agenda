"""Calendar operations: copy, move, delete, clean and update-status, run exactly as the CLI
runs them (`-i`): the account, the calendars, the text filter and the events are asked
through dialogs unless given on the form."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
)

from manage_agenda.events import (
    clean_events_cli,
    copy_events_cli,
    delete_events_cli,
    move_events_cli,
    update_event_status_cli,
)
from manage_agenda.gui.screens.base import Screen
from manage_agenda.gui.widgets import form_layout, primary
from manage_agenda.i18n import t
from manage_agenda.sources import Args

OPERATIONS = (
    ("copy", copy_events_cli, True),
    ("move", move_events_cli, True),
    ("delete", delete_events_cli, False),
    ("clean", clean_events_cli, True),
    ("update-status", update_event_status_cli, False),
)


class CalendarOpsScreen(Screen):
    nav_key = "gui.nav.calendar_ops"
    subtitle_key = "gui.calendar_ops.subtitle"

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        layout = self.content
        form = form_layout()
        self.operation = QComboBox(self)
        for name, _func, _needs_destination in OPERATIONS:
            self.operation.addItem(name, name)
        self.source = QLineEdit(self)
        self.source.setPlaceholderText(t("gui.calendar_ops.ask_placeholder"))
        self.destination = QLineEdit(self)
        self.destination.setPlaceholderText(t("gui.calendar_ops.ask_placeholder"))
        self.text = QLineEdit(self)
        self.text.setPlaceholderText(t("gui.calendar_ops.ask_placeholder"))
        form.addRow(t("gui.calendar_ops.operation"), self.operation)
        form.addRow(t("gui.calendar_ops.source_calendar"), self.source)
        form.addRow(t("gui.calendar_ops.destination_calendar"), self.destination)
        form.addRow(t("gui.calendar_ops.text_filter"), self.text)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.run_button = self.register_run_button(primary(QPushButton(t("gui.calendar_ops.run"), self)))
        row.addWidget(self.run_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

        self.operation.currentIndexChanged.connect(self._on_operation_changed)
        self.run_button.setToolTip(t("gui.calendar_ops.note"))
        self.run_button.clicked.connect(self.run)
        for field in (self.source, self.destination, self.text):
            field.returnPressed.connect(self.run_button.click)  # Enter in a field runs
        self._on_operation_changed(0)

    def _entry(self):
        name = self.operation.currentData()
        for entry in OPERATIONS:
            if entry[0] == name:
                return entry
        return OPERATIONS[0]

    def _on_operation_changed(self, _index):
        self.destination.setEnabled(self._entry()[2])

    def build_args(self):
        """The Args `manage-agenda <operation> -i [-s] [-d] [-t]` would build."""
        _name, _func, needs_destination = self._entry()
        return Args(
            interactive=True,
            source=self.source.text().strip() or None,
            destination=(self.destination.text().strip() or None) if needs_destination else None,
            text=self.text.text().strip() or None,
        )

    def run(self):
        name, func, _needs_destination = self._entry()
        self.submit(t("gui.calendar_ops.job", operation=name), func, self.build_args())
