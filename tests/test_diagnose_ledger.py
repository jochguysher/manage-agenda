"""Tests for scripts/diagnose_ledger.py - loaded by path since scripts/ isn't a package (same
convention as the probe scripts, which also aren't imported as a package)."""

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import googleapiclient.errors

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "diagnose_ledger.py"
_spec = importlib.util.spec_from_file_location("diagnose_ledger", _SCRIPT_PATH)
diagnose_ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diagnose_ledger)


def http_error(status):
    return googleapiclient.errors.HttpError(SimpleNamespace(status=status, reason=""), b"{}")


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

        rows = diagnose_ledger.build_rows(state, client, set())

        self.assertEqual(rows[0]["calendar_classification"], "skipped")
        client.events.assert_not_called()

    def test_entry_with_no_refs_at_all_still_produces_one_row(self):
        rows = diagnose_ledger.build_rows(
            {"msg-1": {"events": [], "status": "no_event"}}, MagicMock(), set()
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

        rows = diagnose_ledger.build_rows(state, client, set())

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

        rows = diagnose_ledger.build_rows(state, client, literals)

        self.assertEqual(rows[0]["identity_test_match"], "high")
        self.assertEqual(rows[0]["event_id_test_match"], "medium")
        self.assertEqual(rows[0]["calendar_id_test_match"], "low")  # "primary", also matched


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
