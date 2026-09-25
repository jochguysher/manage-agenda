"""The home screen: the run it submits, the inline proposal a review_event request becomes
(routed by the main window), and the calendar table with the tool's events marked."""

import threading
from unittest.mock import MagicMock, patch

from manage_agenda.gui.bridge import Bridge
from manage_agenda.gui.jobs import JobRunner
from manage_agenda.gui.main_window import MainWindow
from manage_agenda.gui.persist import gui_settings
from manage_agenda.gui.screens import home
from manage_agenda.gui.screens.home import HomeScreen, ledger_stats, tool_created
from manage_agenda.gui.screens.settings import SettingsScreen
from manage_agenda.sources import remember_handled_mail
from manage_agenda.ui import get_ui
from manage_agenda.user_config import save_user_config

MAIL = ("gmail", "set", "me@x", "posts")
IMAP = ("imap", "set", "review", "posts")
CAL = ("gcalendar", "set", "me@x", "posts")


def _rules():
    rules = MagicMock()
    rules.selectRule.side_effect = lambda name, _sel="": {
        "gmail": [MAIL],
        "imap": [IMAP],
        "gcalendar": [CAL],
    }.get(name, [])
    rules.more = {}
    return rules


def _home(qapp, runner=None):
    runner = runner or JobRunner(Bridge())
    screen = HomeScreen(runner)
    with patch.object(home, "load_rules", return_value=_rules()):
        screen.refresh()
    return runner, screen


def test_home_shows_the_saved_destination_and_remembers_its_choices(qapp):
    save_user_config({"calendar_account": list(CAL), "calendar": ["c1"], "provider": "ollama", "model": "m"})
    _runner, screen = _home(qapp)
    assert screen.source.keys == [MAIL, IMAP]
    assert "c1" in screen.destination.text() and "ollama / m" in screen.destination.text()
    assert screen.review_mode.isChecked()
    assert screen.build_args().interactive is True

    screen.source.setCurrentIndex(1)
    screen.auto_mode.setChecked(True)
    assert screen.build_args().interactive is False
    assert gui_settings().value("home/source") == str(IMAP)

    _runner, again = _home(qapp)
    assert again.source.current_key() == IMAP and again.auto_mode.isChecked()


def test_home_without_saved_calendar_says_so_and_does_not_connect(qapp):
    _runner, screen = _home(qapp)
    assert screen.destination.text()
    with patch.object(home, "fetch_planned") as fetch:
        screen.refresh_planned()
    fetch.assert_not_called()
    assert screen.planned_message.text()


def test_run_submits_add_with_the_mailbox_and_the_mode(qapp, pump):
    runner, screen = _home(qapp)
    with patch.object(home, "add_events_cli") as add_cli:
        screen.run()
        assert screen.running_from_home
        assert pump(lambda: not runner.is_busy())
    args, rules, selected = add_cli.call_args.args
    assert args.interactive is True and selected == MAIL and rules is screen.rules
    assert pump(lambda: not screen.running_from_home)
    assert screen.message.text()


def test_run_without_a_mailbox_does_not_submit(qapp):
    runner = JobRunner(Bridge())
    screen = HomeScreen(runner)
    screen.run()
    assert not runner.is_busy() and screen.message.text()


def _review_job(event, answers):
    def job():
        answers.append(get_ui().review_event(event, label="[msg-1] "))
        return 0

    return job


def test_a_review_from_a_home_run_is_answered_inline(qapp, pump):
    window = MainWindow()
    screen = window.screen(HomeScreen)
    with patch.object(home, "load_rules", return_value=_rules()):
        screen.refresh()
    screen.running_from_home = True
    event = {"summary": "Visit", "start": {"dateTime": "2030-06-01T10:00:00Z"}, "end": {"dateTime": "2030-06-01T11:00:00Z"}}
    answers = []
    assert window.runner.submit("review", _review_job(event, answers))
    assert pump(lambda: not screen.review_box.isHidden())
    assert window.stack.currentIndex() == window.screens.index(screen)
    assert "msg-1" in screen.review_label.text()
    assert screen.review_form.summary.text() == "Visit"

    screen.review_form.summary.setText("Visit (edited)")
    screen.accept_button.click()
    assert pump(lambda: not window.runner.is_busy())
    assert answers == [(event, "accept")] and event["summary"] == "Visit (edited)"
    assert screen.review_box.isHidden() and screen.review_request is None
    window.close()


def test_a_review_from_elsewhere_still_gets_the_dialog(qapp, pump):
    window = MainWindow()
    screen = window.screen(HomeScreen)
    event = {"summary": "Visit"}
    answers = []
    with patch.object(window, "_on_ui_request") as slot:
        assert window.runner.submit("review", _review_job(event, answers))
        assert pump(lambda: slot.called)
        request = slot.call_args.args[0]
        assert not screen.accepts_review()
        request.answer((event, "retry"))
        assert pump(lambda: not window.runner.is_busy())
    assert answers == [(event, "retry")]
    window.close()


def test_stopping_the_scan_cancels_the_pending_proposal(qapp, pump):
    window = MainWindow()
    screen = window.screen(HomeScreen)
    screen.running_from_home = True
    answers = []
    assert window.runner.submit("review", _review_job({"summary": "x"}, answers))
    assert pump(lambda: not screen.review_box.isHidden())
    screen.stop_button.click()
    assert pump(lambda: not window.runner.is_busy())
    assert answers == [] and screen.review_box.isHidden()
    assert not screen.accepts_review()
    window.close()


def test_a_failed_run_is_over_too_and_a_later_job_is_not_taken_for_it(qapp, pump):
    runner, screen = _home(qapp)

    def boom():
        raise RuntimeError("no mailbox")

    with patch.object(home, "add_events_cli", boom):
        screen.run()
        assert pump(lambda: not runner.is_busy())
    assert not screen.accepts_review() and screen.message.text() == ""

    save_user_config({"calendar_account": list(CAL), "calendar": ["c1"]})
    screen.refresh()
    with patch.object(home, "fetch_planned", side_effect=home.CalendarError("no token")):
        screen.refresh_planned()
        assert pump(lambda: not runner.is_busy())
    assert screen.message.text() == ""
    assert screen.planned_message.text() == "no token" and screen.table.rowCount() == 0


def test_planned_table_marks_the_tool_events(qapp, pump):
    save_user_config({"calendar_account": list(CAL), "calendar": ["c1"]})
    remember_handled_mail("m1", events=[{"calendar_id": "c1", "event_id": "e2"}])
    runner, screen = _home(qapp)
    assert "1" in screen.ledger_summary.text()
    rows = [
        {"id": "e1", "sort": "2030-01-01", "when": "2030-01-01", "summary": "Other", "calendar": "Cal", "link": "", "tool": False},
        {"id": "e2", "sort": "2030-01-02", "when": "2030-01-02", "summary": "Ours", "calendar": "Cal", "link": "http://x", "tool": True},
    ]
    with patch.object(home, "fetch_planned", return_value=rows) as fetch:
        screen.refresh_planned()
        assert pump(lambda: not runner.is_busy())
    _rules_arg, account, calendar_ids = fetch.call_args.args[0:3]
    assert account == CAL and calendar_ids == ["c1"]
    assert screen.table.rowCount() == 2
    assert screen.table.item(0, 3).text() == ""
    assert screen.table.item(1, 3).text() and screen.table.item(1, 1).text() == "Ours"


def test_fetch_planned_reads_every_saved_calendar(qapp):
    # The api has only what socialModules' moduleGcalendar offers: the calendar to list is
    # the "active" one (setActive), there is no setCalendar.
    api = MagicMock(spec=["getClient", "setActive", "setPosts", "getPosts", "setCalendarList", "getCalendarList"])
    api.getClient.return_value = object()
    rules = MagicMock()
    rules.readConfigSrc.return_value = api
    rules.more = {}
    events = {
        "c1": [{"id": "a", "summary": "A", "start": {"date": "2030-01-02"}, "htmlLink": "http://a"}],
        "c2": [
            {
                "id": "b",
                "summary": "B",
                "start": {"dateTime": "2030-01-01T10:00:00Z"},
                "extendedProperties": {"private": {"ai_model_used": "m"}},
            }
        ],
    }
    api.getPosts.side_effect = lambda: events[api.setActive.call_args.args[0]]
    with patch.object(home, "_eligible_calendars", return_value=[{"id": "c1", "summary": "One"}]):
        rows = home.fetch_planned(rules, CAL, ["c1", "c2"])
    assert [call.args[0] for call in api.setActive.call_args_list] == ["c1", "c2"]
    assert api.setPosts.call_count == 2
    assert [row["id"] for row in rows] == ["b", "a"]
    assert rows[0]["tool"] and rows[0]["calendar"] == "c2"
    assert not rows[1]["tool"] and rows[1]["calendar"] == "One" and rows[1]["link"] == "http://a"
    assert tool_created({}) is False
    assert ledger_stats()[0] == 0


def test_home_buttons_open_the_other_screens(qapp):
    window = MainWindow()
    screen = window.screen(HomeScreen)
    screen.settings_button.click()
    assert isinstance(window.screens[window.stack.currentIndex()], SettingsScreen)
    window.close()


def test_inline_review_needs_a_valid_time(qapp):
    _runner, screen = _home(qapp)
    request = MagicMock()
    request.payload = {"event": {"summary": "x", "start": {"dateTime": "2030-06-01T10:00:00Z"}}, "label": ""}
    request.done = threading.Event()
    screen.present_review(request)
    screen.review_form.start.setText("tomorrow")
    screen.answer_review("accept")
    request.answer.assert_not_called()
    assert screen.review_form.error.text() and not screen.review_box.isHidden()
    screen.answer_review("retry")
    request.answer.assert_called_once()
    assert request.answer.call_args.args[0][1] == "retry"


def test_an_unreachable_mailbox_is_reported_instead_of_an_empty_scan(qapp, pump):
    runner, screen = _home(qapp)
    screen.rules.readConfigSrc.return_value.getClient.return_value = None
    with patch.object(home, "add_events_cli") as add_cli:
        screen.run()
        assert pump(lambda: not runner.is_busy())
    add_cli.assert_not_called()
    assert "me@x" in screen.message.text() and screen.message.property("role") == "error"
    assert not screen.accepts_review()

    # A mailbox that answers runs the scan, and the error role goes away.
    screen.rules.readConfigSrc.return_value.getClient.return_value = object()
    with patch.object(home, "add_events_cli", return_value=None) as add_cli:
        screen.run()
        assert pump(lambda: not runner.is_busy())
    add_cli.assert_called_once()
    assert screen.message.property("role") == "" and screen.message.text()


def test_home_warns_about_a_mailbox_configured_to_select_nothing(qapp):
    _runner, screen = _home(qapp)
    screen.rules.more = {
        IMAP: {"service": "imap", "folder": "INBOX", "from": ""},
        MAIL: {"service": "gmail"},
    }
    screen.source.setCurrentIndex(1)
    assert not screen.mailbox_hint.isHidden() and screen.mailbox_hint.text()
    screen.source.setCurrentIndex(0)
    assert screen.mailbox_hint.isHidden()
    screen.rules.more[IMAP]["from"] = 'name:"A"'
    screen.source.setCurrentIndex(1)
    assert screen.mailbox_hint.isHidden()
    assert home.mailbox_warning(None, IMAP) == ""


def test_the_proposal_names_the_source_message(qapp):
    _runner, screen = _home(qapp)
    request = MagicMock()
    request.payload = {
        "event": {"summary": "Visite"},
        "label": "[m1] ",
        "context": {"subject": "Confirmation", "sender": "a@b.org", "date": "2026-09-24 14:33", "identifier": "m1"},
    }
    request.done = threading.Event()
    screen.present_review(request)
    text = screen.review_label.text()
    assert "Confirmation" in text and "a@b.org" in text and "2026-09-24 14:33" in text and "m1" in text

    request.payload = {"event": {"summary": "x"}, "label": "[m2] ", "context": {}}
    screen.present_review(request)
    assert "m2" in screen.review_label.text()

    request.payload = {
        "event": {"summary": "NDU - Salle 1"},
        "label": "[m3] ",
        "context": {
            "subject": "Entretien ménager",
            "kind": "cleaning",
            "room": "Salle 1",
            "occupied_from": "2026-09-27",
            "occupied_to": "2026-10-03",
        },
    }
    screen.present_review(request)
    lines = screen.review_label.text().splitlines()
    assert len(lines) == 2 and "Entretien ménager" in lines[0]
    assert "Salle 1" in lines[1] and "2026-09-27" in lines[1] and "2026-10-03" in lines[1]
