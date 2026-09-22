import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import googleapiclient.errors

from manage_agenda.extraction import _load_sync_tokens, event_identity, sync_calendar_changes
from manage_agenda.sources import (
    Args,
    _extract_event_refs,
    load_handled_mail_ids,
    load_handled_mail_state,
    reconcile_handled_events,
    remember_handled_mail,
    unseen_messages,
)


def http_error(status):
    return googleapiclient.errors.HttpError(SimpleNamespace(status=status, reason=""), b"{}")


class ScriptedCalendarClient:
    """Each events().list(...).execute() call pops the next scripted response or exception."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def events(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._responses.pop(0)
        request = MagicMock()
        if isinstance(outcome, BaseException):
            request.execute.side_effect = outcome
        else:
            request.execute.return_value = outcome
        return request


def _api(responses):
    client = ScriptedCalendarClient(responses)
    api = MagicMock()
    api.getClient.return_value = client
    return api, client


class TestSyncCalendarChanges(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_first_call_seeds_a_token_and_reports_no_deletions(self):
        api, client = _api([{"items": [{"id": "e1", "status": "confirmed"}], "nextSyncToken": "tok-1"}])

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(result, set())
        self.assertEqual(_load_sync_tokens(self.path), {"cal-1": "tok-1"})
        self.assertNotIn("syncToken", client.calls[0])

    def test_pagination_is_followed_until_the_last_page(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, client = _api(
            [
                {"items": [{"id": "e1", "status": "confirmed"}], "nextPageToken": "page-2"},
                {"items": [{"id": "e2", "status": "cancelled"}], "nextSyncToken": "tok-2"},
            ]
        )

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1]["pageToken"], "page-2")
        self.assertEqual(result, {"e2"})
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-2")

    def test_existing_token_is_sent_and_cancelled_ids_are_reported(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, client = _api(
            [
                {
                    "items": [
                        {"id": "e1", "status": "confirmed"},
                        {"id": "e2", "status": "cancelled"},
                    ],
                    "nextSyncToken": "tok-new",
                }
            ]
        )

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(client.calls[0]["syncToken"], "tok-old")
        self.assertEqual(result, {"e2"})
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-new")

    def test_expired_token_is_reseeded_without_reporting_deletions(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, client = _api(
            [
                http_error(410),
                {"items": [{"id": "e1", "status": "confirmed"}], "nextSyncToken": "tok-fresh"},
            ]
        )

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(result, set())
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-fresh")
        self.assertNotIn("syncToken", client.calls[1])

    def test_other_api_error_is_conservative_and_keeps_the_old_token(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, _client = _api([http_error(500)])

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(result, set())
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-old")


class TestEventIdentityIsCalendarScoped(unittest.TestCase):
    EVENT = {
        "summary": "Dentiste",
        "start": {"dateTime": "2026-09-22T15:00:00-04:00", "timeZone": "America/Toronto"},
        "end": {"dateTime": "2026-09-22T16:00:00-04:00", "timeZone": "America/Toronto"},
    }

    def test_same_event_on_two_calendars_gets_different_keys(self):
        slot_a, _ = event_identity(self.EVENT, "msg-1", calendar_id="cal-a")
        slot_b, _ = event_identity(self.EVENT, "msg-1", calendar_id="cal-b")
        self.assertNotEqual(slot_a, slot_b)


class TestExtractEventRefs(unittest.TestCase):
    def test_pulls_calendar_and_event_id_from_publish_results(self):
        calendar_result = [
            {"success": True, "calendar_id": "primary", "event_id": "abc"},
            {"success": True, "duplicate": True, "calendar_id": "primary", "event_id": ""},
            "not-a-dict",
        ]
        self.assertEqual(
            _extract_event_refs(calendar_result),
            [{"calendar_id": "primary", "event_id": "abc"}],
        )

    def test_falls_back_to_raw_response_id(self):
        calendar_result = [
            {"success": True, "calendar_id": "primary", "raw_response": {"id": "xyz"}},
        ]
        self.assertEqual(
            _extract_event_refs(calendar_result),
            [{"calendar_id": "primary", "event_id": "xyz"}],
        )

    def test_none_gives_empty_list(self):
        self.assertEqual(_extract_event_refs(None), [])


class TestHandledMailStateMigration(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_legacy_id_only_file_is_read_as_events_free_entries(self):
        self.path.write_text(json.dumps({"ids": ["old-1", "old-2"]}), encoding="utf-8")

        state = load_handled_mail_state(self.path)

        self.assertEqual(state["old-1"], {"events": [], "status": "legacy"})
        self.assertEqual(load_handled_mail_ids(self.path), {"old-1", "old-2"})

    def test_legacy_entries_are_still_skipped_by_unseen_messages(self):
        from email.message import EmailMessage

        self.path.write_text(json.dumps({"ids": ["legacy@x"]}), encoding="utf-8")
        message = EmailMessage()
        message["Message-ID"] = "<legacy@x>"

        fresh, skipped = unseen_messages([(1, message)], path=self.path)

        self.assertEqual(skipped, 1)
        self.assertEqual(fresh, [])

    def test_remember_handled_mail_without_events_is_legacy_equivalent(self):
        remember_handled_mail("msg-1", path=self.path)
        state = load_handled_mail_state(self.path)
        self.assertEqual(state["msg-1"], {"events": [], "status": "no_event"})

    def test_remember_handled_mail_with_events_records_them(self):
        remember_handled_mail(
            "msg-1", path=self.path, events=[{"calendar_id": "primary", "event_id": "e1"}]
        )
        state = load_handled_mail_state(self.path)
        self.assertEqual(
            state["msg-1"],
            {"events": [{"calendar_id": "primary", "event_id": "e1"}], "status": "created"},
        )


class TestReconcileHandledEvents(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.sync_path = Path("/tmp") / (self.id().replace(".", "_") + "_sync.json")
        self.path.unlink(missing_ok=True)
        self.sync_path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))
        self.addCleanup(lambda: self.sync_path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.sync_path) + ".tmp").unlink(missing_ok=True))

    def _write_state(self, messages):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"messages": messages}), encoding="utf-8")

    def _seed_sync_token(self, calendar_id, token):
        self.sync_path.parent.mkdir(parents=True, exist_ok=True)
        self.sync_path.write_text(json.dumps({"tokens": {calendar_id: token}}), encoding="utf-8")

    def test_message_with_deleted_event_is_released_for_reprocessing(self):
        self._write_state(
            {
                "msg-gone": {
                    "events": [{"calendar_id": "cal-1", "event_id": "ev-gone"}],
                    "status": "created",
                },
                "msg-present": {
                    "events": [{"calendar_id": "cal-1", "event_id": "ev-present"}],
                    "status": "created",
                },
                "msg-legacy": {"events": [], "status": "legacy"},
            }
        )
        self._seed_sync_token("cal-1", "tok-old")
        api, _client = _api(
            [
                {
                    "items": [
                        {"id": "ev-gone", "status": "cancelled"},
                        {"id": "ev-present", "status": "confirmed"},
                    ],
                    "nextSyncToken": "tok-new",
                }
            ]
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(still_handled, {"msg-present", "msg-legacy"})
        remaining_state = load_handled_mail_state(self.path)
        self.assertNotIn("msg-gone", remaining_state)
        self.assertIn("msg-present", remaining_state)
        self.assertIn("msg-legacy", remaining_state)

    def test_one_sync_call_per_calendar_regardless_of_event_count(self):
        self._write_state(
            {
                f"msg-{i}": {
                    "events": [{"calendar_id": "cal-1", "event_id": f"ev-{i}"}],
                    "status": "created",
                }
                for i in range(10)
            }
        )
        self._seed_sync_token("cal-1", "tok-old")
        api, client = _api([{"items": [], "nextSyncToken": "tok-new"}])
        args = Args(interactive=False)
        args.calendar_api = api

        reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(len(client.calls), 1)

    def test_no_calendar_connection_keeps_everything_handled(self):
        self._write_state(
            {"msg-1": {"events": [{"calendar_id": "cal-1", "event_id": "ev-1"}], "status": "created"}}
        )
        args = Args(interactive=False)
        args.calendar_api = None

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(still_handled, {"msg-1"})
        self.assertIn("msg-1", load_handled_mail_state(self.path))

    def test_released_message_is_offered_again_by_unseen_messages(self):
        from email.message import EmailMessage

        self._write_state(
            {"<gone@x>": {"events": [{"calendar_id": "cal-1", "event_id": "ev-gone"}], "status": "created"}}
        )
        self._seed_sync_token("cal-1", "tok-old")
        api, _client = _api(
            [{"items": [{"id": "ev-gone", "status": "cancelled"}], "nextSyncToken": "tok-new"}]
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        message = EmailMessage()
        message["Message-ID"] = "<gone@x>"
        fresh, skipped = unseen_messages([(1, message)], handled=still_handled)

        self.assertEqual(skipped, 0)
        self.assertEqual([item[0] for item in fresh], [1])

    def test_first_ever_run_bootstraps_and_releases_nothing(self):
        self._write_state(
            {"msg-1": {"events": [{"calendar_id": "cal-1", "event_id": "ev-1"}], "status": "created"}}
        )
        api, client = _api([{"items": [], "nextSyncToken": "tok-first"}])
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(still_handled, {"msg-1"})
        self.assertNotIn("syncToken", client.calls[0])
        self.assertEqual(_load_sync_tokens(self.sync_path)["cal-1"], "tok-first")


if __name__ == "__main__":
    unittest.main()
