"""The Lists and Auth screens: their core helpers (run in the job runner) and how they fill
their widgets from the result."""

from unittest.mock import MagicMock, patch

from manage_agenda.gui.bridge import Bridge
from manage_agenda.gui.jobs import JobRunner
from manage_agenda.gui.screens import auth, lists
from manage_agenda.gui.widgets import AccountPicker, account_label, rule_keys


def _rules(keys_by_service):
    rules = MagicMock()
    rules.selectRule.side_effect = lambda name, _sel="": list(keys_by_service.get(name, []))
    rules.more = {}
    return rules


def test_rule_keys_and_account_picker(qapp):
    rules = _rules({"gmail": [("gmail", "set", "a@x", "posts")], "imap": [("imap", "set", "b@y", "posts")]})
    assert rule_keys(rules, ["gmail", "imap"]) == [("gmail", "set", "a@x", "posts"), ("imap", "set", "b@y", "posts")]
    picker = AccountPicker(["gmail"])
    assert picker.current_key() is None
    picker.refresh(rules)
    assert picker.count() == 1
    assert picker.current_key() == ("gmail", "set", "a@x", "posts")
    assert picker.itemText(0) == "a@x (gmail)"
    assert account_label(("web/http", "set", "(Enter URLs or leave empty)")) == "web/http"
    assert account_label("plain") == "plain"


def test_fetch_listing_rows(qapp):
    rules = _rules({})
    api = MagicMock()
    api.getPostTitle.side_effect = lambda post: post["title"]
    api.getPostDate.side_effect = lambda post: post["date"]
    rules.readConfigSrc.return_value = api
    posts = [{"title": "One", "date": "2024-01-01"}, {"title": None, "date": None}]
    with patch.object(lists, "_get_events_from_calendar", return_value=posts) as get_events:
        rows = lists.fetch_listing(rules, ("gcalendar", "set", "a", "posts"), "gcalendar", lists.Args())
    assert rows == [("One", "2024-01-01"), ("", "")]
    get_events.assert_called_once()
    with patch.object(lists, "_get_emails_from_folder", return_value=None) as get_emails:
        assert lists.fetch_listing(rules, ("gmail", "set", "a", "posts"), "gmail", lists.Args()) == []
    get_emails.assert_called_once()


def test_lists_screen_fills_its_table_from_the_job(qapp, pump):
    runner = JobRunner(Bridge())
    screen = lists.ListsScreen(runner)
    rules = _rules({"gmail": [("gmail", "set", "a@x", "posts")], "gcalendar": [("gcalendar", "set", "c", "posts")]})
    with patch.object(lists, "load_rules", return_value=rules):
        screen.refresh()
    assert screen.account.current_key() == ("gmail", "set", "a@x", "posts")
    screen.service.setCurrentText("gcalendar")
    assert screen.account.current_key() == ("gcalendar", "set", "c", "posts")

    with patch.object(lists, "fetch_listing", return_value=[("Ev", "2024")]):
        screen.run()
        assert pump(lambda: not runner.is_busy())
    assert screen.table.rowCount() == 1
    assert screen.table.item(0, 0).text() == "Ev"
    assert screen.empty.text() == ""
    assert screen.run_button.isEnabled()

    with patch.object(lists, "fetch_listing", return_value=[]):
        screen.run()
        assert pump(lambda: not runner.is_busy())
    assert screen.table.rowCount() == 0
    assert screen.empty.text()


def test_lists_screen_without_accounts_explains(qapp):
    runner = JobRunner(Bridge())
    screen = lists.ListsScreen(runner)
    with patch.object(lists, "load_rules", return_value=_rules({})):
        screen.refresh()
    screen.run()
    assert not runner.is_busy()
    assert screen.empty.text()


def test_lists_screen_survives_a_broken_configuration(qapp):
    runner = JobRunner(Bridge())
    screen = lists.ListsScreen(runner)
    with patch.object(lists, "load_rules", side_effect=OSError("no .rssBlogs")):
        screen.refresh()
    assert "no .rssBlogs" in screen.last_error
    assert screen.rules is None


def test_check_auth_and_run_oauth(qapp):
    rules = _rules({})
    api = MagicMock()
    api.getClient.return_value = True
    rules.readConfigSrc.return_value = api
    assert auth.check_auth(rules, ("gcalendar", "set", "a", "posts"))[0] is True

    api.getClient.return_value = None
    with patch.object(auth, "describe_auth_failure", return_value="missing file"):
        assert auth.check_auth(rules, "k") == (False, "missing file")
        with patch.object(auth, "credential_path", return_value="/nowhere/client.json"):
            ok, message = auth.run_oauth(rules, "k")
        assert ok is False and "missing file" in message

    with patch.object(auth, "credential_path", return_value=__file__), patch.object(
        auth, "complete_desktop_oauth", return_value=True
    ) as consent, patch.object(auth, "echo"):
        assert auth.run_oauth(rules, "k")[0] is True
    consent.assert_called_once_with(api)


def test_auth_screen_shows_the_result(qapp, pump):
    runner = JobRunner(Bridge())
    screen = auth.AuthScreen(runner)
    rules = _rules({"gcalendar": [("gcalendar", "set", "c", "posts")]})
    with patch.object(auth, "load_rules", return_value=rules):
        screen.refresh()
    with patch.object(auth, "check_auth", return_value=(False, "no token")):
        screen.check_button.click()
        assert pump(lambda: not runner.is_busy())
    assert "no token" in screen.status.toPlainText()
    assert screen.check_button.isEnabled() and screen.oauth_button.isEnabled()
