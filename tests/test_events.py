import datetime
import unittest
from unittest.mock import MagicMock, patch

from manage_agenda.events import adjust_event_times, update_event_status_cli
from manage_agenda.sources import Args


class TestEvents(unittest.TestCase):
    def test_adjust_event_times_both_present(self):
        # A naive dateTime (no explicit timeZone) is localized via Config.DEFAULT_TIMEZONE,
        # pinned to "Europe/Berlin" for the whole suite by conftest.py (set in the
        # environment before manage_agenda.config is ever imported - see its comment) rather
        # than patched per test here, so these expected values assume that pin, not whatever
        # DEFAULT_TIMEZONE the host's real .env happens to set.
        event = {
            "start": {"dateTime": "2024-01-01T10:00:00"},
            "end": {"dateTime": "2024-01-01T11:00:00"},
        }
        result = adjust_event_times(event)
        self.assertEqual(result["start"]["dateTime"], "2024-01-01T09:00:00+00:00")
        self.assertEqual(result["end"]["dateTime"], "2024-01-01T10:00:00+00:00")
        self.assertEqual(result["start"]["timeZone"], "UTC")
        self.assertEqual(result["end"]["timeZone"], "UTC")

    def test_adjust_event_times_start_missing(self):
        event = {"end": {"dateTime": "2024-01-01T11:00:00"}}
        result = adjust_event_times(event)
        self.assertEqual(result["start"]["dateTime"], "2024-01-01T09:30:00+00:00")
        self.assertEqual(result["start"]["timeZone"], "UTC")

    def test_adjust_event_times_end_missing(self):
        event = {"start": {"dateTime": "2024-01-01T10:00:00"}}
        result = adjust_event_times(event)
        self.assertEqual(result["end"]["dateTime"], "2024-01-01T09:30:00+00:00")
        self.assertEqual(result["end"]["timeZone"], "UTC")

    def test_adjust_event_times_timezones(self):
        event = {
            "start": {"dateTime": "2024-01-01T10:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2024-01-01T11:00:00", "timeZone": "UTC"},
        }
        result = adjust_event_times(event)
        self.assertEqual(result["start"]["timeZone"], "UTC")
        self.assertEqual(result["end"]["timeZone"], "UTC")

    @patch("manage_agenda.events.select_events_by_user_input", return_value=[])
    @patch("manage_agenda.events.display_posts")
    @patch("manage_agenda.events.select_calendar", return_value="calendar-id")
    @patch("manage_agenda.events.connections.select_api")
    def test_update_event_status_uses_calendar_posts(
        self,
        mock_select_api,
        mock_select_calendar,
        mock_display_posts,
        mock_select_events,
    ):
        args = Args(interactive=False, output="", text="")
        api_cal = MagicMock()
        events = [{"summary": "Event", "transparency": "opaque"}]
        api_cal.getPosts.return_value = events
        api_cal.getPostTitle.return_value = "Event"
        mock_select_api.return_value = api_cal

        update_event_status_cli(args)

        api_cal.setActive.assert_called_once_with("calendar-id")
        api_cal.setPosts.assert_called_once_with(
            max_results=None, event_types="default", show_active=False
        )
        mock_display_posts.assert_called_once()
        assert mock_display_posts.call_args.args[:2] == (api_cal, events)
        assert mock_display_posts.call_args.kwargs["limit"] == 20
        assert mock_display_posts.call_args.kwargs["title"] == "Upcoming events (up to 20):"
        mock_select_events.assert_called_once_with(api_cal, events, "update")

    def test_adjust_event_times_end_before_start(self):
        """Test adjust_event_times when end is before start."""
        event = {
            "start": {"dateTime": "2024-01-01T11:00:00"},
            "end": {"dateTime": "2024-01-01T10:00:00"},
        }
        result = adjust_event_times(event)

        # End should be adjusted to be 30 minutes after start
        start_dt = datetime.datetime.fromisoformat(result["start"]["dateTime"])
        end_dt = datetime.datetime.fromisoformat(result["end"]["dateTime"])
        self.assertGreater(end_dt, start_dt)

    def test_adjust_event_times_invalid_timezone(self):
        """Test adjust_event_times with invalid timezone."""
        event = {
            "start": {"dateTime": "2024-01-01T10:00:00", "timeZone": "Invalid/Timezone"},
            "end": {"dateTime": "2024-01-01T11:00:00"},
        }
        result = adjust_event_times(event)

        # Should fallback to default timezone
        self.assertEqual(result["start"]["timeZone"], "UTC")

    @patch("manage_agenda.events.connections.select_api")
    @patch("manage_agenda.events.select_calendar", return_value="calendar1")
    @patch("builtins.input", side_effect=["meeting", "0", "calendar2"])
    def test_copy_events_cli_basic(self, mock_input, mock_select_cal, mock_select_api):
        """Test copy_events_cli basic flow."""
        from manage_agenda.events import copy_events_cli

        args = Args(
            interactive=True, source=None, destination=None, text=None, delete=False, verbose=False
        )

        mock_api = MagicMock()
        mock_client = MagicMock()
        mock_api.getClient.return_value = mock_client

        mock_events = {
            "items": [
                {
                    "summary": "Team meeting",
                    "description": "Weekly sync",
                    "start": {"dateTime": "2024-01-15T10:00:00"},
                    "end": {"dateTime": "2024-01-15T11:00:00"},
                }
            ]
        }
        mock_client.events().list().execute.return_value = mock_events
        mock_api.getPostTitle.return_value = "Team meeting"
        mock_api.getPosts.return_value = mock_events["items"]
        mock_select_api.return_value = mock_api

        copy_events_cli(args)

        mock_client.events().insert.assert_called()

    @patch("manage_agenda.events.connections.select_api")
    @patch("manage_agenda.events.select_calendar", return_value="calendar1")
    @patch("builtins.input", side_effect=["", "0"])
    def test_delete_events_cli_basic(self, mock_input, mock_select_cal, mock_select_api):
        """Test delete_events_cli basic flow."""
        from manage_agenda.events import delete_events_cli

        args = Args(
            interactive=True, source=None, destination=None, text=None, delete=False, verbose=False
        )

        mock_api = MagicMock()
        mock_client = MagicMock()
        mock_api.getClient.return_value = mock_client

        mock_events = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Old meeting",
                    "start": {"dateTime": "2024-01-15T10:00:00"},
                    "end": {"dateTime": "2024-01-15T11:00:00"},
                }
            ]
        }
        mock_client.events().list().execute.return_value = mock_events
        mock_api.getPostTitle.return_value = "Old meeting"
        mock_api.getPosts.return_value = mock_events["items"]
        mock_select_api.return_value = mock_api

        delete_events_cli(args)

        mock_client.events().delete.assert_called()

    @patch("manage_agenda.events.connections.select_api")
    @patch("manage_agenda.events.select_calendar", return_value="calendar1")
    @patch("builtins.input", side_effect=["", "0", "calendar2"])
    def test_move_events_cli_basic(self, mock_input, mock_select_cal, mock_select_api):
        """Test move_events_cli basic flow."""
        from manage_agenda.events import move_events_cli

        args = Args(
            interactive=True, source=None, destination=None, text=None, delete=False, verbose=False
        )

        mock_api = MagicMock()
        mock_client = MagicMock()
        mock_api.getClient.return_value = mock_client

        mock_events = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Moving meeting",
                    "start": {"dateTime": "2024-01-15T10:00:00"},
                    "end": {"dateTime": "2024-01-15T11:00:00"},
                }
            ]
        }
        mock_client.events().list().execute.return_value = mock_events
        mock_api.getPostTitle.return_value = "Moving meeting"
        mock_api.getPosts.return_value = mock_events["items"]
        mock_select_api.return_value = mock_api

        move_events_cli(args)

        mock_client.events().insert.assert_called()
        mock_client.events().delete.assert_called()


class TestUpdateEventStatusThroughThePort(unittest.TestCase):
    """update_event_status_cli asks through the UI port, and no longer needs a text filter
    to run non-interactively."""

    def _api(self):
        api = MagicMock()
        api.getPosts.return_value = [
            {"id": "e1", "summary": "Busy one", "transparency": "opaque"},
            {"id": "e2", "summary": "Free one", "transparency": "transparent"},
            {"id": "e3", "summary": "Busy two"},
        ]
        api.getPostTitle.side_effect = lambda event: event.get("summary")
        return api

    @patch("manage_agenda.events.display_posts")
    @patch("manage_agenda.events.connections.select_api")
    def test_non_interactive_without_text_offers_every_busy_event(self, mock_select_api, _display):
        from manage_agenda.ui import use_ui
        from manage_agenda.ui.fake import ScriptedUI

        api = self._api()
        mock_select_api.return_value = api
        args = Args(interactive=False, source="cal-1", text=None)

        with use_ui(ScriptedUI([("select_events", [1])])) as ui:
            update_event_status_cli(args)

        # Only "busy" (opaque, or unset) events are offered: e1 and e3.
        offered = ui.calls[0].payload["events"]
        self.assertEqual([event["id"] for event in offered], ["e1", "e3"])
        self.assertEqual(ui.calls[0].payload["labels"], ["Busy one", "Busy two"])
        update = api.getClient.return_value.events.return_value.update
        update.assert_called_once()
        self.assertEqual(update.call_args.kwargs["calendarId"], "cal-1")
        self.assertEqual(update.call_args.kwargs["body"]["id"], "e3")
        self.assertEqual(update.call_args.kwargs["body"]["transparency"], "transparent")

    @patch("manage_agenda.events.display_posts")
    @patch("manage_agenda.events.connections.select_api")
    def test_interactive_asks_for_the_text_filter_first(self, mock_select_api, _display):
        from manage_agenda.ui import use_ui
        from manage_agenda.ui.fake import ScriptedUI

        mock_select_api.return_value = self._api()
        args = Args(interactive=True, source="cal-1", text=None)

        with use_ui(ScriptedUI([("ask_text", "two"), ("select_events", [])])) as ui:
            update_event_status_cli(args)

        self.assertEqual([call.kind for call in ui.calls], ["ask_text", "select_events"])
        self.assertEqual([e["id"] for e in ui.calls[1].payload["events"]], ["e3"])


class TestCalendarOperationsThroughThePort(unittest.TestCase):
    @patch("manage_agenda.events.display_posts")
    @patch("manage_agenda.events.connections.select_api")
    @patch("manage_agenda.events.select_calendar", return_value="calendar1")
    def test_clean_asks_the_operation_through_choose_action(
        self, _select_cal, mock_select_api, _display
    ):
        from manage_agenda.events import clean_events_cli
        from manage_agenda.ui import use_ui
        from manage_agenda.ui.fake import ScriptedUI

        api = MagicMock()
        api.getPosts.return_value = [
            {"id": "e1", "summary": "Old meeting", "start": {"dateTime": "2024-01-15T10:00:00"}, "end": {"dateTime": "2024-01-15T11:00:00"}}
        ]
        api.getPostTitle.return_value = "Old meeting"
        mock_select_api.return_value = api
        args = Args(interactive=True)

        answers = [("ask_text", ""), ("select_events", "all"), ("choose_action", "1")]
        with use_ui(ScriptedUI(answers)) as ui:
            clean_events_cli(args)

        self.assertEqual([call.kind for call in ui.calls], ["ask_text", "select_events", "choose_action"])
        self.assertEqual([key for key, _label in ui.calls[2].payload["actions"]], ["0", "1", "2"])
        # "1" is copy: an insert on the destination, no delete on the source.
        api.getClient.return_value.events.return_value.insert.assert_called_once()
        api.getClient.return_value.events.return_value.delete.assert_not_called()
