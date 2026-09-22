"""Tests for scripts/diagnose_ledger.py - loaded by path since scripts/ isn't a package (same
convention as the probe scripts, which also aren't imported as a package)."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import googleapiclient.errors
import pytest

from manage_agenda.sources import CalendarScope

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "diagnose_ledger.py"
_spec = importlib.util.spec_from_file_location("diagnose_ledger", _SCRIPT_PATH)
diagnose_ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diagnose_ledger)


def http_error(status):
    return googleapiclient.errors.HttpError(SimpleNamespace(status=status, reason=""), b"{}")


# One configured calendar account, "acct", seeing calendar "cal-1": legacy "primary" refs are
# attributable to it (see CalendarScope.owner_of).
SOLE_ACCOUNT = CalendarScope(account_key="acct", owned_ids={"cal-1"}, sole_account=True)


class TestConfidence(unittest.TestCase):
    def test_no_match_is_empty(self):
        self.assertEqual(diagnose_ledger.confidence("never-seen", {"e1"}), "")

    def test_message_id_shaped_match_is_high(self):
        literals = {"gone@example.com"}
        self.assertEqual(diagnose_ledger.confidence("gone@example.com", literals), "high")

    def test_generic_short_token_match_is_medium(self):
        literals = {"e1", "cal-1"}
        self.assertEqual(diagnose_ledger.confidence("e1", literals), "medium")

    def test_common_real_identifier_is_low_even_if_matched(self):
        literals = {"primary", "INBOX"}
        self.assertEqual(diagnose_ledger.confidence("primary", literals), "low")
        self.assertEqual(diagnose_ledger.confidence("INBOX", literals), "low")

    def test_empty_value_is_never_a_match(self):
        self.assertEqual(diagnose_ledger.confidence("", {""}), "")


class TestCollectTestLiterals(unittest.TestCase):
    def test_collects_string_constants_via_ast(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "test_example.py").write_text(
                'IDENTITY = "gone@example.com"\n'
                'CAL = "cal-1"\n'
                'x = f"not-a-literal-{CAL}"\n'
            )
            literals = diagnose_ledger.collect_test_literals(tmp_path)

        self.assertIn("gone@example.com", literals)
        self.assertIn("cal-1", literals)
        # The f-string's own template pieces are separate constants ast sees, not the
        # interpolated runtime value - this just documents that ast, not text search, is used.
        self.assertNotIn("not-a-literal-cal-1", literals)

    def test_unparseable_file_is_skipped_not_fatal(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "broken.py").write_text("this is not valid python (((")
            literals = diagnose_ledger.collect_test_literals(tmp_path)

        self.assertEqual(literals, set())


class TestClassifyEvent(unittest.TestCase):
    def _client(self, outcome):
        client = MagicMock()
        if isinstance(outcome, BaseException):
            client.events.return_value.get.return_value.execute.side_effect = outcome
        else:
            client.events.return_value.get.return_value.execute.return_value = outcome
        return client

    def test_active_event(self):
        client = self._client({"id": "e1", "status": "confirmed"})
        classification, detail = diagnose_ledger.classify_event(client, "primary", "e1")
        self.assertEqual(classification, "active")
        self.assertEqual(detail, "confirmed")

    def test_cancelled_event(self):
        client = self._client({"id": "e1", "status": "cancelled"})
        classification, _detail = diagnose_ledger.classify_event(client, "primary", "e1")
        self.assertEqual(classification, "cancelled")

    def test_not_found_event(self):
        client = self._client(http_error(404))
        classification, _detail = diagnose_ledger.classify_event(client, "primary", "e1")
        self.assertEqual(classification, "not_found")

    def test_gone_410_is_also_not_found(self):
        client = self._client(http_error(410))
        classification, _detail = diagnose_ledger.classify_event(client, "primary", "e1")
        self.assertEqual(classification, "not_found")

    def test_ambiguous_error_is_reported_not_raised(self):
        client = self._client(http_error(500))
        classification, detail = diagnose_ledger.classify_event(client, "primary", "e1")
        self.assertEqual(classification, "error")
        self.assertTrue(detail)


class TestBuildRows(unittest.TestCase):
    def test_ref_with_missing_ids_is_skipped_not_queried(self):
        client = MagicMock()
        state = {"msg-1": {"events": [{"calendar_id": "", "event_id": ""}], "status": "created"}}

        rows = diagnose_ledger.build_rows(state, client, set(), SOLE_ACCOUNT)

        self.assertEqual(rows[0]["calendar_classification"], "skipped")
        client.events.assert_not_called()

    def test_entry_with_no_refs_at_all_still_produces_one_row(self):
        rows = diagnose_ledger.build_rows(
            {"msg-1": {"events": [], "status": "no_event"}}, MagicMock(), set(), SOLE_ACCOUNT
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["calendar_classification"], "-")

    def test_cancelled_events_are_included_with_their_own_ref_source(self):
        client = MagicMock()
        client.events.return_value.get.return_value.execute.return_value = {
            "id": "e1",
            "status": "cancelled",
        }
        state = {
            "msg-1": {
                "events": [],
                "cancelled_events": [{"calendar_id": "primary", "event_id": "e1"}],
                "status": "no_event",
            }
        }

        rows = diagnose_ledger.build_rows(state, client, set(), SOLE_ACCOUNT)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ref_source"], "cancelled_events")
        self.assertEqual(rows[0]["calendar_classification"], "cancelled")

    def test_identity_and_ref_test_matches_are_reported_independently(self):
        client = MagicMock()
        client.events.return_value.get.return_value.execute.return_value = {"status": "confirmed"}
        state = {
            "gone@example.com": {
                "events": [{"calendar_id": "primary", "event_id": "e1"}],
                "status": "created",
            }
        }
        literals = {"gone@example.com", "e1", "primary"}

        rows = diagnose_ledger.build_rows(state, client, literals, SOLE_ACCOUNT)

        self.assertEqual(rows[0]["identity_test_match"], "high")
        self.assertEqual(rows[0]["event_id_test_match"], "medium")
        self.assertEqual(rows[0]["calendar_id_test_match"], "low")  # "primary", also matched


class TestBuildRowsAccountScope(unittest.TestCase):
    """A real entry of another calendar account must never be reported not_found: refs that
    aren't this account's are classified calendar_inaccessible and never queried - a 404 from
    a calendar this account can't see says nothing about the event."""

    def _client_answering_404(self):
        client = MagicMock()
        client.events.return_value.get.return_value.execute.side_effect = http_error(404)
        return client

    def _classify(self, ref, scope):
        client = self._client_answering_404()
        rows = diagnose_ledger.build_rows(
            {"msg-1": {"events": [ref], "status": "created"}}, client, set(), scope
        )
        return rows[0], client

    def test_calendar_missing_from_this_accounts_calendar_list(self):
        row, client = self._classify({"calendar_id": "cal-other", "event_id": "e1"}, SOLE_ACCOUNT)

        self.assertEqual(row["calendar_classification"], "calendar_inaccessible")
        self.assertIn("calendar list", row["calendar_detail"])
        client.events.assert_not_called()

    def test_ref_recorded_for_another_calendar_account(self):
        row, client = self._classify(
            {"calendar_id": "primary", "event_id": "e1", "calendar_account": "other-acct"}, SOLE_ACCOUNT
        )

        self.assertEqual(row["calendar_classification"], "calendar_inaccessible")
        self.assertIn("other-acct", row["calendar_detail"])
        self.assertEqual(row["ref_calendar_account"], "other-acct")
        client.events.assert_not_called()

    def test_legacy_primary_ref_with_several_accounts_is_never_guessed(self):
        several = CalendarScope(account_key="acct", owned_ids={"cal-1"}, sole_account=False)

        row, client = self._classify({"calendar_id": "primary", "event_id": "e1"}, several)

        self.assertEqual(row["calendar_classification"], "calendar_inaccessible")
        self.assertEqual(row["ref_calendar_account"], "(not recorded)")
        client.events.assert_not_called()

    def test_a_404_on_this_accounts_own_calendar_is_not_found(self):
        row, client = self._classify({"calendar_id": "cal-1", "event_id": "e1"}, SOLE_ACCOUNT)

        self.assertEqual(row["calendar_classification"], "not_found")
        client.events.assert_called()


class TestConnectCalendar:
    def test_default_uses_the_saved_account_read_back_as_a_list(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("calendar_account:\n- gcalendar\n- set\n- me@example.com\n", encoding="utf-8")
        rules = MagicMock()
        key = ("gcalendar", "set", "me@example.com")
        rules.more = {key: {"x": 1}}

        api = diagnose_ledger.connect_calendar(False, rules, config_path=config)

        rules.readConfigSrc.assert_called_once_with("", key, {"x": 1})
        assert api is rules.readConfigSrc.return_value

    def test_no_saved_account_exits_rather_than_picking_one(self, tmp_path):
        rules = MagicMock()

        with pytest.raises(SystemExit):
            diagnose_ledger.connect_calendar(False, rules, config_path=tmp_path / "missing.yaml")

        rules.readConfigSrc.assert_not_called()


class TestRender(unittest.TestCase):
    ROW = {
        "identity": "msg-1",
        "status": "created",
        "ref_source": "events",
        "calendar_id": "primary",
        "event_id": "e1",
        "calendar_classification": "active",
        "calendar_detail": "confirmed",
        "identity_test_match": "",
        "calendar_id_test_match": "low",
        "event_id_test_match": "",
    }

    def test_json_round_trips(self):
        rendered = diagnose_ledger.render([self.ROW], "json")
        self.assertEqual(json.loads(rendered), [self.ROW])

    def test_csv_has_a_header_and_one_data_row(self):
        rendered = diagnose_ledger.render([self.ROW], "csv")
        lines = rendered.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("identity", lines[0])
        self.assertIn("msg-1", lines[1])


if __name__ == "__main__":
    unittest.main()
