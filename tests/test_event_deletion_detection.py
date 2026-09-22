import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from manage_agenda.extraction import _check_events_exist, event_identity
from manage_agenda.sources import (
    Args,
    _extract_event_refs,
    load_handled_mail_ids,
    load_handled_mail_state,
    reconcile_handled_events,
    remember_handled_mail,
    unseen_messages,
)


class Http404(Exception):
    def __init__(self, status=404):
        self.resp = SimpleNamespace(status=status)


def _fake_batch_api(responses):
    """responses: {(calendar_id, event_id): (response_dict_or_None, exception_or_None)}"""
    client = MagicMock()

    def get(calendarId, eventId):
        request = MagicMock()
        request.result = responses[(calendarId, eventId)]
        return request

    client.events.return_value.get.side_effect = get

    class FakeBatch:
        def __init__(self):
            self.calls = []

        def add(self, request, callback=None):
            self.calls.append((request, callback))

        def execute(self):
            for request, callback in self.calls:
                response, exception = request.result
                callback(None, response, exception)

    client.new_batch_http_request.side_effect = FakeBatch
    api = MagicMock()
    api.getClient.return_value = client
    return api, client


class TestCheckEventsExist(unittest.TestCase):
    def test_present_cancelled_and_deleted_are_told_apart(self):
        api, client = _fake_batch_api(
            {
                ("cal-1", "ev-present"): ({"status": "confirmed"}, None),
                ("cal-1", "ev-cancelled"): ({"status": "cancelled"}, None),
                ("cal-1", "ev-deleted"): (None, Http404()),
            }
        )
        triples = [
            ("msg-1", "cal-1", "ev-present"),
            ("msg-2", "cal-1", "ev-cancelled"),
            ("msg-3", "cal-1", "ev-deleted"),
        ]

        result = _check_events_exist(api, triples)

        self.assertTrue(result[("msg-1", "cal-1", "ev-present")])
        self.assertFalse(result[("msg-2", "cal-1", "ev-cancelled")])
        self.assertFalse(result[("msg-3", "cal-1", "ev-deleted")])
        client.new_batch_http_request.assert_called_once()

    def test_unknown_error_keeps_the_event_treated_as_present(self):
        api, _client = _fake_batch_api({("cal-1", "ev-x"): (None, Http404(status=500))})
        result = _check_events_exist(api, [("msg-1", "cal-1", "ev-x")])
        self.assertTrue(result[("msg-1", "cal-1", "ev-x")])

    def test_more_than_fifty_events_are_chunked_into_several_batches(self):
        responses = {("cal-1", f"ev-{i}"): ({"status": "confirmed"}, None) for i in range(120)}
        api, client = _fake_batch_api(responses)
        triples = [(f"msg-{i}", "cal-1", f"ev-{i}") for i in range(120)]

        result = _check_events_exist(api, triples)

        self.assertEqual(len(result), 120)
        self.assertEqual(client.new_batch_http_request.call_count, 3)

    def test_empty_input_makes_no_api_call(self):
        api, client = _fake_batch_api({})
        self.assertEqual(_check_events_exist(api, []), {})
        client.new_batch_http_request.assert_not_called()


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
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def _write_state(self, messages):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"messages": messages}), encoding="utf-8")

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
        api, _client = _fake_batch_api(
            {
                ("cal-1", "ev-gone"): (None, Http404()),
                ("cal-1", "ev-present"): ({"status": "confirmed"}, None),
            }
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path)

        self.assertEqual(still_handled, {"msg-present", "msg-legacy"})
        remaining_state = load_handled_mail_state(self.path)
        self.assertNotIn("msg-gone", remaining_state)
        self.assertIn("msg-present", remaining_state)
        self.assertIn("msg-legacy", remaining_state)

    def test_no_calendar_connection_keeps_everything_handled(self):
        self._write_state(
            {"msg-1": {"events": [{"calendar_id": "cal-1", "event_id": "ev-1"}], "status": "created"}}
        )
        args = Args(interactive=False)
        args.calendar_api = None

        still_handled = reconcile_handled_events(args, path=self.path)

        self.assertEqual(still_handled, {"msg-1"})
        self.assertIn("msg-1", load_handled_mail_state(self.path))

    def test_released_message_is_offered_again_by_unseen_messages(self):
        from email.message import EmailMessage

        self._write_state(
            {"<gone@x>": {"events": [{"calendar_id": "cal-1", "event_id": "ev-gone"}], "status": "created"}}
        )
        api, _client = _fake_batch_api({("cal-1", "ev-gone"): (None, Http404())})
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path)

        message = EmailMessage()
        message["Message-ID"] = "<gone@x>"
        fresh, skipped = unseen_messages([(1, message)], handled=still_handled)

        self.assertEqual(skipped, 0)
        self.assertEqual([item[0] for item in fresh], [1])


if __name__ == "__main__":
    unittest.main()
