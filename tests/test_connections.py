import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch

from socialModules.configMod import safe_get, select_from_list

from manage_agenda.connections import (
    authorize,
    describe_auth_failure,
    prepare_calendar,
    select_api,
    select_calendar,
    select_calendars,
)
from manage_agenda.exceptions import CalendarError
from manage_agenda.sources import Args
from manage_agenda.user_config import load_user_config, save_user_config


class TestConnections(unittest.TestCase):
    def setUp(self):
        self.Args = namedtuple(
            "args",
            ["interactive", "delete", "source", "verbose", "destination", "text"],
        )

    @patch("manage_agenda.connections.select_one")
    def test_select_calendar(self, mock_select_one):
        mock_calendar_api = MagicMock()
        calendars = [{"summary": "Calendar1", "id": "id1", "accessRole": "owner"}]
        mock_calendar_api.getCalendarList.return_value = calendars
        mock_select_one.return_value = calendars[0]

        result = select_calendar(mock_calendar_api)

        mock_calendar_api.setCalendarList.assert_called_once()
        mock_select_one.assert_called_once()
        self.assertEqual(result, "id1")

    def test_select_calendar_prompts_with_no_args_at_all(self):
        """events.py's clean/copy/move flow calls select_calendar(api, title=...) with no
        `args` - it has always prompted unconditionally in that case."""
        mock_calendar_api = MagicMock()
        calendars = [{"summary": "Calendar1", "id": "id1", "accessRole": "owner"}]
        mock_calendar_api.getCalendarList.return_value = calendars
        with patch("manage_agenda.connections.select_one", return_value=calendars[0]) as mock_select_one:
            result = select_calendar(mock_calendar_api)
        mock_select_one.assert_called_once()
        self.assertEqual(result, "id1")

    def test_select_calendar_non_interactive_without_a_resolved_id_raises_clear_error(self):
        mock_calendar_api = MagicMock()
        calendars = [{"summary": "Calendar1", "id": "id1", "accessRole": "owner"}]
        mock_calendar_api.getCalendarList.return_value = calendars
        args = Args(interactive=False)

        with self.assertRaises(CalendarError) as raised:
            select_calendar(mock_calendar_api, args=args)
        self.assertIn("non-interactive", str(raised.exception))

    @patch("manage_agenda.connections.select_many")
    def test_select_calendars_returns_all_chosen_ids(self, mock_select_many):
        calendars = [
            {"summary": "Personal", "id": "p1", "accessRole": "owner"},
            {"summary": "Work", "id": "w1", "accessRole": "owner"},
        ]
        mock_calendar_api = MagicMock()
        mock_calendar_api.getCalendarList.return_value = calendars
        mock_select_many.return_value = calendars

        result = select_calendars(mock_calendar_api, args=Args(interactive=True))

        self.assertEqual(result, ["p1", "w1"])

    @patch("manage_agenda.connections.select_many", return_value=[])
    def test_select_calendars_with_nothing_chosen_raises(self, mock_select_many):
        calendars = [{"summary": "Personal", "id": "p1", "accessRole": "owner"}]
        mock_calendar_api = MagicMock()
        mock_calendar_api.getCalendarList.return_value = calendars

        with self.assertRaises(CalendarError):
            select_calendars(mock_calendar_api, args=Args(interactive=True))

    def test_select_calendars_non_interactive_without_a_resolved_id_raises_clear_error(self):
        mock_calendar_api = MagicMock()
        calendars = [{"summary": "Calendar1", "id": "id1", "accessRole": "owner"}]
        mock_calendar_api.getCalendarList.return_value = calendars
        args = Args(interactive=False)

        with self.assertRaises(CalendarError) as raised:
            select_calendars(mock_calendar_api, args=args)
        self.assertIn("non-interactive", str(raised.exception))

    def test_select_calendar_without_a_client(self):
        calendar_api = MagicMock()
        calendar_api.getClient.return_value = None
        calendar_api.user = "someone@example.com"
        with self.assertRaises(CalendarError) as raised:
            select_calendar(calendar_api)
        self.assertIn(".Gcalendar_example.com_someone.json", str(raised.exception))
        calendar_api.setCalendarList.assert_not_called()

    def test_auth_failure_names_the_file_without_the_leading_dot(self):
        folder = Path("/tmp/manage-agenda-auth-msg")
        folder.mkdir(exist_ok=True)
        expected = folder / ".Gcalendar_example.com_someone.json"
        neighbor = folder / "Gcalendar_example.com_someone.json"
        expected.unlink(missing_ok=True)
        neighbor.write_text('{"installed": {}}', encoding="utf-8")
        api = MagicMock()
        api.confName.return_value = str(expected)
        api.getServer.return_value = "gmail.com"
        api.getNick.return_value = "someone"
        message = describe_auth_failure(api)
        self.assertIn(str(expected), message)
        self.assertIn(str(neighbor), message)
        self.assertIn("Google was not contacted", message)
        neighbor.unlink(missing_ok=True)

    def test_safe_get(self):
        data = {"a": {"b": {"c": "value"}}}
        self.assertEqual(safe_get(data, ["a", "b", "c"]), "value")
        self.assertEqual(safe_get(data, ["a", "x", "c"]), "")
        self.assertEqual(safe_get(data, ["a", "b", "c", "d"]), "")

    @patch("click.prompt", return_value="0")
    @patch("os.popen")
    @patch("click.echo")
    @patch("click.echo_via_pager")
    def test_list_of_strings_numeric_selection(
        self, mock_echo_via_pager, mock_echo, mock_popen, mock_prompt
    ):
        mock_popen.return_value.read.return_value = "24 80"
        options = ["apple", "banana", "cherry"]
        self.assertEqual(select_from_list(options), (0, "apple"))

    @patch("click.prompt", return_value="ban")
    @patch("os.popen")
    @patch("click.echo")
    @patch("click.echo_via_pager")
    def test_list_of_strings_substring_selection(
        self, mock_echo_via_pager, mock_echo, mock_popen, mock_prompt
    ):
        mock_popen.return_value.read.return_value = "24 80"
        options = ["apple", "banana", "cherry"]
        self.assertEqual(select_from_list(options), (1, "banana"))

    @patch("click.prompt", return_value="")
    @patch("os.popen")
    @patch("click.echo")
    @patch("click.echo_via_pager")
    def test_list_of_strings_default_selection(
        self, mock_echo_via_pager, mock_echo, mock_popen, mock_prompt
    ):
        mock_popen.return_value.read.return_value = "24 80"
        options = ["apple", "banana", "cherry"]
        self.assertEqual(select_from_list(options, default="banana"), (1, "banana"))

    @patch("manage_agenda.connections.moduleRules")
    def test_authorize_interactive(self, mock_module_rules):
        args = self.Args(
            interactive=True,
            delete=False,
            source="any",
            verbose=False,
            destination="",
            text="",
        )
        mock_rules = MagicMock()
        mock_module_rules.from_config.return_value = mock_rules
        with patch(
            "manage_agenda.connections.select_from_list",
            return_value=(1, "gmail"),
        ):
            authorize(args)
        mock_module_rules.from_config.assert_called_once()
        mock_rules.selectRuleInteractive.assert_called_once_with("gmail", title="Account")

    @patch("manage_agenda.connections.moduleRules")
    def test_select_api_interactive(self, mock_module_rules):
        args = self.Args(
            interactive=True,
            delete=False,
            source="any",
            verbose=False,
            destination="",
            text="",
        )
        mock_rules = MagicMock()
        select_api(args, "gmail", rules=mock_rules)
        mock_rules.selectRuleInteractive.assert_called_once_with(["gmail"], title="")

    @patch("manage_agenda.connections.moduleRules")
    def test_select_api_non_interactive(self, mock_module_rules):
        args = self.Args(
            interactive=False,
            delete=False,
            source="any",
            verbose=False,
            destination="",
            text="",
        )
        mock_rules = MagicMock()
        mock_rules.selectRule.return_value = ["test_rule"]
        mock_rules.more.get.return_value = {"key": "value"}
        mock_module_rules.return_value = mock_rules
        select_api(args, "gmail", rules=mock_rules)
        mock_rules.selectRule.assert_called_once_with(["gmail"], "")
        mock_rules.readConfigSrc.assert_called_once_with("", "test_rule", {"key": "value"})

    @patch("manage_agenda.connections.select_from_list")
    def test_select_calendar_no_calendars(self, mock_select_from_list):
        """Test select_calendar when no calendars are found."""
        from manage_agenda.exceptions import CalendarError

        mock_calendar_api = MagicMock()
        mock_calendar_api.getCalendarList.return_value = []

        with self.assertRaises(CalendarError) as context:
            select_calendar(mock_calendar_api)

        self.assertIn("No calendars found", str(context.exception))

    @patch("manage_agenda.connections.select_from_list")
    def test_select_calendar_no_writable(self, mock_select_from_list):
        """Test select_calendar when no writable calendars exist."""
        from manage_agenda.exceptions import CalendarError

        mock_calendar_api = MagicMock()
        calendars = [{"summary": "Calendar1", "id": "id1", "accessRole": "reader"}]
        mock_calendar_api.getCalendarList.return_value = calendars

        with self.assertRaises(CalendarError) as context:
            select_calendar(mock_calendar_api)

        self.assertIn("No writable calendars", str(context.exception))

    @patch("manage_agenda.connections.moduleRules")
    def test_select_api_email_interactive(self, mock_module_rules):
        """Test select_api with email type in interactive mode."""
        args = Args(interactive=True)
        mock_rules = MagicMock()
        mock_module_rules.from_config.return_value = mock_rules

        result = select_api(args, "email")
        self.assertIsNotNone(result)
        mock_rules.selectRuleInteractive.assert_called_once()

    @patch("manage_agenda.connections.moduleRules")
    def test_select_api_email_non_interactive(self, mock_module_rules):
        """Test select_api with email type in non-interactive mode."""
        args = Args(interactive=False)
        mock_rules = MagicMock()
        mock_rules.selectRule.return_value = ["gmail1"]
        mock_rules.more.get.return_value = {"key": "value"}
        mock_module_rules.from_config.return_value = mock_rules

        result = select_api(args, "email", rules=mock_rules)

        self.assertIsNotNone(result)
        mock_rules.selectRule.assert_called_once()
        mock_rules.readConfigSrc.assert_called_once()

    @patch("manage_agenda.connections.moduleRules")
    def test_authorize_success(self, mock_module_rules):
        """Test authorize function."""
        args = Args(interactive=False, delete=False, verbose=False)

        mock_rules = MagicMock()
        mock_rules.selectRule.return_value = ["source1"]
        mock_rules.more.get.return_value = {"key": "value"}

        mock_api_src = MagicMock()
        mock_rules.readConfigSrc.return_value = mock_api_src
        mock_module_rules.return_value = mock_rules

        result = authorize(args, rules=mock_rules)

        self.assertIsNotNone(result)
        self.assertEqual(result, mock_api_src)

    @patch("manage_agenda.connections.moduleRules")
    def test_authorize_no_services(self, mock_module_rules):
        """Test authorize when no services configured."""
        args = Args(interactive=False, delete=False, verbose=False)

        mock_rules = MagicMock()
        mock_rules.selectRule.return_value = []
        mock_module_rules.return_value = mock_rules

        result = authorize(args, rules=mock_rules)

        self.assertIsNone(result)


class TestPrepareCalendar(unittest.TestCase):
    """prepare_calendar's precedence: -d/--destination > saved config > interactive wizard >
    a clear error. config_path is always overridden so these tests never touch the real
    ~/.config/manage-agenda/config.yaml."""

    def setUp(self):
        self.config_path = Path("/tmp") / (self.id().replace(".", "_") + "_config.yaml")
        self.config_path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.config_path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.config_path) + ".tmp").unlink(missing_ok=True))
        self.rules = MagicMock()

    @patch("manage_agenda.connections.select_calendar")
    @patch("manage_agenda.connections.select_api")
    def test_explicit_destination_skips_prompting_and_is_not_saved(
        self, mock_select_api, mock_select_calendar
    ):
        fake_api = MagicMock(src="acct1")
        mock_select_api.return_value = fake_api
        args = Args(interactive=False, destination="cal-explicit")

        result = prepare_calendar(args, rules=self.rules, config_path=self.config_path)

        self.assertTrue(result)
        self.assertEqual(args.calendar_id, "cal-explicit")
        mock_select_calendar.assert_not_called()
        self.assertEqual(load_user_config(self.config_path), {})

    @patch("manage_agenda.connections.select_calendars")
    @patch("manage_agenda.connections.select_api")
    def test_explicit_destination_with_no_account_connection_fails_instead_of_proceeding(
        self, mock_select_api, mock_select_calendars
    ):
        """A resolved calendar id (from a flag or saved config) skips select_calendars()
        entirely, so its own api-is-None guard never runs - prepare_calendar must check
        this itself instead of setting args.calendar_api to a broken connection."""
        mock_select_api.return_value = None
        args = Args(interactive=False, destination="cal-explicit")

        result = prepare_calendar(args, rules=self.rules, config_path=self.config_path)

        self.assertFalse(result)
        mock_select_calendars.assert_not_called()
        self.assertIsNone(getattr(args, "calendar_api", None))

    @patch("manage_agenda.connections.select_calendars")
    @patch("manage_agenda.connections.select_api")
    def test_saved_config_is_reused_without_any_prompting(self, mock_select_api, mock_select_calendars):
        save_user_config(
            {"calendar_account": "acct1", "calendar": ["cal-saved-1", "cal-saved-2"]},
            self.config_path,
        )
        fake_api = MagicMock(src="acct1")
        self.rules.readConfigSrc.return_value = fake_api
        self.rules.more.get.return_value = {}
        args = Args(interactive=True)

        result = prepare_calendar(args, rules=self.rules, config_path=self.config_path)

        self.assertTrue(result)
        self.assertEqual(args.calendar_ids, ["cal-saved-1", "cal-saved-2"])
        mock_select_api.assert_not_called()
        mock_select_calendars.assert_not_called()
        self.rules.readConfigSrc.assert_called_once_with("", "acct1", {})

    @patch("manage_agenda.connections.select_calendars")
    @patch("manage_agenda.connections.select_api")
    def test_a_saved_rule_key_tuple_read_back_as_a_list_still_resolves(
        self, mock_select_api, mock_select_calendars
    ):
        """A real socialModules rule key is a tuple; config.yaml (yaml.safe_dump) stores it as a
        list, and a list can't be the dict key rules.more is looked up by - the saved account
        must be turned back into the tuple, not crash every run after the first save."""
        key = ("gcalendar", "set", "me@example.com", "posts")
        save_user_config({"calendar_account": key, "calendar": ["cal-saved"]}, self.config_path)
        self.rules.more = {key: {"x": 1}}
        self.rules.readConfigSrc.return_value = MagicMock(src=key)
        args = Args(interactive=False)

        result = prepare_calendar(args, rules=self.rules, config_path=self.config_path)

        self.assertTrue(result)
        self.rules.readConfigSrc.assert_called_once_with("", key, {"x": 1})
        mock_select_api.assert_not_called()

    @patch("manage_agenda.connections.select_calendars")
    @patch("manage_agenda.connections.select_api")
    def test_interactive_selection_of_several_calendars_is_saved(
        self, mock_select_api, mock_select_calendars
    ):
        fake_api = MagicMock(src="acct1")
        mock_select_api.return_value = fake_api
        mock_select_calendars.return_value = ["cal-one", "cal-two"]
        args = Args(interactive=True)

        result = prepare_calendar(args, rules=self.rules, config_path=self.config_path)

        self.assertTrue(result)
        self.assertEqual(args.calendar_ids, ["cal-one", "cal-two"])
        self.assertEqual(args.calendar_id, "cal-one")
        self.assertEqual(
            load_user_config(self.config_path),
            {"calendar_account": "acct1", "calendar": ["cal-one", "cal-two"]},
        )

    @patch("manage_agenda.connections.select_calendars")
    @patch("manage_agenda.connections.select_api")
    def test_reconfigure_prompts_again_and_overwrites_the_saved_choice(
        self, mock_select_api, mock_select_calendars
    ):
        save_user_config(
            {"calendar_account": "acct1", "calendar": ["cal-old"]}, self.config_path
        )
        fake_api = MagicMock(src="acct2")
        mock_select_api.return_value = fake_api
        mock_select_calendars.return_value = ["cal-new"]
        args = Args(interactive=False, reconfigure=True)

        result = prepare_calendar(args, rules=self.rules, config_path=self.config_path)

        self.assertTrue(result)
        mock_select_api.assert_called_once()
        mock_select_calendars.assert_called_once()
        self.assertEqual(
            load_user_config(self.config_path),
            {"calendar_account": "acct2", "calendar": ["cal-new"]},
        )

    @patch("manage_agenda.connections.select_api")
    def test_non_interactive_with_nothing_configured_fails_clearly(self, mock_select_api):
        fake_api = MagicMock(src="acct1")
        mock_select_api.return_value = fake_api
        args = Args(interactive=False)

        result = prepare_calendar(args, rules=self.rules, config_path=self.config_path)

        self.assertFalse(result)
