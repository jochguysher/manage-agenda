import unittest
from unittest.mock import MagicMock

from manage_agenda.extraction import (
    _publish_event_to_calendar,
    event_identity,
    find_existing_event,
)


EVENT = {
    "summary": "Dentiste",
    "start": {"dateTime": "2026-09-22T15:00:00-04:00", "timeZone": "America/Toronto"},
    "end": {"dateTime": "2026-09-22T16:00:00-04:00", "timeZone": "America/Toronto"},
}


class TestEventIdentity(unittest.TestCase):
    def test_same_slot_from_two_messages_shares_the_slot_key(self):
        slot_a, source_a = event_identity(EVENT, "msg-1")
        slot_b, source_b = event_identity(EVENT, "msg-2")
        self.assertEqual(slot_a, slot_b)
        self.assertNotEqual(source_a, source_b)

    def test_timezone_formats_match(self):
        other = {
            "summary": "  dentiste ",
            "start": {"dateTime": "2026-09-22T19:00:00Z"},
        }
        self.assertEqual(event_identity(EVENT, "msg-1")[0], event_identity(other, "msg-9")[0])


class TestPublishSkipsDuplicates(unittest.TestCase):
    def _api(self, list_response):
        api = MagicMock()
        api.getClient.return_value.events.return_value.list.return_value.execute.return_value = (
            list_response
        )
        return api

    def test_existing_extended_property_skips_insert(self):
        api = self._api({"items": [{"id": "e1", "htmlLink": "https://calendar.example/e1"}]})
        published, result = _publish_event_to_calendar(api, dict(EVENT), "primary", source_id="msg-1")
        self.assertTrue(published)
        self.assertTrue(result["duplicate"])
        api.publishPost.assert_not_called()

    def test_same_summary_and_start_in_the_window_skips_insert(self):
        existing = {
            "id": "e2",
            "summary": "Dentiste",
            "htmlLink": "https://calendar.example/e2",
            "start": {"dateTime": "2026-09-22T19:00:00Z"},
        }

        def list_events(**kwargs):
            response = MagicMock()
            if "privateExtendedProperty" in kwargs:
                response.execute.return_value = {"items": []}
            else:
                response.execute.return_value = {"items": [existing]}
            return response

        api = MagicMock()
        api.getClient.return_value.events.return_value.list.side_effect = list_events
        published, result = _publish_event_to_calendar(api, dict(EVENT), "primary", source_id="msg-2")
        self.assertTrue(result["duplicate"])
        api.publishPost.assert_not_called()
        self.assertTrue(published)

    def test_new_event_is_inserted(self):
        api = self._api({"items": []})
        api.publishPost.return_value = {"success": True, "post_url": "https://calendar.example/new"}
        published, result = _publish_event_to_calendar(api, dict(EVENT), "primary", source_id="msg-3")
        self.assertTrue(published)
        self.assertFalse(result.get("duplicate"))
        api.publishPost.assert_called_once()


class TestRecreateAfterManualDeletion(unittest.TestCase):
    """A local dedup cache used to survive a manual deletion and silently no-op the recreate.

    find_existing_event must always ask Calendar instead of trusting a cache from an earlier
    call, otherwise "recreate a deleted event" looks like "duplicate, skip" forever.
    """

    def test_second_publish_after_the_event_disappears_calls_the_api_again(self):
        api = self._api({"items": []})
        api.publishPost.return_value = {
            "success": True,
            "post_url": "https://calendar.example/first",
            "raw_response": {"id": "e-first", "htmlLink": "https://calendar.example/first"},
        }
        published, result = _publish_event_to_calendar(api, dict(EVENT), "primary", source_id="msg-1")
        self.assertTrue(published)
        self.assertFalse(result.get("duplicate"))
        self.assertEqual(api.publishPost.call_count, 1)

        # The event was deleted from Calendar: every lookup now comes back empty.
        api.getClient.return_value.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }
        api.publishPost.return_value = {
            "success": True,
            "post_url": "https://calendar.example/second",
            "raw_response": {"id": "e-second", "htmlLink": "https://calendar.example/second"},
        }
        published_again, result_again = _publish_event_to_calendar(
            api, dict(EVENT), "primary", source_id="msg-1"
        )
        self.assertTrue(published_again)
        self.assertFalse(result_again.get("duplicate"))
        self.assertEqual(api.publishPost.call_count, 2)

    def _api(self, list_response):
        api = MagicMock()
        api.getClient.return_value.events.return_value.list.return_value.execute.return_value = (
            list_response
        )
        return api
