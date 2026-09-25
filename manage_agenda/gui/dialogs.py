"""One dialog per prompt kind of the UI port, built from a UIRequest by build().

Each dialog's value() is what the port method returns; a rejected dialog (Cancel, or the
window closed) cancels the request, which raises UserCancelled in the worker.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from manage_agenda.gui.bridge import UIRequest
from manage_agenda.gui.review_form import (  # noqa: F401 - to_/from_local_text re-exported
    EventReviewForm,
    from_local_text,
    to_local_text,
)
from manage_agenda.gui.widgets import hint_label, primary, select_all_none_row
from manage_agenda.i18n import t
from manage_agenda.ui import describe_nature, describe_source, label_for


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
        layout.addLayout(select_all_none_row(self.list, self))
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
        layout.addLayout(select_all_none_row(self.list, self))
        layout.addWidget(self._button_box())

    def value(self):
        return [self.events[row] for row in self.list.checked_rows()]


class ReviewEventDialog(PromptDialog):
    """The GUI's version of the s/r/y/m/d/h/i/f date menu: the EventReviewForm, Accept or
    Retry (ask the LLM again). The fields are reachable on the dialog itself (summary,
    start, end, error...), as the main window and the tests use them."""

    def __init__(self, request, parent=None):
        super().__init__(request, parent)
        payload = request.payload
        self._decision = "accept"
        self.setWindowTitle(f"{payload.get('label', '')}{t('events.review_title')}")
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)
        for line in (
            describe_source(payload.get("context")),
            describe_nature(payload.get("context")),
        ):
            if line:
                layout.addWidget(hint_label(line, self))
        self.form = EventReviewForm(self)
        self.form.load(payload["event"])
        layout.addWidget(self.form)
        self.summary, self.location, self.description = (
            self.form.summary,
            self.form.location,
            self.form.description,
        )
        self.start, self.end, self.error = self.form.start, self.form.end, self.form.error

        row = QHBoxLayout()
        self.retry = QPushButton(t("events.review_retry"), self)
        self.accept_button = primary(QPushButton(t("events.review_accept"), self))
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

    @property
    def event_data(self):
        return self.form.event_data

    def _retry(self):
        self._decision = "retry"
        self.accept()

    def _accept_edits(self):
        if not self.form.validate():
            return
        self._decision = "accept"
        self.accept()

    def apply_edits(self):
        """Write the form back into the event; ValueError on a malformed time."""
        return self.form.apply_edits()

    def value(self):
        return self.form.event_data, self._decision


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
