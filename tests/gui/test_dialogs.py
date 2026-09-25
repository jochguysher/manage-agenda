"""Each prompt kind's dialog, driven programmatically: what value() returns for a given
set of widget states, and that Cancel cancels the request."""

import datetime

import pytest
from PySide6.QtWidgets import QDialog

from manage_agenda.events import _parse_event_times
from manage_agenda.gui import dialogs
from manage_agenda.gui.bridge import UIRequest
from manage_agenda.gui.dialogs import from_local_text, to_local_text


def _dialog(kind, **payload):
    request = UIRequest(kind, payload)
    return dialogs.build(request), request


def test_every_kind_has_a_dialog(qapp):
    kinds = {
        "choose_one": {"options": ["a"], "title": ""},
        "choose_many": {"options": ["a"], "title": ""},
        "choose_action": {"actions": [("r", "Retry")], "prompt_text": "?"},
        "confirm": {"text": "?"},
        "ask_text": {"text": "?"},
        "ask_multiline": {"text": "?"},
        "review_event": {"event": {}, "label": ""},
        "select_events": {"events": [1], "labels": ["one"], "title": ""},
    }
    for kind, payload in kinds.items():
        dialog, _request = _dialog(kind, **payload)
        assert isinstance(dialog, QDialog), kind


def test_choose_one_default_and_selection(qapp):
    options = [{"summary": "Personal", "id": "p"}, {"summary": "Work", "id": "w"}]
    dialog, _ = _dialog("choose_one", options=options, title="Cal", identifier="summary", default="Work")
    assert dialog.list.currentRow() == 1
    assert dialog.value() == options[1]
    dialog.list.setCurrentRow(0)
    assert dialog.value() == options[0]


def test_choose_one_shows_tuple_rule_keys_as_text(qapp):
    key = ("imap", "set", "me@host", "posts")
    dialog, _ = _dialog("choose_one", options=[key], title="")
    assert dialog.list.item(0).text() == str(key)
    assert dialog.value() == key


def test_choose_many_checked_rows_in_order(qapp):
    dialog, _ = _dialog("choose_many", options=["a", "b", "c"], title="")
    assert dialog.value() == []
    dialog.list.set_checked(2)
    dialog.list.set_checked(0)
    assert dialog.value() == ["a", "c"]
    dialog.list.set_all(True)
    assert dialog.value() == ["a", "b", "c"]
    dialog.list.set_all(False)
    assert dialog.value() == []


def test_confirm_yes_and_no_both_accept_the_dialog(qapp):
    dialog, request = _dialog("confirm", text="Remove?", default=False)
    dialog.yes.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.value() is True
    dialog, request = _dialog("confirm", text="Remove?", default=False)
    dialog.no.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.value() is False


def test_ask_text_prefilled_and_editable(qapp):
    dialog, _ = _dialog("ask_text", text="URLs", default="http://a")
    assert dialog.value() == "http://a"
    dialog.edit.setText(" http://b ")
    assert dialog.value() == " http://b "


def test_ask_multiline(qapp):
    dialog, _ = _dialog("ask_multiline", text="Paste")
    assert dialog.value() == ""
    dialog.edit.setPlainText("line 1\nline 2")
    assert dialog.value() == "line 1\nline 2"


def test_choose_action_returns_the_clicked_key(qapp):
    dialog, _ = _dialog(
        "choose_action", actions=[("r", "Retry"), ("p", "Snippet"), ("s", "Skip")], prompt_text="?"
    )
    dialog.buttons["p"].click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.value() == "p"


def test_select_events_returns_checked_events(qapp):
    events = [{"id": 1}, {"id": 2}, {"id": 3}]
    dialog, _ = _dialog("select_events", events=events, labels=["a", "b", "c"], title="Pick")
    dialog.list.set_checked(1)
    assert dialog.value() == [{"id": 2}]


def test_rejecting_cancels_the_request_when_the_window_answers(qapp):
    from manage_agenda.gui.main_window import MainWindow

    window = MainWindow()
    request = UIRequest("ask_text", {"text": "?", "default": ""})
    # Drive _on_ui_request with a dialog that rejects itself as soon as it is shown.
    original_build = dialogs.build

    def build_and_reject(req, parent=None):
        dialog = original_build(req, parent)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, dialog.reject)
        return dialog

    dialogs.build = build_and_reject
    try:
        window._on_ui_request(request)
    finally:
        dialogs.build = original_build
    assert request.cancelled and request.done.is_set()
    assert window._active_dialog is None


def test_accepting_answers_the_request_when_the_window_answers(qapp):
    from manage_agenda.gui.main_window import MainWindow

    window = MainWindow()
    request = UIRequest("ask_text", {"text": "?", "default": "typed"})
    original_build = dialogs.build

    def build_and_accept(req, parent=None):
        dialog = original_build(req, parent)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, dialog.accept)
        return dialog

    dialogs.build = build_and_accept
    try:
        window._on_ui_request(request)
    finally:
        dialogs.build = original_build
    assert request.result == "typed" and not request.cancelled


class TestLocalTime:
    def test_round_trip_keeps_the_instant(self):
        iso = "2024-01-15T09:00:00+00:00"
        text = to_local_text(iso)
        back = datetime.datetime.fromisoformat(from_local_text(text))
        assert back == datetime.datetime.fromisoformat(iso)

    def test_empty_and_unparseable_values(self):
        assert to_local_text(None) == ""
        assert to_local_text("") == ""
        assert to_local_text("not a date") == "not a date"
        with pytest.raises(ValueError):
            from_local_text("2024/01/15")


class TestReviewEventDialog:
    def _event(self):
        return {
            "summary": "Meeting",
            "location": "Room 1",
            "description": "Agenda\n\nMessage:\nsource text",
            "start": {"dateTime": "2024-01-15T09:00:00+00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2024-01-15T10:00:00+00:00", "timeZone": "UTC"},
        }

    def test_accept_without_edits_leaves_the_event_untouched(self, qapp):
        event = self._event()
        dialog, _ = _dialog("review_event", event=event, label="[m1] ")
        dialog.accept_button.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.value() == (self._event(), "accept")
        assert "[m1]" in dialog.windowTitle()

    def test_retry(self, qapp):
        dialog, _ = _dialog("review_event", event=self._event(), label="")
        dialog.retry.click()
        assert dialog.value()[1] == "retry"

    def test_edited_times_are_written_back_as_utc(self, qapp):
        event = self._event()
        dialog, _ = _dialog("review_event", event=event, label="")
        dialog.summary.setText("Renamed")
        dialog.start.setText("2030-06-01 10:00:00")
        dialog.end.setText("2030-06-01 10:45:00")
        dialog.accept_button.click()
        edited, decision = dialog.value()
        assert decision == "accept"
        assert edited["summary"] == "Renamed"
        assert edited["start"]["timeZone"] == "UTC" and edited["end"]["timeZone"] == "UTC"
        start, end = _parse_event_times(edited)
        assert end - start == datetime.timedelta(minutes=45)
        local_start = start.astimezone()
        assert (local_start.year, local_start.month, local_start.day, local_start.hour) == (2030, 6, 1, 10)

    def test_a_malformed_time_keeps_the_dialog_open(self, qapp):
        dialog, _ = _dialog("review_event", event=self._event(), label="")
        dialog.start.setText("tomorrow")
        dialog.accept_button.click()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert dialog.error.text()
        dialog.start.setText("2030-06-01 10:00:00")
        dialog.accept_button.click()
        assert dialog.result() == QDialog.DialogCode.Accepted


def test_review_dialog_names_the_source_message(qapp):
    from PySide6.QtWidgets import QLabel

    context = {"subject": "Visite", "sender": "a@b.org", "date": "2026-09-24 14:33", "identifier": "m1"}
    dialog, _ = _dialog("review_event", event={"summary": "x"}, label="[m1] ", context=context)
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("Visite" in text and "14:33" in text and "a@b.org" in text for text in texts)
    plain, _ = _dialog("review_event", event={"summary": "x"}, label="[m1] ", context={})
    assert not any("Visite" in label.text() for label in plain.findChildren(QLabel))


def test_review_dialog_says_what_a_planned_cleaning_is(qapp):
    from PySide6.QtWidgets import QLabel

    context = {"kind": "cleaning", "room": "Salle 1", "occupied_from": "2026-09-27", "occupied_to": "2026-10-03"}
    dialog, _ = _dialog("review_event", event={"summary": "NDU - Salle 1"}, label="", context=context)
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("Salle 1" in text and "2026-10-03" in text for text in texts)
