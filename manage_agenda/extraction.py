"""LLM-driven calendar event extraction and publication helpers."""

import ast
import datetime
import hashlib
import json
import logging
import time
from copy import copy, deepcopy
from dataclasses import is_dataclass, replace
from pathlib import Path

import googleapiclient
from socialModules.configMod import safe_get

from manage_agenda.base import format_time, write_file
from manage_agenda.connections import select_api, select_calendars
from manage_agenda.llm import select_llm


def create_event_dict():
    """Create the template dictionary used for extracted calendar events."""
    return {
        "summary": "",
        "location": "",
        "description": "",
        "start": {"dateTime": "", "timeZone": ""},
        "end": {"dateTime": "", "timeZone": ""},
        "recurrence": [],
    }


def add_message_to_event_description(event, content):
    """Add the source content to an extracted event description."""
    event["description"] = f"{safe_get(event, ['description'])}\n\nMessage:\n{content}"
    return event


def _get_text_snippet(original_content):
    """Get replacement source text while preserving its message date."""
    print("Paste the relevant part of the text here (finish with Ctrl-D):")
    lines = []
    while True:
        try:
            lines.append(input())
        except EOFError:
            break

    if not lines:
        return None

    new_content_text = "\n".join(lines)
    for line in original_content.splitlines():
        if line.startswith("Message date:"):
            new_content_text += f"\n{line}"
            break
    return new_content_text


def _print_context_and_options(content, options_prompt, verbose=False):
    """Display the source context and return the selected fallback action."""
    from manage_agenda.sources import print_first_lines
    for line in content.splitlines():
        if line.startswith("Url: "):
            print(line)
            break
    if verbose:
        print_first_lines(content, content_type="source text")
    return input(options_prompt).lower().strip()


def extract_json(text):
    """Return the JSON-like portion of an LLM response."""
    if not text.startswith("{"):
        pos = text.find("{")
        if pos != -1:
            text = text[pos:]
    if not text.endswith("}"):
        pos = text.rfind("}")
        if pos != -1:
            text = text[: pos + 1]
    return text


def get_event_from_llm(model, prompt, post_id, verbose=False):
    """Get event data from an LLM and parse its calendar JSON response."""
    from manage_agenda.sources import print_first_lines
    from manage_agenda.exceptions import LLMError

    print(f"Calling LLM {model.model_name}")
    event, vcal_json = None, None
    start_time = time.time()
    try:
        llm_response = model.generate_text(prompt)
    except LLMError as error:
        print(f"LLM API error: {error}")
        return None, "ServiceError", time.time() - start_time
    write_file(f"log/{model.model_name}/{post_id}_llm.txt", llm_response)
    elapsed_time = time.time() - start_time
    print(f"AI call took {format_time(elapsed_time)} ({elapsed_time:.2f} seconds)")

    memory_error_occurred = False
    json_error_occurred = True
    if not llm_response:
        print("Failed to get response from LLM.")
    elif "model requires more system memory" in llm_response:
        print(
            "LLM failed due to insufficient memory. Model requires more "
            "system memory than available."
        )
        memory_error_occurred = True
    else:
        if verbose:
            print_first_lines(llm_response, n=None, title="Reply")
        try:
            vcal_json = ast.literal_eval(extract_json(llm_response.replace("\n", " ")))
            write_file(
                f"log/{model.model_name}/{post_id}_vcal_extracted.txt", json.dumps(vcal_json)
            )
            if verbose:
                print_first_lines(vcal_json, n=None, title="Json")
            event = vcal_json
            json_error_occurred = False
        except json.JSONDecodeError as error:
            logging.error(f"Invalid JSON in vCal data: {vcal_json}")
            logging.error(f"Error: {error}")
        except SyntaxError as error:
            logging.error(f"Syntax error: {vcal_json}")
            logging.error(f"Error: {error}")
        except ValueError as error:
            logging.error(f"Value error: {vcal_json}")
            logging.error(f"Error: {error}")

    if memory_error_occurred or json_error_occurred:
        event = None
        vcal_json = "MemoryError" if memory_error_occurred else "JsonError"
    return event, vcal_json, elapsed_time


def _with_source(args, source):
    """Clone arguments for alternate-model selection without importing sources.Args."""
    if is_dataclass(args):
        return replace(args, source=source)
    if hasattr(args, "_replace"):
        return args._replace(source=source)
    new_args = copy(args)
    new_args.source = source
    return new_args


def get_event_from_llm_with_retry(model, prompt, post_id, args):
    """Call an LLM repeatedly and switch models if a memory error occurs.

    A successful extraction is accepted as soon as it is produced. Earlier
    versions re-queried the model once more "to confirm" the first event's
    date, then unconditionally replaced the whole result with whatever that
    second, independent call returned. For a multi-event extraction, that
    silently discarded a correct list of distinct events in favor of the
    second call's (possibly collapsed or shorter) answer.
    """
    event = None
    vcal_json = None
    elapsed_time = 0
    memory_error_occurred = False
    json_error_occurred = False
    retries = 0
    max_retries = 3

    while (
        not event
        and not memory_error_occurred
        and not json_error_occurred
        and retries < max_retries
    ):
        event, vcal_json, elapsed_time = get_event_from_llm(model, prompt, post_id, args.verbose)
        if vcal_json == "ServiceError" or _is_occupancy_payload(event):
            return event, vcal_json, elapsed_time
        retries += 1

        if vcal_json == "MemoryError":
            print("Switching to a different LLM due to memory constraints...")
            source = None if args.interactive else model.model_name
            if not args.interactive:
                print("Trying to switch to a lighter model automatically...")
            print(f"Source: {source}")
            new_model = select_llm(_with_source(args, source))
            if new_model:
                model = new_model
                if args.interactive:
                    print(f"Selected new AI model: {model.__class__.__name__}")
                else:
                    print(f"Switched to lighter AI model: {model.__class__.__name__}")
                event = None
                vcal_json = None
            else:
                if args.interactive:
                    print("No alternative model selected. Skipping event processing.")
                else:
                    print("Could not switch to a lighter model. Skipping event processing.")
                memory_error_occurred = True
        elif vcal_json == "JsonError":
            event = None
            vcal_json = None
            json_error_occurred = False
            print("Error in generated Json...")

    if not event and retries >= max_retries:
        vcal_json = "RetryError"
        print("Max retries reached. Skipping event processing.")
    return event, vcal_json, elapsed_time


def _create_llm_prompt(*args):
    """Construct the LLM prompt for calendar event extraction."""
    if len(args) == 2:
        content_text, reference_date_time = args
        event = create_event_dict()
    elif len(args) == 3:
        event, content_text, reference_date_time = args
    else:
        raise TypeError(
            f"_create_llm_prompt() takes 2 or 3 positional arguments but {len(args)} were given"
        )

    content_text = content_text.replace("\r", "")
    prompt_template = _prompt_template_for(content_text)
    return (
        prompt_template.replace("{event}", str(event)).replace("{content_text}", content_text)
    )


def _from_header(content_text):
    for line in (content_text or "").splitlines():
        if line.lower().startswith("from:"):
            return line.split(":", 1)[1].strip()
    return ""


def _prompt_template_for(content_text):
    from manage_agenda.scheduling import prompt_template_for

    specific = prompt_template_for(_from_header(content_text))
    if specific:
        return specific
    prompt_file = Path(__file__).parent / "prompts" / "event_extraction_prompt.txt"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    return (
        "Extract event information from the provided text and fill in the JSON structure below.\n\n"
        "JSON structure to fill:\n{event}\n\n"
        "SOURCE TEXT:\n{content_text}\n"
    )


def _is_occupancy_payload(event):
    item = event[0] if isinstance(event, (list, tuple)) and event else event
    return isinstance(item, dict) and item.get("kind") == "room_occupancy"


def _extract_event_with_llm_retry(
    args, model, content_text, reference_date_time, post_identifier, subject_for_print
):
    """Extract, normalize, and optionally retry an LLM-generated event."""
    from manage_agenda.events import adjust_event_times
    from manage_agenda.sources import print_first_lines

    original_content = content_text
    prompt_content = content_text
    total_elapsed_time = 0
    while True:
        prompt = _create_llm_prompt(prompt_content, reference_date_time)
        write_file(f"log/{post_identifier}_prompt.txt", prompt)
        if args.verbose:
            print_first_lines(prompt, n=None, title="Prompt")

        event, vcal_json, elapsed_time = get_event_from_llm_with_retry(
            model, prompt, post_identifier, args
        )
        total_elapsed_time += elapsed_time
        if args.verbose:
            print_first_lines(event, n=None, title="Event")
        if event is None and vcal_json in {"MemoryError", "RetryError", "ServiceError"}:
            return event, vcal_json, total_elapsed_time, False, False, False

        if _is_occupancy_payload(event):
            return event, vcal_json, total_elapsed_time, True, False, False

        if event:
            if not isinstance(event, (list, tuple)):
                event = [event]
            processed_events = []
            for single_event in event:
                if args.verbose and len(event) > 1:
                    print_first_lines(single_event, title="Single event")
                if isinstance(single_event, dict):
                    single_event = add_message_to_event_description(single_event, original_content)
                    processed_events.append(adjust_event_times(single_event))
            event = processed_events or None
            if args.verbose:
                print_first_lines(processed_events, title="Proc event")
            break

        write_file(
            f"log/{post_identifier}_fail.vcal",
            json.dumps(vcal_json) if vcal_json else "Failed extraction",
        )
        if not args.interactive:
            return None, vcal_json, total_elapsed_time, False, False, False

        print("\nLLM failed to extract event information.")
        choice = _print_context_and_options(
            original_content,
            "Options: (r)etry, (p)rovide relevant text snippet, (s)kip item: ",
            args.verbose,
        )
        if choice == "r":
            prompt_content = original_content
            continue
        if choice == "p":
            snippet = _get_text_snippet(original_content)
            if snippet:
                prompt_content = snippet
                continue
        return None, vcal_json, total_elapsed_time, False, False, False

    write_file(
        f"log/{model.model_name}/{post_identifier}_event_processed.vcal",
        json.dumps(event) if isinstance(event, (dict, list)) else str(event),
    )
    if isinstance(event, (list, tuple)):
        for idx, single_event in enumerate(event, start=1):
            write_file(
                f"log/{model.model_name}/{post_identifier}_{idx}.vcal",
                json.dumps(single_event)
                if isinstance(single_event, (dict, list))
                else str(single_event),
            )
    else:
        write_file(
            f"log/{post_identifier}.vcal",
            json.dumps(event) if isinstance(event, (dict, list)) else str(event),
        )
    return event, vcal_json, total_elapsed_time, True, False, False


def _display_event_info(
    event, subject_for_print, elapsed_time=None, model=None, post_identifier=""
):
    """Display a normalized event consistently."""
    from manage_agenda.events import _format_datetime_for_display

    start_time_local = _format_datetime_for_display(safe_get(event, ["start", "dateTime"]))
    end_time_local = _format_datetime_for_display(safe_get(event, ["end", "dateTime"]))
    event_summary = safe_get(event, ["summary"]) or subject_for_print
    print("=====================================")
    print(f"Summary: {event_summary}")
    if post_identifier:
        print(f"File: {post_identifier}")
    print(f"Start: {start_time_local}")
    print(f"End: {end_time_local}")
    print(f"Model: {model.model_name}")
    if elapsed_time is not None:
        print(f"Time: {format_time(elapsed_time)} ({elapsed_time:.2f} seconds)")
    print("=====================================")
    return start_time_local, end_time_local


def _process_event_with_llm_and_calendar(
    args,
    model,
    content_text,
    reference_date_time,
    post_identifier,
    subject_for_print,
    rules=None,
):
    """Extract events, validate their dates, and publish or write them."""
    from manage_agenda.events import (
        _validate_event_dates_interactive,
        _validate_event_dates_non_interactive,
        adjust_event_times,
    )

    success = False
    should_process = True
    date_validation_retries = 0
    max_date_validation_retries = 3
    while should_process and not success:
        if date_validation_retries >= max_date_validation_retries:
            print(
                f"Max date validation retries ({max_date_validation_retries}) "
                f"reached for {post_identifier}. Skipping event processing."
            )
            break

        event, vcal_json, elapsed_time, extraction_success, need_restart, need_another_ai = (
            _extract_event_with_llm_retry(
                args, model, content_text, reference_date_time, post_identifier, subject_for_print
            )
        )
        if vcal_json == "ServiceError":
            from manage_agenda.exceptions import LLMError

            raise LLMError("The model API did not answer. This message stays pending.")
        if need_restart or need_another_ai:
            return None, None
        if not extraction_success or event is None:
            return None, None

        from manage_agenda.scheduling import as_occupancy, is_occupancy_sender

        sender = _from_header(content_text)
        if _is_occupancy_payload(event) or is_occupancy_sender(sender):
            event = as_occupancy(event)
            events, api_dst, selected_calendars = _visits_from_occupancy(
                event, content_text, args, rules
            )
            if not events:
                print("No visit fits the hours, the weekdays, and the next room occupation.")
                return None, None
        else:
            events = list(event)
            api_dst, selected_calendars = _selected_calendar(
                args, rules, title=events[0].get("summary", "Event")
            )
        calendar_results = []

        if getattr(args, "output", "calendar") == "calendar" and not selected_calendars:
            print("No calendar selected, skipping event creation.")
        else:
            for idx, single_event in enumerate(events, start=1):
                single_event = adjust_event_times(single_event)
                write_file(
                    f"log/{model.model_name}/{post_identifier}_{idx}.json",
                    json.dumps(single_event),
                )
                _display_event_info(
                    single_event, subject_for_print, elapsed_time, model, post_identifier
                )

                retry_needed = False
                if args.interactive:
                    single_event, is_valid, _ = _validate_event_dates_interactive(
                        single_event, post_identifier
                    )
                    retry_needed = not is_valid
                else:
                    single_event, is_valid, validation_errors = _validate_event_dates_non_interactive(
                        single_event, post_identifier
                    )
                    if not is_valid:
                        print(f"Date validation errors for {post_identifier}:")
                        for error in validation_errors:
                            print(f"  - {error}")
                        date_validation_retries += 1
                        break

                if retry_needed and model and content_text and reference_date_time:
                    date_validation_retries += 1
                    break
                if single_event is None:
                    continue

                _add_ai_metadata_to_event(single_event, model, elapsed_time)
                file_name = f"log/{post_identifier}_{idx}_times.json"
                if getattr(args, "output", "calendar") == "calendar":
                    calendar_result = []
                    all_published = True
                    for calendar_id in selected_calendars:
                        # A separate copy per calendar: publishing stamps identity properties
                        # onto the event dict that are scoped to one calendar, and would
                        # otherwise be overwritten before the next calendar's insert.
                        published, single_result = _publish_event_to_calendar(
                            api_dst, deepcopy(single_event), calendar_id, source_id=post_identifier
                        )
                        if not published or (
                            isinstance(single_result, dict) and not single_result.get("success")
                        ):
                            all_published = False
                            break
                        calendar_result.append(single_result)
                    if not all_published:
                        from manage_agenda.exceptions import CalendarError

                        raise CalendarError(
                            "The calendar was not updated. This message stays pending."
                        )
                    published = True
                else:
                    write_file(
                        f"log/{model.model_name}/{post_identifier}_{idx}_times.json",
                        json.dumps(single_event),
                    )
                    calendar_result = f"{post_identifier}_{idx}_times.json"
                    published = True
                if published:
                    if getattr(args, "output", "calendar") == "calendar":
                        calendar_results.extend(calendar_result)
                        for single_result in calendar_result:
                            if isinstance(single_result, dict) and single_result.get("duplicate"):
                                print(f"Already on the calendar, skipped: {single_event.get('summary')}")
                            else:
                                print("Calendar event created")
                    else:
                        calendar_results.append(calendar_result)
                        print(f"File {post_identifier}_{idx}_times.json created")
                    success = True
                    write_file(file_name, json.dumps(single_event))

        print(f"Success: {success}")
        if success:
            if args.verbose:
                print(f"Events: {events}")
                print(f"Results: {calendar_results}")
            return events, calendar_results
        return None, None
    return None, None


def _normalize_summary(event):
    return " ".join((event.get("summary") or "").casefold().split())


def _start_token(event):
    """Minute-precision UTC token so the same slot matches across formats."""
    start = event.get("start") or {}
    if start.get("date") and not start.get("dateTime"):
        return f"d:{start['date']}"
    raw = start.get("dateTime") or ""
    if not raw:
        return ""
    try:
        moment = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return str(raw)
    if moment.tzinfo is None:
        tzname = start.get("timeZone") or "UTC"
        try:
            import pytz

            moment = pytz.timezone(tzname).localize(moment)
        except Exception:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
    moment = moment.astimezone(datetime.timezone.utc).replace(second=0, microsecond=0)
    return moment.strftime("%Y-%m-%dT%H:%M")


def _identity_hash(*parts):
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def event_identity(event, source_id="", calendar_id=""):
    """Slot key (calendar + summary + start) and, when known, a key that also includes the source mail.

    The calendar is part of the key so the same appointment inserted into two calendars (or
    re-inserted after being deleted from one) is not mistaken for a duplicate of itself.
    """
    summary = _normalize_summary(event)
    start = _start_token(event)
    slot = _identity_hash(str(calendar_id), summary, start) if summary and start else ""
    source = (
        _identity_hash(str(calendar_id), str(source_id), summary, start)
        if source_id and summary and start
        else ""
    )
    return slot, source


def _stamp_event_identity(event, source_id="", calendar_id=""):
    slot, source = event_identity(event, source_id, calendar_id)
    private = event.setdefault("extendedProperties", {}).setdefault("private", {})
    if slot:
        private["manageAgendaSlot"] = slot
    if source:
        private["manageAgendaSource"] = source
    return slot, source


def _calendar_items(response):
    if not isinstance(response, dict):
        return []
    items = response.get("items")
    return items if isinstance(items, list) else []


def _start_window(event):
    start = event.get("start") or {}
    if start.get("date") and not start.get("dateTime"):
        day = datetime.date.fromisoformat(start["date"])
        opening = datetime.datetime.combine(day, datetime.time.min, tzinfo=datetime.timezone.utc)
        return opening, opening + datetime.timedelta(days=1)
    raw = start.get("dateTime") or ""
    if not raw:
        return None
    try:
        moment = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    moment = moment.astimezone(datetime.timezone.utc)
    return moment - datetime.timedelta(minutes=1), moment + datetime.timedelta(minutes=1)


def _same_slot(existing, event):
    return _normalize_summary(existing) == _normalize_summary(event) and _start_token(
        existing
    ) == _start_token(event)


def find_existing_event(api_dst, event, calendar_id, source_id=""):
    """Return an existing calendar event that is the same appointment, if one is known.

    Always asks Calendar (by extendedProperty, then by time window) rather than trusting a
    local cache: a cache that outlives a manually deleted event would make recreating that
    event look like a no-op duplicate instead of actually recreating it.
    """
    slot, source = event_identity(event, source_id, calendar_id)

    client = api_dst.getClient()
    for name, value in (("manageAgendaSlot", slot), ("manageAgendaSource", source)):
        if not value:
            continue
        try:
            response = (
                client.events()
                .list(
                    calendarId=calendar_id,
                    privateExtendedProperty=f"{name}={value}",
                    maxResults=1,
                    singleEvents=True,
                )
                .execute()
            )
        except Exception as error:
            logging.warning(f"Could not look up {name}: {error}")
            continue
        items = _calendar_items(response)
        if items:
            return items[0]

    window = _start_window(event)
    if not window:
        return None
    time_min, time_max = window
    try:
        response = (
            client.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat().replace("+00:00", "Z"),
                timeMax=time_max.isoformat().replace("+00:00", "Z"),
                singleEvents=True,
                maxResults=20,
            )
            .execute()
        )
    except Exception as error:
        logging.warning(f"Could not list events around the start time: {error}")
        return None
    for item in _calendar_items(response):
        if _same_slot(item, event):
            return item
    return None


def calendar_sync_state_file():
    """Per-calendar Calendar API sync tokens, used to detect deleted events incrementally."""
    from manage_agenda.config import DATA_DIR

    return Path(DATA_DIR) / "calendar_sync_tokens.json"


def _load_sync_tokens(path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict):
        return {}
    return {str(key): str(value) for key, value in tokens.items()}


def _save_sync_tokens(path, tokens):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"tokens": tokens}, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


# How far back a bootstrap (or post-410 reseed) full listing reaches. Calendar's API forbids
# combining timeMin/timeMax with syncToken at all, so this bound only ever applies to the
# unavoidable full listing - every later incremental call is a cheap, unbounded-by-us delta.
# Events this tool creates are appointments extracted from recent messages, so their start time
# is virtually always within this window; an event scheduled further out than this and deleted
# before its first incremental check would not be caught by the bootstrap diff below.
_SYNC_BOOTSTRAP_WINDOW_DAYS = 90


def _bootstrap_cutoff():
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=_SYNC_BOOTSTRAP_WINDOW_DAYS
    )


def _bootstrap_time_min():
    return _bootstrap_cutoff().isoformat().replace("+00:00", "Z")


def _is_within_bootstrap_window(recorded_at):
    """Whether a tracked ref is recent enough that the bootstrap listing should cover it.

    Without this, an id whose ref predates the window would be "missing from the listing" on
    every reseed forever, without ever actually being confirmable one way or the other - paying
    a targeted get() for it each time, growing with the whole ledger's history instead of its
    recent activity. A ref with no recorded_at (from before this field existed) is treated as
    outside the window: conservative, and consistent with how the ledger treats other entries
    it has no information about.
    """
    if not recorded_at:
        return False
    try:
        moment = datetime.datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment >= _bootstrap_cutoff()


def _list_all_pages(client, calendar_id, sync_token=None, time_min=None):
    """Every event on one calendar since `sync_token`, or a full listing without one.

    `time_min` only makes sense for the full-listing case: Calendar's API rejects timeMin
    combined with syncToken. Follows nextPageToken across pages; the last page carries
    nextSyncToken, which the caller stores and passes back next time to get only what changed
    since this call. Raises googleapiclient.errors.HttpError on failure - in particular 410 Gone
    when sync_token has expired and a fresh one must be seeded instead.
    """
    items = []
    next_sync_token = None
    page_token = None
    while True:
        kwargs = {"calendarId": calendar_id, "showDeleted": True, "singleEvents": True}
        if page_token:
            kwargs["pageToken"] = page_token
        if sync_token:
            kwargs["syncToken"] = sync_token
        elif time_min:
            kwargs["timeMin"] = time_min
        response = client.events().list(**kwargs).execute()
        items.extend(_calendar_items(response))
        next_sync_token = response.get("nextSyncToken", next_sync_token)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return items, next_sync_token


def _confirm_missing_ids(client, calendar_id, missing_ids):
    """Tell a genuine deletion apart from "just outside the bootstrap listing's time window".

    One targeted get() per id - only for the ids a bounded bootstrap listing did not account
    for at all, typically a handful, never the whole tracked set. An id is confirmed deleted on
    404/410 or an explicit "cancelled" status; any other error is inconclusive and is left out,
    the same conservative default used everywhere else here, so a transient API problem cannot
    cause a message to be silently reprocessed.
    """
    confirmed = set()
    for event_id in missing_ids:
        try:
            response = client.events().get(calendarId=calendar_id, eventId=event_id).execute()
        except googleapiclient.errors.HttpError as error:
            if getattr(getattr(error, "resp", None), "status", None) in (404, 410):
                confirmed.add(event_id)
            continue
        except Exception:
            continue
        if (response or {}).get("status") == "cancelled":
            confirmed.add(event_id)
    return confirmed


def sync_calendar_changes(api_dst, calendar_id, tracked_events=None, path=None):
    """Ids that need to be treated as deleted on one calendar, via Calendar's incremental sync.

    This is the mechanism sync clients use: one cheap call returns only what changed since a
    stored syncToken, regardless of how many events are being tracked - not one check per known
    event. Once a valid token exists, deletions are exactly the ids that come back with
    status "cancelled" in that delta.

    The first call for a calendar (no token yet), or one made after a stored token has expired
    (Calendar answers 410 Gone), has no "since when" to diff against, so instead it does one
    bounded full listing (see _SYNC_BOOTSTRAP_WINDOW_DAYS) to seed a fresh token - covering
    deletions that happened before this tool ever ran, or during the gap before a reseed. Among
    the tracked ids absent from that listing, only the recent ones (see
    _is_within_bootstrap_window) are confirmed with one targeted lookup each (_confirm_missing_ids):
    an id old enough to already be outside the listing's window is left alone rather than paying
    for a lookup every single reseed, forever, as the ledger accumulates history. Any other API
    error is conservative: nothing is reported and the stored token, if any, is left untouched.

    `tracked_events` is {event_id: recorded_at} for this calendar - recorded_at is when this
    tool created/confirmed the ref (see _extract_event_refs), used only to decide which missing
    ids are worth confirming.

    Returns the set of event ids to treat as deleted.
    """
    path = Path(path) if path else calendar_sync_state_file()
    tokens = _load_sync_tokens(path)
    token = tokens.get(calendar_id)
    client = api_dst.getClient()
    tracked_events = dict(tracked_events or {})

    def _bootstrap():
        try:
            items, fresh_token = _list_all_pages(
                client, calendar_id, time_min=_bootstrap_time_min()
            )
        except Exception as error:
            logging.warning(f"Could not seed a Calendar sync token for {calendar_id}: {error}")
            return set()
        if fresh_token:
            tokens[calendar_id] = fresh_token
            _save_sync_tokens(path, tokens)
        else:
            logging.warning(f"Calendar did not return a sync token for {calendar_id}.")
        listed_ids = {item.get("id") for item in items if item.get("id")}
        cancelled_ids = {
            item.get("id") for item in items if item.get("status") == "cancelled" and item.get("id")
        }
        missing_ids = set(tracked_events) - listed_ids
        confirmable_ids = {
            event_id
            for event_id in missing_ids
            if _is_within_bootstrap_window(tracked_events.get(event_id))
        }
        confirmed_missing = (
            _confirm_missing_ids(client, calendar_id, confirmable_ids) if confirmable_ids else set()
        )
        return cancelled_ids | confirmed_missing

    if not token:
        return _bootstrap()

    try:
        items, fresh_token = _list_all_pages(client, calendar_id, sync_token=token)
    except googleapiclient.errors.HttpError as error:
        if getattr(getattr(error, "resp", None), "status", None) == 410:
            logging.info(f"Calendar sync token expired for {calendar_id}, reseeding.")
            tokens.pop(calendar_id, None)
            return _bootstrap()
        logging.warning(f"Could not fetch Calendar changes for {calendar_id}: {error}")
        return set()
    except Exception as error:
        logging.warning(f"Could not fetch Calendar changes for {calendar_id}: {error}")
        return set()

    if fresh_token:
        tokens[calendar_id] = fresh_token
        _save_sync_tokens(path, tokens)
    else:
        logging.warning(f"Calendar did not return a sync token for {calendar_id}.")

    return {item.get("id") for item in items if item.get("status") == "cancelled" and item.get("id")}


def _selected_calendar(args, rules, title):
    """Use the calendar(s) chosen before the scan, or ask once if not prepared.

    Returns (api_dst, [calendar_id, ...]) - an event is published to every calendar in that
    list.
    """
    if getattr(args, "output", "calendar") != "calendar":
        return None, []
    api_dst = getattr(args, "calendar_api", None)
    selected_calendars = getattr(args, "calendar_ids", None)
    if api_dst and selected_calendars:
        return api_dst, selected_calendars
    api_dst = select_api(args, "gcalendar", rules=rules, title="Select Calendar")
    selected_calendars = select_calendars(api_dst, title=title, args=args)
    return api_dst, selected_calendars


def _visits_from_occupancy(event, content_text, args, rules):
    """Choose a visit before the next occupation, inside the configured hours."""
    from manage_agenda.scheduling import (
        availability_for,
        busy_intervals,
        plan_room_visits,
    )

    payload = event[0] if isinstance(event, (list, tuple)) else event
    sender = _from_header(content_text)
    constraints = availability_for(sender)
    api_dst = None
    selected_calendars = []
    busy = []
    api_dst, selected_calendars = _selected_calendar(args, rules, title="Visite")
    if api_dst and selected_calendars:
        busy = _calendar_busy(api_dst, selected_calendars, constraints)
    visits = plan_room_visits(payload, constraints, busy=busy, sender=sender)
    return visits, api_dst, selected_calendars


def _calendar_busy(api_dst, calendar_ids, constraints):
    """Busy intervals across every selected calendar - a visit must avoid conflicts on all of
    them, since the event will be written to each one."""
    from manage_agenda.scheduling import busy_intervals

    start = datetime.datetime.now(datetime.timezone.utc)
    end = start + datetime.timedelta(days=constraints.horizon_days)
    client = api_dst.getClient()
    busy = []
    for calendar_id in calendar_ids:
        try:
            response = (
                client.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=start.isoformat().replace("+00:00", "Z"),
                    timeMax=end.isoformat().replace("+00:00", "Z"),
                    singleEvents=True,
                    maxResults=100,
                )
                .execute()
            )
        except Exception as error:
            logging.warning(f"Could not read the calendar while choosing a visit: {error}")
            continue
        busy.extend(busy_intervals(response))
    return busy


def _publish_event_to_calendar(api_dst, event, selected_calendar, source_id=""):
    """Publish an event, skipping one that is already on the calendar."""
    from manage_agenda.events import _ensure_valid_event_timezones

    _stamp_event_identity(event, source_id, selected_calendar)
    existing = find_existing_event(api_dst, event, selected_calendar, source_id)
    if existing:
        link = existing.get("htmlLink", "") if isinstance(existing, dict) else ""
        event_id = existing.get("id", "") if isinstance(existing, dict) else ""
        return True, {
            "success": True,
            "duplicate": True,
            "post_url": link,
            "calendar_id": selected_calendar,
            "event_id": event_id,
        }

    def _insert(body):
        result = api_dst.publishPost(post={"event": body, "idCal": selected_calendar}, api=api_dst)
        if isinstance(result, dict) and result.get("success"):
            result.setdefault("calendar_id", selected_calendar)
            result.setdefault("event_id", (result.get("raw_response") or {}).get("id", ""))
        return True, result

    try:
        return _insert(event)
    except googleapiclient.errors.HttpError as error:
        logging.error(f"Error creating calendar event: {error}")
        if "Invalid time zone definition for end time'" in str(error):
            logging.info(
                "Detected invalid timezone definition for end time. Correcting event timezones and retrying."
            )
            event = _ensure_valid_event_timezones(event, fallback_tz="UTC")
            try:
                return _insert(event)
            except Exception as retry_error:
                logging.error(f"Retry after timezone correction failed: {retry_error}")
    return False, None


def _add_ai_metadata_to_event(event, model, elapsed_time, confidence_score=None):
    """Add machine-readable and human-readable LLM processing metadata."""
    from unittest.mock import Mock

    def is_mock(value):
        return isinstance(value, Mock)

    model_name = "unknown"
    if model:
        value = getattr(model, "model_name", None)
        if value is not None and not is_mock(value):
            model_name = str(value)
        elif hasattr(model, "get_name") and callable(model.get_name):
            try:
                value = model.get_name()
                if value is not None and not is_mock(value):
                    model_name = str(value)
            except NotImplementedError:
                pass
        if model_name == "unknown":
            value = getattr(model, "name", None)
            if value is not None and not is_mock(value):
                model_name = str(value)
            elif not is_mock(model):
                model_name = str(model)

    event.setdefault("extendedProperties", {}).setdefault("private", {}).update(
        {
            "ai_model_used": model_name,
            "processing_timestamp": datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "processing_elapsed_time_seconds": f"{elapsed_time:.2f}",
        }
    )
    if confidence_score is not None:
        event["extendedProperties"]["private"]["confidence_score"] = f"{confidence_score:.2f}"

    ai_metadata_text = (
        f"\n\n---\nAI Processing Info:\n- Model: {model_name}"
        f"\n- Processing time: {elapsed_time:.2f} seconds"
    )
    if confidence_score is not None:
        ai_metadata_text += f"\n- Confidence: {confidence_score:.2f}"
    event["description"] = event.get("description", "") + ai_metadata_text
