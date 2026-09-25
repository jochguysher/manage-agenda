"""EventReviewForm: the editable view of an extracted event - title, location, start and end
(local time), description - shared by the review dialog (dialogs.ReviewEventDialog, what the
Add screen's run opens) and the home screen's inline proposal.

Times are shown and edited in local time; an edited time is written back as UTC, the form
adjust_event_times() produces, so the rest of the flow sees exactly what it would after a
terminal edit (the s/r/y/m/d/h/i/f menu of manage_agenda.ui.console).
"""

from __future__ import annotations

import datetime

from PySide6.QtWidgets import QLabel, QLineEdit, QPlainTextEdit, QWidget

from manage_agenda.events import DATETIME_FORMAT
from manage_agenda.gui.widgets import form_layout, set_role
from manage_agenda.i18n import t

DESCRIPTION_HEIGHT = 110


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


class EventReviewForm(QWidget):
    """The fields of one event. load() shows an event dict (kept by reference: apply_edits()
    writes the edits back into that same dict, which is what the worker gets)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.event_data = {}
        self._start_initial = ""
        self._end_initial = ""
        form = form_layout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.summary = QLineEdit(self)
        self.location = QLineEdit(self)
        self.start = QLineEdit(self)
        self.end = QLineEdit(self)
        self.description = QPlainTextEdit(self)
        self.description.setMaximumHeight(DESCRIPTION_HEIGHT)
        hint = QLabel(t("events.review_datetime_hint", format=DATETIME_FORMAT), self)
        set_role(hint, "hint")
        self.error = QLabel("", self)
        set_role(self.error, "error")
        form.addRow(t("events.review_summary"), self.summary)
        form.addRow(t("events.review_location"), self.location)
        form.addRow(t("events.review_start"), self.start)
        form.addRow(t("events.review_end"), self.end)
        form.addRow("", hint)
        form.addRow(t("events.review_description"), self.description)
        form.addRow("", self.error)

    def load(self, event_data):
        self.event_data = event_data
        self.summary.setText(event_data.get("summary") or "")
        self.location.setText(event_data.get("location") or "")
        self.description.setPlainText(event_data.get("description") or "")
        self._start_initial = to_local_text((event_data.get("start") or {}).get("dateTime"))
        self._end_initial = to_local_text((event_data.get("end") or {}).get("dateTime"))
        self.start.setText(self._start_initial)
        self.end.setText(self._end_initial)
        self.error.setText("")

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
        return self.event_data

    def validate(self):
        """apply_edits(), showing the error instead of raising; whether it succeeded."""
        try:
            self.apply_edits()
        except ValueError:
            self.error.setText(t("events.review_invalid_datetime", format=DATETIME_FORMAT))
            return False
        self.error.setText("")
        return True
