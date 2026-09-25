"""The Add and Settings screens: the Args the form builds, what it submits, and the
config.yaml round trip (under conftest's isolated XDG_CONFIG_HOME)."""

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QDialog

from manage_agenda.gui.bridge import Bridge
from manage_agenda.gui.jobs import JobRunner
from manage_agenda.gui.screens import add, settings
from manage_agenda.sources import Args
from manage_agenda.user_config import load_user_config, save_user_config

MAIL = ("gmail", "set", "me@x", "posts")
CAL = ("gcalendar", "set", "me@x", "posts")
WEB = ("web/http", "set", "(Enter URLs or leave empty)")
TEXT = ("text", "set", "(enter filenames or leave empty)")


def _rules():
    rules = MagicMock()
    rules.selectRule.side_effect = lambda name, _sel="": {"gcalendar": [CAL]}.get(name, [])
    rules.more = {}
    return rules


def _add_screen(qapp):
    runner = JobRunner(Bridge())
    screen = add.AddScreen(runner)
    with patch.object(add, "load_rules", return_value=_rules()), patch.object(
        add, "get_add_sources", return_value=([MAIL], [WEB, TEXT])
    ):
        screen.refresh()
    return runner, screen


def test_add_screen_lists_mail_accounts_then_web_and_text(qapp):
    _runner, screen = _add_screen(qapp)
    assert screen.sources == [MAIL, WEB, TEXT]
    assert screen.selected_source() == MAIL
    assert not screen.urls.isEnabled() and not screen.files.isEnabled()
    assert screen.urls.isHidden() and screen.files.isHidden()
    assert not screen.advanced_box.isChecked() and screen.advanced_box.body.isHidden()
    screen.source.setCurrentIndex(1)
    assert screen.urls.isEnabled() and not screen.files.isEnabled()
    assert not screen.urls.isHidden() and screen.files.isHidden()
    screen.source.setCurrentIndex(2)
    assert screen.files.isEnabled()


def test_add_screen_default_args_match_the_cli_defaults(qapp):
    _runner, screen = _add_screen(qapp)
    assert screen.build_args() == Args(interactive=True, debug_log_retention_days=7)


def test_add_screen_args_follow_the_form(qapp):
    _runner, screen = _add_screen(qapp)
    screen.provider.setCurrentIndex(screen.provider.findData("gemini"))
    screen.model.setText(" gemini-pro ")
    screen.output.setCurrentText("file")
    screen.rule.setCurrentIndex(screen.rule.findData("review"))
    screen.force_refresh.setChecked(True)
    screen.dry_run_ledger.setChecked(True)
    screen.debug_log.setChecked(True)
    screen.retention.setValue(30)
    assert screen.build_args() == Args(
        interactive=True,
        ai="gemini",
        model="gemini-pro",
        output="file",
        force_refresh=True,
        rule="review",
        dry_run_ledger=True,
        debug_log_extractions=True,
        debug_log_retention_days=30,
    )


def test_chosen_calendars_pre_answer_the_calendar_question(qapp):
    _runner, screen = _add_screen(qapp)
    assert not screen.calendar_ids and screen.calendars_summary.text()
    api = MagicMock()
    calendars = [{"id": "c1", "summary": "One"}, {"id": "c2", "summary": "Two"}]
    screen.set_calendars(CAL, api, calendars, ["c2", "ghost"])
    assert screen.calendar_ids == ["c2"] and "Two" in screen.calendars_summary.text()
    args = screen.build_args()
    assert args.calendar_api is api
    assert args.calendar_ids == ["c2"] and args.calendar_id == "c2"
    screen.output.setCurrentText("file")
    assert not hasattr(screen.build_args(), "calendar_api")

    # The choice belongs to the account it was made on.
    screen.output.setCurrentText("calendar")
    screen.set_calendars(("gcalendar", "set", "other", "posts"), api, calendars, ["c1"])
    assert not hasattr(screen.build_args(), "calendar_api")
    assert "One" not in screen.calendars_summary.text()


def test_run_submits_add_events_cli_with_the_selection(qapp, pump):
    runner, screen = _add_screen(qapp)
    with patch.object(add, "add_events_cli") as add_cli:
        screen.run()
        assert pump(lambda: not runner.is_busy())
    add_cli.assert_called_once()
    args, rules, selected = add_cli.call_args.args
    assert args.interactive is True and selected == MAIL and rules is screen.rules

    screen.source.setCurrentIndex(1)
    screen.urls.setText(" http://a http://b ")
    assert screen.selection_for_run() == "http://a http://b"
    screen.urls.setText("")
    assert screen.selection_for_run() == WEB
    screen.source.setCurrentIndex(2)
    screen.files.setText("a.txt")
    assert screen.selection_for_run() == "a.txt"


def test_run_without_a_source_does_not_submit(qapp):
    runner = JobRunner(Bridge())
    screen = add.AddScreen(runner)
    screen.run()
    assert not runner.is_busy()
    assert screen.message.text()


def test_load_calendars_opens_the_dialog_with_the_saved_ids_checked(qapp, pump):
    runner, screen = _add_screen(qapp)
    screen._saved_calendar_ids = ["c2"]
    api = MagicMock()
    calendars = [{"id": "c1", "summary": "One"}, {"id": "c2", "summary": "Two"}]
    opened = []

    def accept(dialog):
        opened.append(dialog.checked_ids())
        dialog.picker.set_all(True)
        return QDialog.DialogCode.Accepted

    with patch.object(add, "fetch_calendars", return_value=(api, calendars)), patch.object(
        add.CalendarSelectionDialog, "exec", accept
    ):
        screen.load_calendars()
        assert pump(lambda: not runner.is_busy())
    assert opened == [["c2"]]
    assert screen.calendar_ids == ["c1", "c2"] and screen.calendar_api is api
    assert "One, Two" in screen.calendars_summary.text()

    # Cancelling keeps the choice; the dialog reopens on that choice, not the saved one.
    def cancel(dialog):
        opened.append(dialog.checked_ids())
        return QDialog.DialogCode.Rejected

    with patch.object(add, "fetch_calendars", return_value=(api, calendars)), patch.object(
        add.CalendarSelectionDialog, "exec", cancel
    ):
        screen.load_calendars()
        assert pump(lambda: not runner.is_busy())
    assert opened[-1] == ["c1", "c2"] and screen.calendar_ids == ["c1", "c2"]


def test_settings_round_trip(qapp):
    runner = JobRunner(Bridge())
    screen = settings.SettingsScreen(runner)
    save_user_config({"provider": "mistral", "model": "m", "calendar_account": list(CAL), "calendar": ["c1", "c2"], "language": "fr", "other": 1})
    with patch.object(settings, "load_rules", return_value=_rules()):
        screen.refresh()
    assert screen.provider.currentData() == "mistral"
    assert screen.model.text() == "m"
    assert screen.account.current_key() == CAL
    assert screen.calendar_ids.text() == "c1, c2"
    assert screen.language.currentData() == "fr"

    screen.provider.setCurrentIndex(screen.provider.findData("ollama"))
    screen.model.setText("")
    screen.calendar_ids.setText("c3")
    screen.language.setCurrentIndex(0)
    screen.save()
    assert load_user_config() == {"other": 1, "provider": "ollama", "calendar_account": list(CAL), "calendar": ["c3"]}
    assert screen.message.text()


def test_settings_picker_fills_the_ids_field(qapp, pump):
    runner = JobRunner(Bridge())
    screen = settings.SettingsScreen(runner)
    with patch.object(settings, "load_rules", return_value=_rules()):
        screen.refresh()
    api = MagicMock()
    calendars = [{"id": "c1", "summary": "One"}, {"id": "c2", "summary": "Two"}]
    with patch.object(settings, "fetch_calendars", return_value=(api, calendars)):
        screen.load_calendars()
        assert pump(lambda: not runner.is_busy())
    screen.calendars.item(1).setCheckState(screen.calendars.item(1).checkState().Checked)
    assert screen.calendar_ids.text() == "c2"


def test_settings_save_keeps_the_saved_account_when_accounts_cannot_be_listed(qapp):
    runner = JobRunner(Bridge())
    screen = settings.SettingsScreen(runner)
    save_user_config({"calendar_account": list(CAL), "calendar": ["c1"], "provider": "ollama"})
    with patch.object(settings, "load_rules", side_effect=OSError("no .rssBlogs")):
        screen.refresh()
    assert screen.account.keys == []
    screen.model.setText("m2")
    screen.save()
    saved = load_user_config()
    assert saved["calendar_account"] == list(CAL)
    assert saved["model"] == "m2" and saved["calendar"] == ["c1"]


def test_settings_names_the_typed_calendar_ids_when_it_can(qapp, pump):
    runner = JobRunner(Bridge())
    screen = settings.SettingsScreen(runner)
    save_user_config({"calendar_account": list(CAL), "calendar": ["c1", "c2"], "calendar_names": {"c1": "One"}})
    with patch.object(settings, "load_rules", return_value=_rules()):
        screen.refresh()
    assert "One" in screen.calendar_names.text() and not screen.calendar_names.isHidden()

    screen.calendar_ids.setText("c2")
    assert screen.calendar_names.text() == "" and screen.calendar_names.isHidden()

    api = MagicMock()
    calendars = [{"id": "c1", "summary": "One"}, {"id": "c2", "summary": "Two"}]
    with patch.object(settings, "fetch_calendars", return_value=(api, calendars)):
        screen.load_calendars()
        assert pump(lambda: not runner.is_busy())
    assert "Two" in screen.calendar_names.text() and not screen.calendar_names.isHidden()
    screen.calendars.item(0).setCheckState(screen.calendars.item(0).checkState().Checked)
    assert screen.calendar_ids.text() == "c1, c2" and "One, Two" in screen.calendar_names.text()


def test_settings_shows_the_calendar_list_only_once_loaded(qapp, pump):
    runner = JobRunner(Bridge())
    screen = settings.SettingsScreen(runner)
    screen.show()
    assert screen.calendars.isHidden()
    with patch.object(settings, "load_rules", return_value=_rules()):
        screen.refresh()
    with patch.object(settings, "fetch_calendars", return_value=(MagicMock(), [{"id": "c1", "summary": "One"}])):
        screen.load_calendars()
        assert pump(lambda: not runner.is_busy())
    assert not screen.calendars.isHidden() and screen.calendars.count() == 1
    screen.hide()


def test_calendar_summary_names_the_saved_calendars_and_the_dialog_saves_its_choice(qapp):
    save_user_config({"calendar_account": list(CAL), "calendar": ["c1"], "calendar_names": {"c1": "Work"}})
    _runner, screen = _add_screen(qapp)
    assert screen.account.current_key() == CAL
    assert "Work" in screen.calendars_summary.text()  # the saved choice, named, no loading needed

    calendars = [{"id": "c1", "summary": "Work"}, {"id": "c2", "summary": "Home"}]
    screen.set_calendars(CAL, MagicMock(), calendars, ["c2"])
    assert "Home" in screen.calendars_summary.text() and "Work" not in screen.calendars_summary.text()
    saved = load_user_config()
    assert saved["calendar"] == ["c2"] and saved["calendar_account"] == list(CAL)

    screen.set_calendars(CAL, MagicMock(), calendars, [])  # unticked: nothing chosen any more
    assert screen.calendars_summary.text() == settings.t("gui.add.calendars_none")
    assert load_user_config()["calendar"] == []
