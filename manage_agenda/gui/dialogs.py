"""One dialog per prompt kind of the UI port, built from a UIRequest by build().

Each dialog's value() is what the port method returns; a rejected dialog (Cancel, or the
window closed) cancels the request, which raises UserCancelled in the worker.
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from manage_agenda.events import DATETIME_FORMAT
from manage_agenda.gui.bridge import UIRequest
from manage_agenda.i18n import t
from manage_agenda.ui import label_for


class PromptDialog(QDialog):
    """Base: a modal dialog answering one UIRequest through value()."""

    def __init__(self, request: UIRequest, parent=None):
        super().__init__(parent)
        self.request = request
        self.setModal(True)
        self.setMinimumWidth(420)

    def value(self):
        raise NotImplementedError

    def _button_box(self, ok_text=None):
        box = QDialogButtonBox(self)
        ok = box.addButton(ok_text or t("gui.dialog.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("gui.dialog.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        ok.setDefault(True)
        return box


class ChooseOneDialog(PromptDialog):
    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        payload = request.payload
        self.options = list(payload["options"])
        identifier = payload.get("identifier")
        labels = [label_for(item, identifier) for item in self.options]
        self.setWindowTitle(payload.get("title") or t("gui.dialog.choose_one_title"))

        layout = QVBoxLayout(self)
        if payload.get("title"):
            layout.addWidget(QLabel(payload["title"]))
        self.list = QListWidget(self)
        for label in labels:
            self.list.addItem(label)
        default = payload.get("default")
        self.list.setCurrentRow(labels.index(default) if default in labels else 0)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list)
        layout.addWidget(self._button_box())

    def value(self):
        row = self.list.currentRow()
        return self.options[row] if 0 <= row < len(self.options) else None


class _CheckableList(QListWidget):
    """A list of checkable rows with helpers to check all / none."""

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        for label in labels:
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.addItem(item)

    def set_all(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.count()):
            self.item(row).setCheckState(state)

    def set_checked(self, row, checked=True):
        self.item(row).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def checked_rows(self):
        return [
            row for row in range(self.count())
            if self.item(row).checkState() == Qt.CheckState.Checked
        ]


def _select_all_none_row(target, parent):
    row = QHBoxLayout()
    select_all = QPushButton(t("gui.dialog.select_all"), parent)
    select_none = QPushButton(t("gui.dialog.select_none"), parent)
    select_all.clicked.connect(lambda: target.set_all(True))
    select_none.clicked.connect(lambda: target.set_all(False))
    row.addWidget(select_all)
    row.addWidget(select_none)
    row.addStretch(1)
    return row


class ChooseManyDialog(PromptDialog):
    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        payload = request.payload
        self.options = list(payload["options"])
        labels = [label_for(item, payload.get("identifier")) for item in self.options]
        self.setWindowTitle(payload.get("title") or t("gui.dialog.choose_many_title"))

        layout = QVBoxLayout(self)
        if payload.get("title"):
            layout.addWidget(QLabel(payload["title"]))
        self.list = _CheckableList(labels, self)
        layout.addWidget(self.list)
        layout.addLayout(_select_all_none_row(self.list, self))
        layout.addWidget(self._button_box())

    def value(self):
        return [self.options[row] for row in self.list.checked_rows()]


class ConfirmDialog(PromptDialog):
    """Yes and No are both answers; only closing the window cancels."""

    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        self.setWindowTitle(t("gui.dialog.confirm_title"))
        self._answer = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(request.payload["text"]))
        row = QHBoxLayout()
        self.yes = QPushButton(t("gui.dialog.yes"), self)
        self.no = QPushButton(t("gui.dialog.no"), self)
        self.yes.clicked.connect(lambda: self._decide(True))
        self.no.clicked.connect(lambda: self._decide(False))
        (self.yes if request.payload.get("default") else self.no).setDefault(True)
        row.addStretch(1)
        row.addWidget(self.no)
        row.addWidget(self.yes)
        layout.addLayout(row)

    def _decide(self, answer):
        self._answer = answer
        self.accept()

    def value(self):
        return bool(self._answer)


class AskTextDialog(PromptDialog):
    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        self.setWindowTitle(t("gui.dialog.ask_text_title"))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(request.payload["text"]))
        self.edit = QLineEdit(request.payload.get("default") or "", self)
        layout.addWidget(self.edit)
        layout.addWidget(self._button_box())
        self.edit.returnPressed.connect(self.accept)

    def value(self):
        return self.edit.text()


class AskMultilineDialog(PromptDialog):
    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        self.setWindowTitle(t("gui.dialog.ask_multiline_title"))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(request.payload["text"]))
        self.edit = QPlainTextEdit(self)
        layout.addWidget(self.edit)
        layout.addWidget(QLabel(t("gui.dialog.ask_multiline_hint")))
        layout.addWidget(self._button_box())

    def value(self):
        return self.edit.toPlainText()


class ChooseActionDialog(PromptDialog):
    """One button per action; the chosen action's key is the answer."""

    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        self.setWindowTitle(t("gui.dialog.action_title"))
        self._key = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(request.payload["prompt_text"]))
        self.buttons = {}
        for key, label in request.payload["actions"]:
            button = QPushButton(label, self)
            button.clicked.connect(lambda _checked=False, key=key: self._choose(key))
            self.buttons[key] = button
            layout.addWidget(button)
        cancel = QPushButton(t("gui.dialog.cancel"), self)
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def _choose(self, key):
        self._key = key
        self.accept()

    def value(self):
        return self._key


class SelectEventsDialog(PromptDialog):
    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        payload = request.payload
        self.events = list(payload["events"])
        self.setWindowTitle(payload.get("title") or t("gui.dialog.select_events_title"))
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        if payload.get("title"):
            layout.addWidget(QLabel(payload["title"]))
        self.list = _CheckableList(list(payload["labels"]), self)
        layout.addWidget(self.list)
        layout.addLayout(_select_all_none_row(self.list, self))
        layout.addWidget(self._button_box())

    def value(self):
        return [self.events[row] for row in self.list.checked_rows()]


def to_local_text(iso_value):
    """An event dateTime (ISO 8601, usually UTC) shown as local time in DATETIME_FORMAT."""
    if not iso_value:
        return ""
    try:
        parsed = datetime.datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
    except ValueError:
        return str(iso_value)
    if parsed.tzinfo is None:
        return parsed.strftime(DATETIME_FORMAT)
    return parsed.astimezone().strftime(DATETIME_FORMAT)


def from_local_text(text):
    """A DATETIME_FORMAT local time as an aware UTC ISO string; ValueError when malformed."""
    naive = datetime.datetime.strptime(text.strip(), DATETIME_FORMAT)
    return naive.astimezone().astimezone(datetime.timezone.utc).isoformat()


class ReviewEventDialog(PromptDialog):
    """The GUI's version of the s/r/y/m/d/h/i/f date menu: an editable form, Accept or
    Retry (ask the LLM again). Times are shown and edited in local time; an edited time is
    written back as UTC, the form adjust_event_times() produces, so the rest of the flow
    sees exactly what it would after a terminal edit."""

    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        payload = request.payload
        self.event_data = payload["event"]
        self._decision = "accept"
        self.setWindowTitle(f"{payload.get('label', '')}{t('events.review_title')}")
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.summary = QLineEdit(self.event_data.get("summary") or "", self)
        self.location = QLineEdit(self.event_data.get("location") or "", self)
        self.description = QPlainTextEdit(self)
        self.description.setPlainText(self.event_data.get("description") or "")
        self._start_initial = to_local_text((self.event_data.get("start") or {}).get("dateTime"))
        self._end_initial = to_local_text((self.event_data.get("end") or {}).get("dateTime"))
        self.start = QLineEdit(self._start_initial, self)
        self.end = QLineEdit(self._end_initial, self)
        form.addRow(t("events.review_summary"), self.summary)
        form.addRow(t("events.review_location"), self.location)
        form.addRow(t("events.review_start"), self.start)
        form.addRow(t("events.review_end"), self.end)
        form.addRow("", QLabel(t("events.review_datetime_hint", format=DATETIME_FORMAT)))
        form.addRow(t("events.review_description"), self.description)
        layout.addLayout(form)
        self.error = QLabel("", self)
        self.error.setStyleSheet("color: #b00020;")
        layout.addWidget(self.error)

        row = QHBoxLayout()
        self.retry = QPushButton(t("events.review_retry"), self)
        self.accept_button = QPushButton(t("events.review_accept"), self)
        cancel = QPushButton(t("gui.dialog.cancel"), self)
        self.retry.clicked.connect(self._retry)
        self.accept_button.clicked.connect(self._accept_edits)
        cancel.clicked.connect(self.reject)
        self.accept_button.setDefault(True)
        row.addWidget(cancel)
        row.addStretch(1)
        row.addWidget(self.retry)
        row.addWidget(self.accept_button)
        layout.addLayout(row)

    def _retry(self):
        self._decision = "retry"
        self.accept()

    def _accept_edits(self):
        try:
            self.apply_edits()
        except ValueError:
            self.error.setText(t("events.review_invalid_datetime", format=DATETIME_FORMAT))
            return
        self._decision = "accept"
        self.accept()

    def apply_edits(self):
        """Write the form back into the event; ValueError on a malformed time."""
        times = {}
        for when, edit, initial in (
            ("start", self.start, self._start_initial),
            ("end", self.end, self._end_initial),
        ):
            text = edit.text().strip()
            if text != initial.strip():
                times[when] = from_local_text(text) if text else None
        for when, value in times.items():
            field = self.event_data.setdefault(when, {})
            if value is None:
                field.pop("dateTime", None)
            else:
                field["dateTime"] = value
                field["timeZone"] = "UTC"
        for key, edit in (("summary", self.summary), ("location", self.location)):
            if edit.text() != (self.event_data.get(key) or ""):
                self.event_data[key] = edit.text()
        if self.description.toPlainText() != (self.event_data.get("description") or ""):
            self.event_data["description"] = self.description.toPlainText()

    def value(self):
        return self.event_data, self._decision


DIALOGS = {
    "choose_one": ChooseOneDialog,
    "choose_many": ChooseManyDialog,
    "choose_action": ChooseActionDialog,
    "confirm": ConfirmDialog,
    "ask_text": AskTextDialog,
    "ask_multiline": AskMultilineDialog,
    "review_event": ReviewEventDialog,
    "select_events": SelectEventsDialog,
}


def build(request: UIRequest, parent=None) -> PromptDialog:
    """The dialog answering `request`."""
    return DIALOGS[request.kind](request, parent)
