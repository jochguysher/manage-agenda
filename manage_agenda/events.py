import datetime
import logging
from datetime import timedelta

import dateparser
import pytz
from socialModules.configMod import safe_get
from socialModules.moduleContent import display_posts

from manage_agenda import connections
from manage_agenda.config import config
from manage_agenda.connections import select_calendar
from manage_agenda.i18n import t
from manage_agenda.ui import echo, get_ui

logger = logging.getLogger(__name__)

# Constants for date confirmation and interactive date/time modification.
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _default_naive_timezone():
    """The pytz timezone used to localize a naive event start/end time (no explicit
    timeZone) - resolved fresh on EVERY call from config.DEFAULT_TIMEZONE, never cached as a
    module-level constant.

    This used to be a `DEFAULT_NAIVE_TIMEZONE = pytz.timezone(config.DEFAULT_TIMEZONE)`
    constant computed once at import time - the same baked-at-import pattern behind the
    ledger/config-path pollution bug fixed elsewhere in this redesign (see
    docs/investigation-limite1.md §10), just for a timezone instead of a path. It surfaced as
    three test_events.py failures (test_adjust_event_times_*) that looked like unrelated
    flakiness: the constant silently read whatever DEFAULT_TIMEZONE the local .env happened
    to set (America/Toronto, UTC-5 in January) instead of the Europe/Berlin (UTC+1) the tests
    assumed - a 6-hour discrepancy - because nothing isolates that env var in tests and the
    constant, once baked, ignored the timezone test_config.py's own patch.object(Config,
    "DEFAULT_TIMEZONE", ...) calls elsewhere set for their own purposes. Bounded-purge
    entries stamp their event_end from Calendar's own live event, not from this function, but
    an event manage-agenda CREATES from a naive datetime is stamped via this - so a wrong
    default timezone here does eventually skew purge timing by the same offset, once that
    event's own end date is later read back."""
    try:
        return pytz.timezone(config.DEFAULT_TIMEZONE)
    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"Invalid timezone '{config.DEFAULT_TIMEZONE}' in config. Falling back to UTC.")
        return pytz.utc


def filter_events_by_title(api_cal, events, text_filter):
    """Filter calendar events by title or abstract text."""
    filtered_events = []
    for event in events:
        title = api_cal.getPostTitle(event)
        if title and text_filter and text_filter.lower() in title.lower():
            filtered_events.append(event)
        else:
            abstract = api_cal.getPostAbstract(event)
            if abstract and text_filter and text_filter.lower() in abstract.lower():
                filtered_events.append(event)
            elif not text_filter and title:
                filtered_events.append(event)

    return filtered_events


def _parse_datetime_to_utc(dt_str, tz_name=None):
    """Parse a datetime string, localize it if naive, and convert it to UTC."""
    if not dt_str:
        return None

    if isinstance(dt_str, str):
        normalized_str = dt_str.replace("Z", "+00:00")
    else:
        return None

    try:
        dt_obj = datetime.datetime.fromisoformat(normalized_str)
    except ValueError:
        try:
            dt_obj = datetime.datetime.strptime(normalized_str, DATETIME_FORMAT)
        except ValueError as parse_err:
            logger.error(f"Invalid datetime format: '{dt_str}'. Error: {parse_err}")
            return None

    if dt_obj.tzinfo is None:
        if tz_name:
            try:
                local_tz = pytz.timezone(tz_name)
                dt_obj = local_tz.localize(dt_obj)
            except pytz.exceptions.UnknownTimeZoneError:
                logger.warning(
                    f"Unknown timezone '{tz_name}'. "
                    f"Using default timezone: {config.DEFAULT_TIMEZONE}"
                )
                dt_obj = _default_naive_timezone().localize(dt_obj)
        else:
            dt_obj = _default_naive_timezone().localize(dt_obj)

    return dt_obj.astimezone(pytz.utc)


def _parse_event_times(event):
    """Parse event start and end times into UTC datetime objects."""
    start_str = safe_get(event, ["start", "dateTime"])
    start_tz = safe_get(event, ["start", "timeZone"])
    end_str = safe_get(event, ["end", "dateTime"])
    end_tz = safe_get(event, ["end", "timeZone"])

    current_start = _parse_datetime_to_utc(start_str, start_tz)
    if start_str and current_start is None:
        echo(t("events.could_not_parse_start_time"))

    current_end = _parse_datetime_to_utc(end_str, end_tz)
    if end_str and current_end is None:
        echo(t("events.could_not_parse_end_time"))

    return current_start, current_end


def adjust_event_times(event):
    """Adjust event start/end times, localizing naive times and converting to UTC."""
    if not isinstance(event.get("start"), dict):
        event["start"] = {}
    if not isinstance(event.get("end"), dict):
        event["end"] = {}
    start = event["start"]
    end = event["end"]

    start_dt, end_dt = _parse_event_times(event)

    if start_dt:
        start["dateTime"] = start_dt.isoformat()
        start["timeZone"] = "UTC"

    if end_dt:
        end["dateTime"] = end_dt.isoformat()
        end["timeZone"] = "UTC"

    if not start_dt and end_dt:
        start_dt = end_dt - timedelta(minutes=30)
        start["dateTime"] = start_dt.isoformat()
        start["timeZone"] = "UTC"

    if not end_dt and start_dt:
        end_dt = start_dt + timedelta(minutes=30)
        end["dateTime"] = end_dt.isoformat()
        end["timeZone"] = "UTC"

    if start_dt and end_dt and end_dt <= start_dt:
        echo(t("events.end_not_after_start_warning"))
        end_dt = start_dt + timedelta(minutes=30)
        end["dateTime"] = end_dt.isoformat()
        end["timeZone"] = "UTC"

    return event


def _ensure_valid_event_timezones(event, fallback_tz="UTC"):
    """Ensure both start and end have valid timeZone values."""
    if not isinstance(event, dict):
        return event

    for when in ("start", "end"):
        field = event.setdefault(when, {})
        tz_name = field.get("timeZone")
        if not tz_name:
            field["timeZone"] = fallback_tz
            continue

        try:
            pytz.timezone(tz_name)
        except Exception:
            logger.warning(
                f"Invalid timezone '{tz_name}' for event {when}; using fallback '{fallback_tz}'."
            )
            field["timeZone"] = fallback_tz

    return event


def _validate_event_dates_interactive(event, post_identifier=None, context=None):
    """Let the user confirm or correct an extracted event's dates, through the UI port.

    Returns (event, is_valid, errors) like the non-interactive twin: is_valid is False when
    the user asked for the LLM to be run again ("retry"), which the caller honours by
    re-extracting. The terminal menu (s/r/y/m/d/h/i/f) lives in
    manage_agenda.ui.console.ConsoleUI.review_event; a GUI shows a form instead. `context`
    (extraction.message_context()) names the source message next to the event."""
    label = f"[{post_identifier}] " if post_identifier else ""
    event, decision = get_ui().review_event(event, label=label, context=context)
    return event, decision != "retry", []


def _validate_event_dates_non_interactive(event, post_identifier=None):
    """Validate event dates in non-interactive mode."""
    errors = []
    warnings = []
    label = f"[{post_identifier}] " if post_identifier else ""

    current_start, current_end = _parse_event_times(event)
    if current_start is None or current_end is None:
        errors.append(t("events.missing_start_or_end_datetime", label=label))

    now = datetime.datetime.now(datetime.timezone.utc)
    reasonable_past = now - timedelta(days=730)
    reasonable_future = now + timedelta(days=1825)

    for field_name, dt in [("start", current_start), ("end", current_end)]:
        if dt is None:
            continue
        if dt < reasonable_past:
            warnings.append(
                t(
                    "events.time_far_in_the_past",
                    label=label,
                    field_name=field_name,
                    formatted_time=dt.strftime(DATETIME_FORMAT),
                )
            )
        if dt > reasonable_future:
            warnings.append(
                t(
                    "events.time_far_in_the_future",
                    label=label,
                    field_name=field_name,
                    formatted_time=dt.strftime(DATETIME_FORMAT),
                )
            )

    for warning in warnings:
        echo(t("events.warning_prefix", warning=warning))

    return event, len(errors) == 0, errors


def _format_datetime_for_display(dt_value):
    """Format a datetime value for display in the local timezone."""
    if dt_value is None or dt_value == "":
        return t("events.not_available")

    if isinstance(dt_value, datetime.datetime):
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=datetime.datetime.now().astimezone().tzinfo)
        dt_string = dt_value.isoformat()
    else:
        dt_string = dt_value

    try:
        dt_local = datetime.datetime.fromisoformat(dt_string).astimezone()
        tz_name = dt_local.tzname()
        return dt_local.strftime(f"%Y-%m-%d %H:%M:%S {tz_name}")
    except ValueError:
        return dt_string


def clean_action(api_cal, event, my_calendar, my_calendar_dst):
    pass


def copy_action(api_cal, event, my_calendar, my_calendar_dst):
    """Action function to copy an event."""
    my_event = {
        "summary": event["summary"],
        "description": (
            event["description"] if "description" in event and event["description"] else ""
        ),
        "start": event["start"],
        "end": event["end"],
    }
    if "location" in event:
        my_event["location"] = event["location"]

    my_calendar_dst.getClient().events().insert(calendarId=my_calendar, body=my_event).execute()
    echo(t("events.copied_event", summary=my_event["summary"]))


def copy_events_cli(args):
    """Copies events from a source calendar to a destination calendar."""
    process_calendar_events(args, "copy", copy_action, destination_needed=True)


def select_events_by_user_input(api_cal, events_list, action_verb="copy"):
    """
    Common function to handle user input for selecting events.

    Args:
        api_cal: Calendar API object
        events_list: List of events to select from
        action_verb: String describing the action (e.g., 'copy', 'delete')

    Returns:
        List of selected events
    """
    # The terminal (ConsoleUI.select_events) lists the events with display_posts and reads
    # numbers, "all" or title text; a GUI shows a checkable table. Both get the same labels.
    labels = [api_cal.getPostTitle(event) or "" for event in events_list]
    return get_ui().select_events(
        events_list,
        labels,
        title=t("events.select_events_to", action_verb=action_verb),
        prompt_text=t("events.which_events_prompt", action_verb=action_verb),
        render=lambda: display_posts(api_cal, events_list),
    )


def process_calendar_events(
    args, action_verb, action_func, destination_needed=False, api_src_type="gcalendar"
):
    """
    Generic function to handle complete calendar event processing from initialization to action.

    Args:
        args: Arguments object
        action_verb: String describing the action (e.g., 'copy', 'delete', 'move')
        action_func: Function to perform the specific action on selected events
        destination_needed: Boolean indicating if destination calendar is needed
        api_src_type: Type of API source (default: "gcalendar")

    Returns:
        None
    """
    # Initialize API and calendar
    api_cal = connections.select_api(args, "gcalendar", rules=None, title=t("events.select_rule_title"))
    if getattr(args, "source", None):
        selected_calendar = args.source
    else:
        selected_calendar = select_calendar(api_cal, title=t("events.select_calendar_title"), args=args)

    # Set the active calendar using socialModules method
    api_cal.setActive(selected_calendar)

    today = datetime.datetime.now()
    today = datetime.datetime.now(datetime.timezone.utc)

    # Fetch events from calendar using socialModules methods
    all_posts = []
    try:
        api_cal.setPostsType("posts")
        api_cal.setPosts("2008-01-01")
        all_posts = api_cal.getPosts()
    except Exception:
        all_posts = []

    today = datetime.datetime.now()
    today = datetime.datetime.now(datetime.timezone.utc)

    # If interactive, present all fetched posts (tests expect interactive flows
    # to show items regardless of date)
    if args.interactive:
        future_events = all_posts
    else:
        future_events = []
        for post in all_posts:
            post_date = api_cal.getPostDate(post)
            echo(t("events.date_label", value=post_date))

            if not isinstance(post_date, str):
                if isinstance(post, dict):
                    start = post.get("start", {})
                    post_date = start.get("dateTime") or start.get("date")

            if isinstance(post_date, str):
                post_date = dateparser.parse(post_date)
                # Normalize naive datetimes to UTC for comparison
                if post_date and post_date.tzinfo is None:
                    try:
                        post_date = pytz.utc.localize(post_date)
                    except Exception:
                        pass
            else:
                post_date = None

            if post_date and post_date >= today:
                future_events.append(post)

    echo(t("events.upcoming_events_title"))
    for event in future_events[:20]:
        echo(t("events.event_line", title=api_cal.getPostTitle(event), date=api_cal.getPostDate(event)))

    text_filter = args.text
    if args.interactive and not text_filter:
        text_filter = get_ui().ask_text(t("events.text_filter_prompt"))

    # Use the helper function to filter events by title
    filtered_events = filter_events_by_title(api_cal, future_events, text_filter)

    if not filtered_events:
        echo(t("events.no_events_found"))
        return

    selected_events = select_events_by_user_input(api_cal, filtered_events, action_verb)

    if "clean" in action_func.__name__:
        actions = [t("events.action_delete"), t("events.action_copy"), t("events.action_move")]
        msg = t("events.select_operation_title")
        for i, act in enumerate(actions):
            msg = f"{msg}\n{i}) {act}"
        msg = f"{msg}\n"

        action_sel = get_ui().choose_action(
            [("0", actions[0]), ("1", actions[1]), ("2", actions[2])], msg
        )
        destination_needed = True
        if action_sel == "1":  # Copy
            action_verb = "copy"
            action_func = copy_action
        elif action_sel == "2":  # Move
            action_verb = "move"
            action_func = move_action
        else:  # Delete
            action_verb = "delete"
            action_func = delete_action
            destination_needed = False

    # Handle destination calendar if needed
    if destination_needed:
        my_calendar_dst = connections.select_api(
            args, "gcalendar", rules=None, title=t("events.select_rule_lower_title")
        )
        if getattr(args, "destination", None):
            my_calendar = args.destination
        else:
            my_calendar = select_calendar(
                my_calendar_dst, title=t("events.select_destination_calendar"), args=args
            )
    else:
        my_calendar = None
        my_calendar_dst = None

    # Perform the specific action on selected events
    for event in selected_events:
        action_func(api_cal, event, my_calendar, my_calendar_dst)


def delete_action(api_cal, event, my_calendar, my_calendar_dst):
    """Action function to delete an event."""
    api_cal.getClient().events().delete(
        calendarId=api_cal.getActive(), eventId=event["id"]
    ).execute()
    echo(t("events.deleted_event", summary=event["summary"]))


def delete_events_cli(args):
    """Deletes events from a calendar."""
    process_calendar_events(args, "delete", delete_action)


def move_action(api_cal, event, my_calendar, my_calendar_dst):
    """Action function to move an event (copy then delete)."""
    my_event = {
        "summary": event["summary"],
        "description": event["description"] if "description" in event else "",
        "start": event["start"],
        "end": event["end"],
    }
    if "location" in event:
        my_event["location"] = event["location"]

    my_calendar_dst.getClient().events().insert(calendarId=my_calendar, body=my_event).execute()
    echo(t("events.copied_event", summary=my_event["summary"]))
    api_cal.getClient().events().delete(
        calendarId=api_cal.getActive(), eventId=event["id"]
    ).execute()
    echo(t("events.deleted_event", summary=event["summary"]))


def move_events_cli(args):
    """Moves events from a source calendar to a destination calendar."""
    process_calendar_events(args, "move", move_action, destination_needed=True)


def update_event_status_cli(args):
    """Update event status from busy to available for selected events."""
    api_cal = connections.select_api(args, "gcalendar", rules=None, title=t("events.select_rule_title"))

    if args.source:
        my_calendar = args.source
    else:
        my_calendar = select_calendar(api_cal)

    api_cal.setActive(my_calendar)
    api_cal.setPosts(max_results=None, event_types="default", show_active=False)
    events = api_cal.getPosts() or []
    display_posts(
        api_cal,
        events,
        format_post=lambda event: (
            f"[{event.get('transparency', 'opaque')}] "
            f"{api_cal.getPostTitle(event) or t('events.no_title')}"
        ),
        limit=20,
        title=t("events.upcoming_events_title"),
    )

    text_filter = args.text
    if args.interactive and not text_filter:
        text_filter = get_ui().ask_text(t("events.text_filter_prompt"))

    events_to_update = []
    for event in events:
        title = api_cal.getPostTitle(event) or t("events.no_title")
        # No filter (neither -i nor --text) means every event, as filter_events_by_title
        # does; `None in title` used to raise TypeError here.
        if not text_filter or text_filter in title:
            # Only include events that are currently "busy" (opaque)
            if event.get("transparency", "opaque") == "opaque":
                events_to_update.append(event)

    if not events_to_update:
        echo(t("events.no_busy_events_found"))
        return

    selected_events = select_events_by_user_input(api_cal, events_to_update, "update")

    for event in selected_events:
        # Update the event's transparency to "transparent" (available/free)
        event["transparency"] = "transparent"

        # Perform the update
        api_cal.getClient().events().update(
            calendarId=my_calendar, eventId=event["id"], body=event
        ).execute()

        title = api_cal.getPostTitle(event) or t("events.no_title")
        echo(t("events.updated_status_available", title=title))


def clean_events_cli(args):
    """Combined command to clean calendar entries (select between copy or delete)."""
    process_calendar_events(args, "clean", clean_action, destination_needed=True)
