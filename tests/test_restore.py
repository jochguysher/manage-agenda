import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from manage_agenda.sources import (
    Args,
    _attempt_restore_one_event,
    list_restorable_identities_cli,
    load_handled_mail_state,
    mark_events_restored,
    restore_deleted_event_cli,
)


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def _write_state(self, messages):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"messages": messages}), encoding="utf-8")


class TestMarkEventsRestored(LedgerTestCase):
    def test_moves_the_restored_ref_back_into_events(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [],
                    "cancelled_events": [{"calendar_id": "primary", "event_id": "e1"}],
                    "status": "no_event",
                }
            }
        )

        mark_events_restored("msg-1", [{"calendar_id": "primary", "event_id": "e1"}], path=self.path)

        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["events"], [{"calendar_id": "primary", "event_id": "e1"}])
        self.assertEqual(entry["status"], "created")
        self.assertNotIn("cancelled_events", entry)

    def test_partial_restore_keeps_the_rest_in_cancelled_events(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [],
                    "cancelled_events": [
                        {"calendar_id": "primary", "event_id": "e1"},
                        {"calendar_id": "primary", "event_id": "e2"},
                    ],
                    "status": "no_event",
                }
            }
        )

        mark_events_restored("msg-1", [{"calendar_id": "primary", "event_id": "e1"}], path=self.path)

        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["events"], [{"calendar_id": "primary", "event_id": "e1"}])
        self.assertEqual(entry["cancelled_events"], [{"calendar_id": "primary", "event_id": "e2"}])

    def test_unknown_identity_is_a_no_op(self):
        self._write_state({})

        mark_events_restored("nope", [{"calendar_id": "primary", "event_id": "e1"}], path=self.path)

        self.assertEqual(load_handled_mail_state(self.path), {})

    def test_empty_restored_refs_is_a_no_op(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [],
                    "cancelled_events": [{"calendar_id": "primary", "event_id": "e1"}],
                    "status": "no_event",
                }
            }
        )

        mark_events_restored("msg-1", [], path=self.path)

        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["status"], "no_event")
        self.assertEqual(entry["cancelled_events"], [{"calendar_id": "primary", "event_id": "e1"}])


class TestListRestorableIdentitiesCli(LedgerTestCase):
    def test_lists_identities_with_cancelled_events(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [],
                    "cancelled_events": [{"calendar_id": "primary", "event_id": "e1"}],
                    "status": "no_event",
                },
                "msg-2": {"events": [{"calendar_id": "primary", "event_id": "e2"}], "status": "created"},
            }
        )

        captured = io.StringIO()
        sys.stdout = captured
        try:
            list_restorable_identities_cli(path=self.path)
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        self.assertIn("msg-1", output)
        self.assertIn("e1", output)
        self.assertNotIn("msg-2", output)

    def test_empty_ledger_prints_the_empty_message(self):
        self._write_state({})

        captured = io.StringIO()
        sys.stdout = captured
        try:
            list_restorable_identities_cli(path=self.path)
        finally:
            sys.stdout = sys.__stdout__

        self.assertIn("No identity", captured.getvalue())


class TestAttemptRestoreOneEvent(unittest.TestCase):
    def test_true_only_when_the_followup_get_confirms_it(self):
        client = MagicMock()
        client.events.return_value.get.return_value.execute.return_value = {"status": "confirmed"}

        result = _attempt_restore_one_event(client, "primary", "e1")

        self.assertTrue(result)
        client.events.return_value.patch.assert_called_once_with(
            calendarId="primary", eventId="e1", body={"status": "confirmed"}
        )

    def test_false_when_the_followup_get_still_shows_cancelled(self):
        """The exact scenario probe (b) exists to resolve: patch() returns 200 but the event
        stays cancelled - this must never be reported as a success."""
        client = MagicMock()
        client.events.return_value.get.return_value.execute.return_value = {"status": "cancelled"}

        result = _attempt_restore_one_event(client, "primary", "e1")

        self.assertFalse(result)

    def test_false_when_patch_raises(self):
        client = MagicMock()
        client.events.return_value.patch.return_value.execute.side_effect = Exception("boom")

        result = _attempt_restore_one_event(client, "primary", "e1")

        self.assertFalse(result)
        client.events.return_value.get.assert_not_called()

    def test_false_when_the_followup_get_raises(self):
        client = MagicMock()
        client.events.return_value.get.return_value.execute.side_effect = Exception("gone")

        result = _attempt_restore_one_event(client, "primary", "e1")

        self.assertFalse(result)


class TestRestoreDeletedEventCli(LedgerTestCase):
    def _args(self):
        return Args(interactive=False, delete=None, source=None, verbose=False, destination=None, text=None)

    @patch("manage_agenda.sources.select_api")
    def test_unknown_identity_does_not_touch_any_api(self, mock_select_api):
        self._write_state({})

        result = restore_deleted_event_cli(self._args(), "nope")

        self.assertFalse(result)
        mock_select_api.assert_not_called()

    @patch("manage_agenda.sources.select_api")
    def test_identity_with_nothing_cancelled_does_not_touch_any_api(self, mock_select_api):
        self._write_state({"msg-1": {"events": [{"calendar_id": "primary", "event_id": "e1"}], "status": "created"}})

        with patch("manage_agenda.sources.handled_mail_file", return_value=self.path):
            result = restore_deleted_event_cli(self._args(), "msg-1")

        self.assertFalse(result)
        mock_select_api.assert_not_called()

    @patch("manage_agenda.sources._attempt_restore_one_event")
    @patch("manage_agenda.sources.select_api")
    def test_successful_restore_updates_the_ledger(self, mock_select_api, mock_attempt):
        self._write_state(
            {
                "msg-1": {
                    "events": [],
                    "cancelled_events": [{"calendar_id": "primary", "event_id": "e1"}],
                    "status": "no_event",
                }
            }
        )
        mock_attempt.return_value = True
        mock_api_cal = MagicMock()
        mock_select_api.return_value = mock_api_cal

        with patch("manage_agenda.sources.handled_mail_file", return_value=self.path):
            result = restore_deleted_event_cli(self._args(), "msg-1")

        self.assertTrue(result)
        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["status"], "created")
        self.assertEqual(entry["events"], [{"calendar_id": "primary", "event_id": "e1"}])

    @patch("manage_agenda.sources._attempt_restore_one_event")
    @patch("manage_agenda.sources.select_api")
    def test_failed_restore_leaves_the_ledger_untouched_and_reports_it(self, mock_select_api, mock_attempt):
        self._write_state(
            {
                "msg-1": {
                    "events": [],
                    "cancelled_events": [{"calendar_id": "primary", "event_id": "e1"}],
                    "status": "no_event",
                }
            }
        )
        mock_attempt.return_value = False
        mock_select_api.return_value = MagicMock()

        captured = io.StringIO()
        sys.stdout = captured
        try:
            with patch("manage_agenda.sources.handled_mail_file", return_value=self.path):
                result = restore_deleted_event_cli(self._args(), "msg-1")
        finally:
            sys.stdout = sys.__stdout__

        self.assertFalse(result)
        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["cancelled_events"], [{"calendar_id": "primary", "event_id": "e1"}])
        self.assertIn("probe", captured.getvalue().lower())

    @patch("manage_agenda.sources._attempt_restore_one_event")
    @patch("manage_agenda.sources.select_api")
    def test_partial_restore_across_two_events(self, mock_select_api, mock_attempt):
        self._write_state(
            {
                "msg-1": {
                    "events": [],
                    "cancelled_events": [
                        {"calendar_id": "primary", "event_id": "e1"},
                        {"calendar_id": "primary", "event_id": "e2"},
                    ],
                    "status": "no_event",
                }
            }
        )
        mock_attempt.side_effect = lambda client, cal, event_id: event_id == "e1"
        mock_select_api.return_value = MagicMock()

        with patch("manage_agenda.sources.handled_mail_file", return_value=self.path):
            result = restore_deleted_event_cli(self._args(), "msg-1")

        self.assertFalse(result)  # not fully successful - one event still failed
        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["events"], [{"calendar_id": "primary", "event_id": "e1"}])
        self.assertEqual(entry["cancelled_events"], [{"calendar_id": "primary", "event_id": "e2"}])


if __name__ == "__main__":
    unittest.main()
