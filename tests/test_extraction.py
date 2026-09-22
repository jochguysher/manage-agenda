import datetime
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import googleapiclient.errors

from manage_agenda.extraction import (
    add_message_to_event_description,
    create_event_dict,
    deterministic_event_id,
    extract_json,
    get_event_from_llm_with_retry,
)
from manage_agenda.sources import Args

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "llm_responses"


def _not_found_error():
    return googleapiclient.errors.HttpError(SimpleNamespace(status=404, reason=""), b"{}")


def _mock_api_dst_with_no_existing_events():
    """A publishPost-mocking api_dst whose pre-insert events().get() existence check always
    reports "not found", so the deterministic-id collision check in
    _publish_event_to_calendar lets every insert through (matching these tests' intent of
    exercising the insert path itself, not the dedup path)."""
    api_dst = MagicMock()
    api_dst.getClient.return_value.events.return_value.get.return_value.execute.side_effect = (
        _not_found_error()
    )
    return api_dst


class TestExtraction(unittest.TestCase):
    def test_extract_json(self):
        text = """Some text

        ```json
{"key": "value"}
        ```

more text"""
        expected_json = '{"key": "value"}'
        self.assertEqual(extract_json(text), expected_json)

    def test_add_message_to_event_description(self):
        event = {"description": "Original description"}
        content = "Email content"
        result = add_message_to_event_description(event, content)
        self.assertIn("Email content", result["description"])

    def test_create_event_dict(self):
        event_dict = create_event_dict()
        self.assertIsInstance(event_dict, dict)
        self.assertIn("summary", event_dict)
        self.assertIn("start", event_dict)

    @patch("manage_agenda.extraction.format_time")
    def test_get_event_from_llm_success(self, mock_format_time):
        """Test get_event_from_llm with successful response."""
        from manage_agenda.extraction import get_event_from_llm

        mock_format_time.return_value = "0h 0m 1.00s"
        mock_model = MagicMock()
        mock_model.generate_text.return_value = (
            '{"summary": "Test Event", "start": {"dateTime": "2024-01-01T10:00:00"}}'
        )

        prompt = "Create an event"
        event, vcal_json, elapsed_time = get_event_from_llm(
            mock_model, prompt, post_id="test_post_123", verbose=False
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["summary"], "Test Event")
        self.assertIsInstance(elapsed_time, float)

    @patch("manage_agenda.extraction.format_time")
    def test_get_event_from_llm_no_response(self, mock_format_time):
        """Test get_event_from_llm when LLM returns no response."""
        import io

        from manage_agenda.extraction import get_event_from_llm

        mock_format_time.return_value = "0h 0m 1.00s"
        mock_model = MagicMock()
        mock_model.generate_text.return_value = ""

        captured_output = io.StringIO()
        sys.stdout = captured_output
        event, vcal_json, elapsed_time = get_event_from_llm(
            mock_model, "test", post_id="test_post_123", verbose=False
        )
        sys.stdout = sys.__stdout__
        output = captured_output.getvalue()

        self.assertIn("Failed to get response", output)

    def test_extract_json_with_braces(self):
        """Test extract_json finds JSON within text."""
        text = 'some text before {"key": "value"} some text after'
        result = extract_json(text)
        self.assertEqual(result, '{"key": "value"}')

    def test_extract_json_already_clean(self):
        """Test extract_json with clean JSON."""
        text = '{"key": "value"}'
        result = extract_json(text)
        self.assertEqual(result, '{"key": "value"}')

    def test_extract_json_multiple_braces(self):
        """Test extract_json with nested JSON and extra closing brace."""
        text = '{"key": {"nested": "value"}}}extra'
        result = extract_json(text)
        self.assertIn('"key"', result)
        self.assertIn('"nested"', result)

    def test_create_llm_prompt(self):
        """Test _create_llm_prompt generates correct prompt."""
        from manage_agenda.extraction import _create_llm_prompt

        event = create_event_dict()
        content = "Meeting about project X on Monday at 3pm"
        ref_date = datetime.datetime(2024, 1, 15, 10, 0, 0)

        prompt = _create_llm_prompt(event, content, ref_date)

        self.assertIn("Meeting about project X", prompt)
        self.assertIn("JSON", prompt)
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 100)

    @patch("manage_agenda.extraction.get_event_from_llm")
    @patch("manage_agenda.extraction.select_api")
    @patch("manage_agenda.extraction.select_calendars")
    @patch("manage_agenda.extraction.write_file")
    @patch("manage_agenda.events._validate_event_dates_interactive")
    def test_process_event_with_llm_and_calendar_multiple_events(
        self,
        mock_interactive_confirmation,
        mock_write_file,
        mock_select_calendars,
        mock_select_api,
        mock_get_event_from_llm,
    ):
        """Test _process_event_with_llm_and_calendar when LLM returns a tuple of events."""
        from manage_agenda.extraction import _process_event_with_llm_and_calendar

        args = Args(
            interactive=False,
            delete=False,
            source="gemini",
            verbose=False,
            destination="",
            text="",
        )

        mock_model = MagicMock()
        event1 = {
            "summary": "Meeting One",
            "start": {"dateTime": "2024-01-01T10:00:00"},
            "end": {"dateTime": "2024-01-01T11:00:00"},
        }
        event2 = {
            "summary": "Meeting Two",
            "start": {"dateTime": "2024-01-02T12:00:00"},
            "end": {"dateTime": "2024-01-02T13:00:00"},
        }

        mock_get_event_from_llm.return_value = ((event1, event2), (event1, event2), 1.0)

        mock_api_dst = _mock_api_dst_with_no_existing_events()
        mock_select_api.return_value = mock_api_dst
        mock_select_calendars.return_value = ["calendar_id"]
        mock_interactive_confirmation.side_effect = lambda args, ev: ev
        mock_api_dst.publishPost.side_effect = ["result1", "result2"]

        events, results = _process_event_with_llm_and_calendar(
            args,
            mock_model,
            content_text="Multiple events text",
            reference_date_time="2024-01-01T00:00:00",
            post_identifier="post_123",
            subject_for_print="Test Subject",
        )

        self.assertIsInstance(events, list)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["summary"], "Meeting One")
        self.assertEqual(events[1]["summary"], "Meeting Two")
        self.assertEqual(results, ["result1", "result2"])

        self.assertEqual(mock_write_file.call_count, 8)
        self.assertEqual(mock_api_dst.publishPost.call_count, 2)

    @patch("manage_agenda.extraction.get_event_from_llm")
    @patch("manage_agenda.extraction.select_api")
    @patch("manage_agenda.extraction.select_calendars")
    @patch("manage_agenda.extraction.write_file")
    @patch("manage_agenda.events._validate_event_dates_interactive")
    def test_one_event_is_published_to_every_selected_calendar(
        self,
        mock_interactive_confirmation,
        mock_write_file,
        mock_select_calendars,
        mock_select_api,
        mock_get_event_from_llm,
    ):
        """One event, two selected calendars: publishPost is called once per calendar, and
        each result is tracked with its own calendar_id/event_id (feeding the deletion-
        detection ledger from an earlier feature - it needs to see both refs, not just one)."""
        from manage_agenda.extraction import _process_event_with_llm_and_calendar

        args = Args(
            interactive=False, delete=False, source="gemini", verbose=False, destination="", text=""
        )
        mock_model = MagicMock()
        event = {
            "summary": "Standup",
            "start": {"dateTime": "2024-01-01T10:00:00"},
            "end": {"dateTime": "2024-01-01T11:00:00"},
        }
        mock_get_event_from_llm.return_value = ((event,), (event,), 1.0)

        mock_api_dst = _mock_api_dst_with_no_existing_events()
        mock_select_api.return_value = mock_api_dst
        mock_select_calendars.return_value = ["cal-1", "cal-2"]
        mock_interactive_confirmation.side_effect = lambda args, ev: ev
        mock_api_dst.publishPost.side_effect = [
            {"success": True, "post_url": "u1", "raw_response": {"id": "e1"}},
            {"success": True, "post_url": "u2", "raw_response": {"id": "e2"}},
        ]

        events, results = _process_event_with_llm_and_calendar(
            args,
            mock_model,
            content_text="Standup invite",
            reference_date_time="2024-01-01T00:00:00",
            post_identifier="post_123",
            subject_for_print="Test Subject",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(mock_api_dst.publishPost.call_count, 2)
        self.assertEqual(len(results), 2)
        self.assertEqual({r["calendar_id"] for r in results}, {"cal-1", "cal-2"})
        # The deterministic id is derived from post_identifier/generation/event_index, not
        # calendar-scoped (Google's uniqueness constraint is per-calendar, verified in Phase
        # 1) - so both calendars get the SAME event_id here, distinguished by calendar_id.
        expected_event_id = deterministic_event_id("post_123", 0, 1)
        self.assertEqual({r["event_id"] for r in results}, {expected_event_id})

    @patch("manage_agenda.extraction.get_event_from_llm")
    @patch("manage_agenda.extraction.select_api")
    @patch("manage_agenda.extraction.select_calendars")
    @patch("manage_agenda.extraction.write_file")
    @patch("manage_agenda.events._validate_event_dates_interactive")
    def test_a_failure_on_any_selected_calendar_fails_the_whole_event(
        self,
        mock_interactive_confirmation,
        mock_write_file,
        mock_select_calendars,
        mock_select_api,
        mock_get_event_from_llm,
    ):
        """If the first calendar succeeds but the second fails, the message must stay pending
        (CalendarError) rather than being marked handled with only a partial write - retrying
        it is safe because the same identity/generation/event_index recompute the same
        deterministic id, so the event already created on the first calendar is found by the
        pre-insert events().get() check and reported as a duplicate rather than re-inserted."""
        from manage_agenda.exceptions import CalendarError
        from manage_agenda.extraction import _process_event_with_llm_and_calendar

        args = Args(
            interactive=False, delete=False, source="gemini", verbose=False, destination="", text=""
        )
        mock_model = MagicMock()
        event = {
            "summary": "Standup",
            "start": {"dateTime": "2024-01-01T10:00:00"},
            "end": {"dateTime": "2024-01-01T11:00:00"},
        }
        mock_get_event_from_llm.return_value = ((event,), (event,), 1.0)

        mock_api_dst = _mock_api_dst_with_no_existing_events()
        mock_select_api.return_value = mock_api_dst
        mock_select_calendars.return_value = ["cal-1", "cal-2"]
        mock_interactive_confirmation.side_effect = lambda args, ev: ev
        mock_api_dst.publishPost.side_effect = [
            {"success": True, "post_url": "u1", "raw_response": {"id": "e1"}},
            {"success": False, "error_message": "quota"},
        ]

        with self.assertRaises(CalendarError):
            _process_event_with_llm_and_calendar(
                args,
                mock_model,
                content_text="Standup invite",
                reference_date_time="2024-01-01T00:00:00",
                post_identifier="post_123",
                subject_for_print="Test Subject",
            )

    @patch("manage_agenda.extraction._extract_event_with_llm_retry")
    @patch("manage_agenda.extraction.select_api")
    @patch("manage_agenda.extraction.select_calendars")
    @patch("manage_agenda.extraction.write_file")
    @patch("manage_agenda.events._validate_event_dates_interactive")
    def test_process_event_with_llm_and_calendar_file_output(
        self,
        mock_interactive_confirmation,
        mock_write_file,
        mock_select_calendars,
        mock_select_api,
        mock_extract_event_with_llm_retry,
    ):
        """Test _process_event_with_llm_and_calendar with file output option."""
        from manage_agenda.extraction import _process_event_with_llm_and_calendar

        args = Args(
            interactive=False,
            delete=False,
            source="gemini",
            verbose=False,
            destination="",
            text="",
            output="file",
        )

        mock_model = MagicMock()
        event = {
            "summary": "Meeting One",
            "start": {"dateTime": "2024-01-01T10:00:00"},
            "end": {"dateTime": "2024-01-01T11:00:00"},
        }

        mock_extract_event_with_llm_retry.return_value = ([event], event, 1.0, True, False, False)
        mock_interactive_confirmation.side_effect = lambda args, ev, *a, **kw: (ev, False)

        events, results = _process_event_with_llm_and_calendar(
            args,
            mock_model,
            content_text="Single event text",
            reference_date_time="2024-01-01T00:00:00",
            post_identifier="post_123",
            subject_for_print="Test Subject",
        )

        self.assertEqual(events[0]["summary"], "Meeting One")
        self.assertEqual(results, ["post_123_1_times.json"])

        mock_select_api.assert_not_called()
        mock_select_calendars.assert_not_called()
        mock_write_file.assert_called()


class TestCalendarBusyAcrossMultipleCalendars(unittest.TestCase):
    """A room-visit slot must avoid conflicts on every calendar the event will be written to,
    not just the first one - otherwise a visit could double-book a calendar select_calendars()
    added later in the list."""

    def test_busy_intervals_are_aggregated_across_all_selected_calendars(self):
        from types import SimpleNamespace

        from manage_agenda.extraction import _calendar_busy

        responses = {
            "cal-1": {
                "items": [
                    {
                        "start": {"dateTime": "2024-01-01T09:00:00+00:00"},
                        "end": {"dateTime": "2024-01-01T10:00:00+00:00"},
                    }
                ]
            },
            "cal-2": {
                "items": [
                    {
                        "start": {"dateTime": "2024-01-01T14:00:00+00:00"},
                        "end": {"dateTime": "2024-01-01T15:00:00+00:00"},
                    }
                ]
            },
        }

        def list_events(**kwargs):
            response = MagicMock()
            response.execute.return_value = responses[kwargs["calendarId"]]
            return response

        api_dst = MagicMock()
        api_dst.getClient.return_value.events.return_value.list.side_effect = list_events
        constraints = SimpleNamespace(horizon_days=7)

        busy = _calendar_busy(api_dst, ["cal-1", "cal-2"], constraints)

        self.assertEqual(len(busy), 2)

    def test_a_failing_calendar_does_not_prevent_reading_the_others(self):
        from types import SimpleNamespace

        from manage_agenda.extraction import _calendar_busy

        def list_events(**kwargs):
            if kwargs["calendarId"] == "cal-broken":
                raise RuntimeError("boom")
            response = MagicMock()
            response.execute.return_value = {
                "items": [
                    {
                        "start": {"dateTime": "2024-01-01T09:00:00+00:00"},
                        "end": {"dateTime": "2024-01-01T10:00:00+00:00"},
                    }
                ]
            }
            return response

        api_dst = MagicMock()
        api_dst.getClient.return_value.events.return_value.list.side_effect = list_events
        constraints = SimpleNamespace(horizon_days=7)

        busy = _calendar_busy(api_dst, ["cal-broken", "cal-ok"], constraints)

        self.assertEqual(len(busy), 1)


class TestMultiEventRetryPreservesDistinctDates(unittest.TestCase):
    """Regression test for the "all extracted events share one date" bug.

    get_event_from_llm_with_retry used to always make a second, independent
    LLM call to "confirm" a first successful extraction (event_old started
    empty, so the first result was always judged unstable), then
    unconditionally REPLACE the first result with whatever that second call
    returned - no merge, no validation. A correct multi-event extraction from
    call 1 was silently discarded if call 2 (same prompt, fresh
    non-deterministic generation) returned something worse, e.g. a single
    collapsed event.

    The fix: accept a successful extraction immediately, with no redundant
    confirmation call.
    """

    def setUp(self):
        self.multi_event_response = (FIXTURES_DIR / "multiple_events.txt").read_text(
            encoding="utf-8"
        )
        patcher = patch("manage_agenda.extraction.write_file")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _model_with_responses(self, responses):
        model = MagicMock()
        model.model_name = "fixture"
        model.generate_text.side_effect = responses
        return model

    def test_successful_multi_event_extraction_is_not_overwritten(self):
        """A single-event response queued after the good multi-event one must
        never be reached: the first, correct extraction is final."""
        single_event_would_collapse_it = (
            '{"summary": "", "start": {"dateTime": "2030-02-10", "timeZone": ""},'
            ' "end": {"dateTime": "", "timeZone": ""}}'
        )
        model = self._model_with_responses(
            [self.multi_event_response, single_event_would_collapse_it]
        )
        args = Args(interactive=False, verbose=False)

        event, _, _ = get_event_from_llm_with_retry(model, "prompt", "post_multi", args)

        self.assertEqual(
            model.generate_text.call_count,
            1,
            "A redundant confirmation call was made after a successful extraction.",
        )
        self.assertIsInstance(event, (list, tuple))
        self.assertEqual(len(event), 2)
        self.assertEqual(
            [item["start"]["dateTime"] for item in event],
            ["2030-02-10", "2030-03-11"],
        )
