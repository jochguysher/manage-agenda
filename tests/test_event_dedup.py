import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import googleapiclient.errors

from manage_agenda.extraction import _publish_event_to_calendar, deterministic_event_id


def http_error(status):
    return googleapiclient.errors.HttpError(SimpleNamespace(status=status, reason=""), b"{}")


EVENT = {
    "summary": "Dentiste",
    "start": {"dateTime": "2026-09-22T15:00:00-04:00", "timeZone": "America/Toronto"},
    "end": {"dateTime": "2026-09-22T16:00:00-04:00", "timeZone": "America/Toronto"},
}


class TestDeterministicEventId(unittest.TestCase):
    def test_same_inputs_give_the_same_id(self):
        self.assertEqual(
            deterministic_event_id("msg-1", 0, 1), deterministic_event_id("msg-1", 0, 1)
        )

    def test_different_identity_gives_a_different_id(self):
        self.assertNotEqual(
            deterministic_event_id("msg-1", 0, 1), deterministic_event_id("msg-2", 0, 1)
        )

    def test_different_generation_gives_a_different_id(self):
        self.assertNotEqual(
            deterministic_event_id("msg-1", 0, 1), deterministic_event_id("msg-1", 1, 1)
        )

    def test_different_event_index_gives_a_different_id(self):
        self.assertNotEqual(
            deterministic_event_id("msg-1", 0, 1), deterministic_event_id("msg-1", 0, 2)
        )

    def test_charset_and_length_match_googles_base32hex_constraint(self):
        # https://developers.google.com/workspace/calendar/api/v3/reference/events#id -
        # lowercase a-v and 0-9 only, length 5-1024. Verified against the official docs
        # during Phase 1, not assumed (see docs/investigation-limite1.md).
        event_id = deterministic_event_id("msg-1", 0, 1)
        self.assertTrue(5 <= len(event_id) <= 1024)
        self.assertTrue(set(event_id) <= set("0123456789abcdefghijklmnopqrstuv"))


def _api_with_get(get_responses):
    """get_responses: {(calendar_id, event_id): outcome} where outcome is a dict (the Event
    response) or an exception instance to raise."""
    client = MagicMock()

    def get(calendarId, eventId):
        request = MagicMock()
        outcome = get_responses.get((calendarId, eventId))
        if isinstance(outcome, BaseException):
            request.execute.side_effect = outcome
        else:
            request.execute.return_value = outcome
        return request

    client.events.return_value.get.side_effect = get
    api = MagicMock()
    api.getClient.return_value = client
    return api, client


class TestPublishWithDeterministicId(unittest.TestCase):
    def test_not_found_inserts_with_the_deterministic_id(self):
        event_id = deterministic_event_id("msg-1", 0, 1)
        api, client = _api_with_get({("primary", event_id): http_error(404)})
        api.publishPost.return_value = {"success": True, "post_url": "https://calendar.example/e1"}

        published, result = _publish_event_to_calendar(
            api, dict(EVENT), "primary", source_id="msg-1", generation=0, event_index=1
        )

        self.assertTrue(published)
        self.assertFalse(result.get("duplicate"))
        self.assertEqual(result["event_id"], event_id)
        api.publishPost.assert_called_once()
        inserted_body = api.publishPost.call_args.kwargs["post"]["event"]
        self.assertEqual(inserted_body["id"], event_id)
        self.assertEqual(inserted_body["extendedProperties"]["private"]["origin"], "manage-agenda")
        self.assertEqual(inserted_body["extendedProperties"]["private"]["sourceMailId"], "msg-1")
        self.assertEqual(inserted_body["extendedProperties"]["private"]["generation"], "0")
        self.assertEqual(inserted_body["extendedProperties"]["private"]["eventIndex"], "1")

    def test_live_existing_event_is_reported_as_duplicate_without_inserting(self):
        event_id = deterministic_event_id("msg-1", 0, 1)
        api, client = _api_with_get(
            {("primary", event_id): {"id": event_id, "status": "confirmed", "htmlLink": "https://x"}}
        )

        published, result = _publish_event_to_calendar(
            api, dict(EVENT), "primary", source_id="msg-1", generation=0, event_index=1
        )

        self.assertTrue(published)
        self.assertTrue(result["duplicate"])
        self.assertEqual(result["event_id"], event_id)
        api.publishPost.assert_not_called()

    def test_cancelled_existing_event_is_a_collision_not_a_duplicate(self):
        """A cancelled event at the id we're about to use must never be silently treated as
        "already there, nothing to do" - see docs/investigation-limite1.md correction 1: no
        409 is guaranteed on insert, so this is the only place a collision can be caught."""
        event_id = deterministic_event_id("msg-1", 0, 1)
        api, client = _api_with_get({("primary", event_id): {"id": event_id, "status": "cancelled"}})

        published, result = _publish_event_to_calendar(
            api, dict(EVENT), "primary", source_id="msg-1", generation=0, event_index=1
        )

        self.assertFalse(published)
        self.assertFalse(result.get("success"))
        self.assertFalse(result.get("duplicate"))
        api.publishPost.assert_not_called()

    def test_ambiguous_existence_check_error_does_not_insert(self):
        """Inserting without a confirmed "does not exist" answer could create a duplicate the
        tool would never reconcile with the id it expected - conservative by design."""
        event_id = deterministic_event_id("msg-1", 0, 1)
        api, client = _api_with_get({("primary", event_id): http_error(500)})

        published, result = _publish_event_to_calendar(
            api, dict(EVENT), "primary", source_id="msg-1", generation=0, event_index=1
        )

        self.assertFalse(published)
        api.publishPost.assert_not_called()

    def test_same_id_is_used_across_different_calendars(self):
        """Google's id-uniqueness constraint is per-calendar, not global (verified in Phase
        1), so the same deterministic id is reused as-is on every calendar an event is
        published to - no calendar-scoping needed."""
        event_id = deterministic_event_id("msg-1", 0, 1)
        api, client = _api_with_get(
            {
                ("cal-a", event_id): http_error(404),
                ("cal-b", event_id): http_error(404),
            }
        )
        api.publishPost.return_value = {"success": True}

        _, result_a = _publish_event_to_calendar(
            api, dict(EVENT), "cal-a", source_id="msg-1", generation=0, event_index=1
        )
        _, result_b = _publish_event_to_calendar(
            api, dict(EVENT), "cal-b", source_id="msg-1", generation=0, event_index=1
        )

        self.assertEqual(result_a["event_id"], event_id)
        self.assertEqual(result_b["event_id"], event_id)

    def test_no_source_id_falls_back_to_a_plain_insert(self):
        """No stable identity available at all (should not happen via the normal CLI flow,
        which always has at least a per-run post id) - fall back to Calendar assigning the id,
        rather than crashing."""
        api = MagicMock()
        api.getClient.return_value.events.return_value.get.side_effect = AssertionError(
            "should not be called when there is no source_id to check"
        )
        api.publishPost.return_value = {
            "success": True,
            "raw_response": {"id": "google-assigned-id"},
        }

        event = dict(EVENT)
        published, result = _publish_event_to_calendar(api, event, "primary", source_id="")

        self.assertTrue(published)
        self.assertEqual(result["event_id"], "google-assigned-id")
        api.getClient.return_value.events.return_value.get.assert_not_called()
        # No sourceMailId to key a ledger reconstruction by, but origin alone still marks
        # the event as manage-agenda's for events.list(privateExtendedProperty=
        # "origin=manage-agenda") to find it.
        self.assertEqual(event["extendedProperties"]["private"]["origin"], "manage-agenda")
        self.assertNotIn("sourceMailId", event["extendedProperties"]["private"])


class TestRecreateAfterManualDeletion(unittest.TestCase):
    """A local cache, or a collision hidden behind the same generation, used to survive a
    manual deletion and silently no-op the recreate. A fresh generation (the requeue
    resolution step's job, not tested here) is what makes a genuine recreate succeed."""

    def test_republishing_under_the_same_generation_after_deletion_is_a_collision(self):
        event_id = deterministic_event_id("msg-1", 0, 1)
        api, client = _api_with_get({("primary", event_id): {"id": event_id, "status": "cancelled"}})

        published, result = _publish_event_to_calendar(
            api, dict(EVENT), "primary", source_id="msg-1", generation=0, event_index=1
        )

        self.assertFalse(published)
        api.publishPost.assert_not_called()

    def test_republishing_under_a_new_generation_succeeds(self):
        old_id = deterministic_event_id("msg-1", 0, 1)
        new_id = deterministic_event_id("msg-1", 1, 1)
        self.assertNotEqual(old_id, new_id)
        api, client = _api_with_get({("primary", new_id): http_error(404)})
        api.publishPost.return_value = {"success": True}

        published, result = _publish_event_to_calendar(
            api, dict(EVENT), "primary", source_id="msg-1", generation=1, event_index=1
        )

        self.assertTrue(published)
        self.assertEqual(result["event_id"], new_id)
        api.publishPost.assert_called_once()


if __name__ == "__main__":
    unittest.main()
