"""LLM-driven calendar event extraction and publication helpers."""

import ast
import base64
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
from manage_agenda.connections import calendar_account_key, select_api, select_calendars
from manage_agenda.i18n import t
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
    print(t("extraction.paste_text_prompt"))
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
        print_first_lines(content, content_type=t("extraction.source_text_content_type"))
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


def get_event_from_llm(model, prompt, post_id, verbose=False, debug_log_extractions=False):
    """Get event data from an LLM and parse its calendar JSON response."""
    from manage_agenda.exceptions import LLMError
    from manage_agenda.sources import print_first_lines

    print(t("extraction.calling_llm", model=model.model_name))
    event, vcal_json = None, None
    start_time = time.time()
    try:
        llm_response = model.generate_text(prompt)
    except LLMError as error:
        print(t("extraction.llm_api_error", error=error))
        return None, "ServiceError", time.time() - start_time
    write_file(
        f"log/{model.model_name}/{post_id}_llm.txt", llm_response, enabled=debug_log_extractions
    )
    elapsed_time = time.time() - start_time
    print(
        t(
            "extraction.ai_call_took",
            duration=format_time(elapsed_time),
            seconds=f"{elapsed_time:.2f}",
        )
    )

    memory_error_occurred = False
    json_error_occurred = True
    if not llm_response:
        print(t("extraction.failed_to_get_response"))
    elif "model requires more system memory" in llm_response:
        print(t("extraction.llm_insufficient_memory"))
        memory_error_occurred = True
    else:
        if verbose:
            print_first_lines(llm_response, n=None, title=t("extraction.title_reply"))
        try:
            vcal_json = ast.literal_eval(extract_json(llm_response.replace("\n", " ")))
            write_file(
                f"log/{model.model_name}/{post_id}_vcal_extracted.txt",
                json.dumps(vcal_json),
                enabled=debug_log_extractions,
            )
            if verbose:
                print_first_lines(vcal_json, n=None, title=t("extraction.title_json"))
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
        event, vcal_json, elapsed_time = get_event_from_llm(
            model, prompt, post_id, args.verbose, getattr(args, "debug_log_extractions", False)
        )
        if vcal_json == "ServiceError" or _is_occupancy_payload(event):
            return event, vcal_json, elapsed_time
        retries += 1

        if vcal_json == "MemoryError":
            print(t("extraction.switching_llm_memory"))
            source = None if args.interactive else model.model_name
            if not args.interactive:
                print(t("extraction.trying_lighter_model"))
            print(t("extraction.source_debug", source=source))
            new_model = select_llm(_with_source(args, source))
            if new_model:
                model = new_model
                if args.interactive:
                    print(t("extraction.selected_new_ai_model", model=model.__class__.__name__))
                else:
                    print(t("extraction.switched_lighter_ai_model", model=model.__class__.__name__))
                event = None
                vcal_json = None
            else:
                if args.interactive:
                    print(t("extraction.no_alternative_model"))
                else:
                    print(t("extraction.could_not_switch_model"))
                memory_error_occurred = True
        elif vcal_json == "JsonError":
            event = None
            vcal_json = None
            json_error_occurred = False
            print(t("extraction.json_generation_error"))

    if not event and retries >= max_retries:
        vcal_json = "RetryError"
        print(t("extraction.max_retries_reached"))
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
        write_file(f"log/{post_identifier}_prompt.txt", prompt, enabled=getattr(args, "debug_log_extractions", False))
        if args.verbose:
            print_first_lines(prompt, n=None, title=t("extraction.title_prompt"))

        event, vcal_json, elapsed_time = get_event_from_llm_with_retry(
            model, prompt, post_identifier, args
        )
        total_elapsed_time += elapsed_time
        if args.verbose:
            print_first_lines(event, n=None, title=t("extraction.title_event"))
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
                    print_first_lines(single_event, title=t("extraction.title_single_event"))
                if isinstance(single_event, dict):
                    single_event = add_message_to_event_description(single_event, original_content)
                    processed_events.append(adjust_event_times(single_event))
            event = processed_events or None
            if args.verbose:
                print_first_lines(processed_events, title=t("extraction.title_proc_event"))
            break

        write_file(
            f"log/{post_identifier}_fail.vcal",
            json.dumps(vcal_json) if vcal_json else "Failed extraction",
            enabled=getattr(args, "debug_log_extractions", False),
        )
        if not args.interactive:
            return None, vcal_json, total_elapsed_time, False, False, False

        print(t("extraction.llm_failed_extract"))
        choice = _print_context_and_options(
            original_content,
            t("extraction.retry_options_prompt"),
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
        enabled=getattr(args, "debug_log_extractions", False),
    )
    if isinstance(event, (list, tuple)):
        for idx, single_event in enumerate(event, start=1):
            write_file(
                f"log/{model.model_name}/{post_identifier}_{idx}.vcal",
                json.dumps(single_event)
                if isinstance(single_event, (dict, list))
                else str(single_event),
                enabled=getattr(args, "debug_log_extractions", False),
            )
    else:
        write_file(
            f"log/{post_identifier}.vcal",
            json.dumps(event) if isinstance(event, (dict, list)) else str(event),
            enabled=getattr(args, "debug_log_extractions", False),
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
    print(t("extraction.display_summary", summary=event_summary))
    if post_identifier:
        print(t("extraction.display_file", post_identifier=post_identifier))
    print(t("extraction.display_start", start=start_time_local))
    print(t("extraction.display_end", end=end_time_local))
    print(t("extraction.display_model", model=model.model_name))
    if elapsed_time is not None:
        print(
            t(
                "extraction.display_time",
                duration=format_time(elapsed_time),
                seconds=f"{elapsed_time:.2f}",
            )
        )
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
    dedup_identity=None,
    generation=0,
):
    """Extract events, validate their dates, and publish or write them.

    `dedup_identity`/`generation` feed the deterministic event id (see
    deterministic_event_id()). `dedup_identity` defaults to `post_identifier` when not given
    explicitly (web/txt sources, which have no ledger/generation concept - always
    generation=0); the email flow passes mail_identity() and the ledger's tracked
    generation for that identity instead.
    """
    from manage_agenda.events import (
        _validate_event_dates_interactive,
        _validate_event_dates_non_interactive,
        adjust_event_times,
    )

    identity = dedup_identity if dedup_identity is not None else post_identifier

    success = False
    should_process = True
    date_validation_retries = 0
    max_date_validation_retries = 3
    while should_process and not success:
        if date_validation_retries >= max_date_validation_retries:
            print(
                t(
                    "extraction.max_date_validation_retries_reached",
                    max_retries=max_date_validation_retries,
                    post_identifier=post_identifier,
                )
            )
            break

        event, vcal_json, elapsed_time, extraction_success, need_restart, need_another_ai = (
            _extract_event_with_llm_retry(
                args, model, content_text, reference_date_time, post_identifier, subject_for_print
            )
        )
        if vcal_json == "ServiceError":
            from manage_agenda.exceptions import LLMError

            raise LLMError(t("extraction.model_api_no_answer"))
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
                print(t("extraction.no_visit_fits"))
                return None, None
        else:
            events = list(event)
            api_dst, selected_calendars = _selected_calendar(
                args, rules, title=events[0].get("summary") or t("extraction.event_fallback_title")
            )
        calendar_results = []

        if getattr(args, "output", "calendar") == "calendar" and not selected_calendars:
            print(t("extraction.no_calendar_selected"))
        else:
            for idx, single_event in enumerate(events, start=1):
                single_event = adjust_event_times(single_event)
                write_file(
                    f"log/{model.model_name}/{post_identifier}_{idx}.json",
                    json.dumps(single_event),
                    enabled=getattr(args, "debug_log_extractions", False),
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
                        print(t("extraction.date_validation_errors_header", post_identifier=post_identifier))
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
                        # A separate copy per calendar: the id and extendedProperties are
                        # identical across calendars now (the deterministic id is not
                        # calendar-scoped), but a retry-path mutation (e.g. the timezone
                        # correction below) for one calendar must not leak into the next.
                        published, single_result = _publish_event_to_calendar(
                            api_dst,
                            deepcopy(single_event),
                            calendar_id,
                            source_id=identity,
                            generation=generation,
                            event_index=idx,
                        )
                        if not published or (
                            isinstance(single_result, dict) and not single_result.get("success")
                        ):
                            all_published = False
                            break
                        calendar_result.append(single_result)
                    if not all_published:
                        from manage_agenda.exceptions import CalendarError

                        raise CalendarError(t("extraction.calendar_not_updated"))
                    published = True
                else:
                    # Not a debug artifact: this is the actual "-o file" output mode, the
                    # user's requested result, not an optional trail - it always writes
                    # regardless of --debug-log-extractions, and lives under its own
                    # config.output_dir(), not msg_txt_dir()/log/, so
                    # purge_expired_log_files() can never delete it (see base.write_file's
                    # docstring and docs/investigation-limite1.md).
                    from manage_agenda.config import output_dir

                    write_file(
                        f"{model.model_name}/{post_identifier}_{idx}_times.json",
                        json.dumps(single_event),
                        enabled=True,
                        base_dir=output_dir(),
                    )
                    calendar_result = f"{post_identifier}_{idx}_times.json"
                    published = True
                if published:
                    if getattr(args, "output", "calendar") == "calendar":
                        calendar_results.extend(calendar_result)
                        for single_result in calendar_result:
                            if isinstance(single_result, dict) and single_result.get("duplicate"):
                                print(
                                    t(
                                        "extraction.already_on_calendar",
                                        summary=single_event.get("summary"),
                                    )
                                )
                            else:
                                print(t("extraction.calendar_event_created"))
                    else:
                        calendar_results.append(calendar_result)
                        print(
                            t(
                                "extraction.file_created",
                                filename=f"{post_identifier}_{idx}_times.json",
                            )
                        )
                    success = True
                    write_file(file_name, json.dumps(single_event), enabled=getattr(args, "debug_log_extractions", False))

        print(t("extraction.success_debug", success=success))
        if success:
            if args.verbose:
                print(t("extraction.events_debug", events=events))
                print(t("extraction.results_debug", results=calendar_results))
            return events, calendar_results
        return None, None
    return None, None


def _calendar_items(response):
    if not isinstance(response, dict):
        return []
    items = response.get("items")
    return items if isinstance(items, list) else []


def deterministic_event_id(identity, generation, event_index):
    """A Calendar event id derived from (identity, generation, event_index) - the same inputs
    always produce the same id, so re-publishing the same event is idempotent by construction
    instead of relying on Calendar to detect a duplicate insert (it does not guarantee that;
    see docs/investigation-limite1.md, correction 1).

    `identity` is the source message's stable identity (mail_identity() for email, or a
    provider post id for web/txt sources, which have no ledger/generation concept and always
    pass generation=0). `generation` increments each time this identity's tracked events are
    requeued after a manual deletion, so a requeued re-publish never collides with the id of
    the event that was just deleted (see correction 1: id reuse after deletion is not
    guaranteed to be safe, so this design never attempts it).

    Google requires base32hex (lowercase a-v, 0-9), length 5-1024, unique per calendar (not
    globally) - a sha256 digest, base32hex-encoded, is comfortably within that and does not
    need to be scoped by calendar_id itself.
    """
    raw = f"{identity}|{generation}|{event_index}".encode()
    digest = hashlib.sha256(raw).digest()
    return base64.b32hexencode(digest).decode("ascii").lower().rstrip("=")


def _stamp_reconstructible_properties(event, identity, generation, event_index):
    """Properties that let the ledger be rebuilt from Calendar alone (a live event only -
    extendedProperties is not guaranteed to survive on a deleted one, see correction 2), via
    events.list(privateExtendedProperty="origin=manage-agenda").
    """
    private = event.setdefault("extendedProperties", {}).setdefault("private", {})
    private["origin"] = "manage-agenda"
    if identity:
        private["sourceMailId"] = str(identity)
    private["generation"] = str(generation)
    private["eventIndex"] = str(event_index)


def _get_event_if_present(client, calendar_id, event_id):
    """The Event (live or cancelled) at this id, or None if Calendar confirms it does not
    exist (404/410). Any other error is re-raised: proceeding to insert without a confirmed
    "does not exist" answer could silently create a duplicate the tool would never reconcile
    with the deterministic id it expected.
    """
    try:
        return client.events().get(calendarId=calendar_id, eventId=event_id).execute()
    except googleapiclient.errors.HttpError as error:
        status = getattr(getattr(error, "resp", None), "status", None)
        if status in (404, 410):
            return None
        raise


def migrate_one_legacy_event(
    client, calendar_id, event_id, identity, generation, event_index, dry_run=False
):
    """Patch extendedProperties.private onto one pre-existing Calendar event (created before
    deterministic ids/origin stamping existed - see docs/investigation-limite1.md migration
    requirements), and read back event_end from the same fetch. Never touches the event's own
    id - patch() cannot change it, and this function's body never includes one.

    The existing `private` map is fetched and re-sent whole (existing keys plus the new ones),
    rather than a patch body with only the new keys: whether Calendar's PATCH merges
    extendedProperties.private at the individual-key level or replaces the whole map is
    undocumented and unverified (no probe covers it) - sending the complete desired end state
    is correct either way, so this deliberately does not rely on an assumption about it.

    `dry_run=True` still performs the read-only events.get() (needed to log an accurate
    preview and to read event_end), but never calls events.patch() - no Calendar mutation at
    all. See the distinct "would_migrate" status below.

    Returns (status, event_end):
    - ("migrated", event_end): patched successfully; event_end from the live event (may be
      None if the event has neither `end.dateTime` nor `end.date` - unusual, not an error).
    - ("would_migrate", event_end): dry_run only - patch was NOT called; this event would be
      migrated on a real run. The caller must not mark the ref "migrated" on this status, or a
      later real run would skip the very ref the preview said it would touch.
    - ("already_migrated", event_end): the event already carries origin=manage-agenda (e.g. a
      previous partial migration run) - no patch call made, event_end still read from the
      get() that was needed anyway to check.
    - ("gone", None): the event is confirmed deleted (404/410) - nothing to patch or read;
      logged and treated as a normal, non-fatal, non-retried outcome.
    - ("cancelled", event_end): get() returned the event with status "cancelled" (deleted,
      not yet purged by Calendar) - never patched: whether a PATCH on a cancelled event can
      bring it back is unverified (probe (b) territory), and stamping one buys nothing anyway.
      event_end is still read, so the caller can backfill it: once reconcile moves the ref to
      cancelled_events, it is what earns the entry the event_end-based purge margin instead of
      the short recorded_at fallback. The caller leaves the ref un-migrated for reconcile to
      resolve through on_user_delete. This matters most for the explicit `migrate-ledger`
      command, which runs without reconcile first (see sources.migrate_ledger_cli).
    - ("retry", None): an ambiguous error (not a confirmed 404/410) on either call - left
      un-migrated so a future run tries again, the same conservative pattern
      _get_event_if_present uses for the same reason (proceeding on an unconfirmed answer
      risks acting on stale or wrong data).
    """
    try:
        existing = client.events().get(calendarId=calendar_id, eventId=event_id).execute()
    except googleapiclient.errors.HttpError as error:
        status_code = getattr(getattr(error, "resp", None), "status", None)
        if status_code in (404, 410):
            logging.info(f"migrate: {calendar_id}/{event_id} is gone - nothing to patch.")
            return "gone", None
        logging.warning(f"migrate: could not fetch {calendar_id}/{event_id}: {error}")
        return "retry", None
    except Exception as error:
        logging.warning(f"migrate: could not fetch {calendar_id}/{event_id}: {error}")
        return "retry", None

    if not isinstance(existing, dict):
        return "retry", None

    event_end = _event_end_iso(existing)
    if existing.get("status") == "cancelled":
        logging.info(f"migrate: {calendar_id}/{event_id} is cancelled - not patched, left to reconcile.")
        return "cancelled", event_end

    private = dict((existing.get("extendedProperties") or {}).get("private") or {})
    if private.get("origin") == "manage-agenda":
        return "already_migrated", event_end

    body = {"extendedProperties": {"private": private}}
    _stamp_reconstructible_properties(body, identity, generation, event_index)
    if dry_run:
        logging.info(
            f"DRY RUN migrate: would patch {calendar_id}/{event_id} with "
            f"extendedProperties.private={body['extendedProperties']['private']}"
        )
        return "would_migrate", event_end
    try:
        client.events().patch(calendarId=calendar_id, eventId=event_id, body=body).execute()
    except Exception as error:
        logging.warning(f"migrate: could not patch {calendar_id}/{event_id}: {error}")
        return "retry", None
    return "migrated", event_end


# Token files a dry run has already reported legacy tokens for - see sync_calendar_changes().
# A real run drops them on its first call, so it warns once; a dry run leaves them on disk,
# and would otherwise repeat the same warning for every calendar it syncs.
_dry_run_legacy_warned = set()


def calendar_sync_state_file():
    """Calendar API sync tokens, one per (calendar account, calendar id), used to detect
    deleted events incrementally. Stored as {"accounts": {account_key: {calendar_id: token}}},
    account_key being connections.calendar_account_key() of the connection that obtained the
    token - see sync_calendar_changes()."""
    from manage_agenda.config import data_dir

    return data_dir() / "calendar_sync_tokens.json"


def _read_sync_state(path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_sync_tokens(path):
    """{account_key: {calendar_id: token}} - see calendar_sync_state_file()."""
    accounts = _read_sync_state(path).get("accounts")
    if not isinstance(accounts, dict):
        return {}
    return {
        str(account): {str(calendar_id): str(token) for calendar_id, token in tokens.items()}
        for account, tokens in accounts.items()
        if isinstance(tokens, dict)
    }


def _legacy_sync_tokens(path):
    """Tokens from the previous format, {"tokens": {calendar_id: token}}, keyed by calendar id
    alone - see sync_calendar_changes() for why they are abandoned, never reused."""
    tokens = _read_sync_state(path).get("tokens")
    return {str(key): str(value) for key, value in tokens.items()} if isinstance(tokens, dict) else {}


def _save_sync_tokens(path, tokens):
    """Writes the {"accounts": ...} format only - any legacy "tokens" key is dropped."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"accounts": tokens}, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


# How far back a bootstrap (or post-410 reseed) full listing reaches. Calendar's API forbids
# combining timeMin/timeMax with syncToken at all, so this bound only ever applies to the
# unavoidable full listing - every later incremental call is a cheap, unbounded-by-us delta.
# A tracked ref missing from that listing is not assumed deleted: _should_confirm_missing()
# decides whether it is worth one targeted events.get() - by its event_end when recorded,
# otherwise by its recorded_at falling within this same window.
_SYNC_BOOTSTRAP_WINDOW_DAYS = 90

# How long after its event's end a ledger entry is kept (purge_expired_ledger_entries, via
# sources._entry_purge_after). Defined here, not in sources.py (which re-exports it), because
# the bootstrap uses it too and sources.py imports this module at load time.
LEDGER_EVENT_END_MARGIN_DAYS = 30


def _bootstrap_cutoff():
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=_SYNC_BOOTSTRAP_WINDOW_DAYS
    )


def _bootstrap_time_min():
    return _bootstrap_cutoff().isoformat().replace("+00:00", "Z")


def _is_within_bootstrap_window(recorded_at):
    """Whether a tracked ref is recent enough that the bootstrap listing should cover it - the
    fallback _should_confirm_missing() uses for a ref with no event_end. Reconcile only:
    migration (sources.migrate_legacy_ledger_entries) attempts every un-migrated ref, whatever
    its age.

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


def _parse_iso_datetime(value):
    """A tz-aware datetime from an ISO date or datetime string, or None if unparseable."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.datetime.fromisoformat(text + "T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _should_confirm_missing(tracked):
    """Whether a tracked ref absent from a bootstrap listing is worth one events.get().

    `tracked` is the ref's {"recorded_at", "event_end"} (either may be missing). With an
    event_end: yes while the event is still to come or within the ledger's purge margin
    (event_end + LEDGER_EVENT_END_MARGIN_DAYS not yet past) - i.e. for as long as its entry is
    kept, whatever recorded_at says: an event planned long ago for a date still ahead is
    exactly the one whose deletion matters. Past that margin the entry is about to be purged,
    and a lookup buys nothing. Without an event_end (refs recorded before it was tracked, and
    not migrated), fall back to recorded_at within the bootstrap window
    (_is_within_bootstrap_window). Either way the lookups stay bounded by current activity,
    never by the ledger's whole history."""
    event_end = _parse_iso_datetime(tracked.get("event_end"))
    if event_end is not None:
        cutoff = event_end + datetime.timedelta(days=LEDGER_EVENT_END_MARGIN_DAYS)
        return cutoff > datetime.datetime.now(datetime.timezone.utc)
    return _is_within_bootstrap_window(tracked.get("recorded_at"))


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
    """Tell a genuine deletion apart from "just outside the bootstrap listing's time window" -
    and, among genuine confirmations, tell "Calendar knows this was cancelled" apart from
    "Calendar has no record of this id at all" (see docs/investigation-limite1.md §8).

    One targeted get() per id - only for the ids a bounded bootstrap listing did not account
    for at all, typically a handful, never the whole tracked set.

    Returns (cancelled_ids, unknown_ids):
    - cancelled_ids: the id came back with an explicit status "cancelled" - Calendar has a
      tombstone for it, a genuine confirmed deletion.
    - unknown_ids: the id came back 404/410 - Calendar has no record of it at all. This is
      NOT proof the user deleted it: it is equally consistent with the event never having
      been created in the first place (a past bug, ledger corruption, a wrong/stale
      event_id), and must never be treated as a user deletion by the caller - see
      reconcile_handled_events()'s "unknown_event" resolution.

    Any other error is inconclusive and the id is left out of both sets, the same
    conservative default used everywhere else here, so a transient API problem cannot cause a
    message to be silently reprocessed (or misclassified as unknown).
    """
    cancelled = set()
    unknown = set()
    for event_id in missing_ids:
        try:
            response = client.events().get(calendarId=calendar_id, eventId=event_id).execute()
        except googleapiclient.errors.HttpError as error:
            if getattr(getattr(error, "resp", None), "status", None) in (404, 410):
                unknown.add(event_id)
            continue
        except Exception:
            continue
        if (response or {}).get("status") == "cancelled":
            cancelled.add(event_id)
    return cancelled, unknown


def sync_calendar_changes(api_dst, calendar_id, tracked_events=None, path=None, dry_run=False):
    """Ids that need to be treated as deleted on one calendar, via Calendar's incremental sync.

    This is the mechanism sync clients use: one cheap call returns only what changed since a
    stored syncToken, regardless of how many events are being tracked - not one check per known
    event. Once a valid token exists, deletions are exactly the ids that come back with
    status "cancelled" in that delta.

    The first call for a calendar (no token yet), or one made after a stored token has expired
    (Calendar answers 410 Gone), has no "since when" to diff against, so instead it does one
    bounded full listing (see _SYNC_BOOTSTRAP_WINDOW_DAYS) to seed a fresh token - covering
    deletions that happened before this tool ever ran, or during the gap before a reseed. Every
    listing passes showDeleted=True, so a deletion normally shows up as a "cancelled" item.
    A tracked id absent from that listing is never taken as deleted: it is confirmed with one
    targeted lookup (_confirm_missing_ids) when _should_confirm_missing() says it still matters
    - its event_end not yet past the ledger's purge margin, or, with no event_end recorded, its
    recorded_at within the bootstrap window - and otherwise left alone rather than paying for a
    lookup every single reseed, forever, as the ledger accumulates history. Any other API error
    is conservative: nothing is reported and the stored token, if any, is left untouched.

    `tracked_events` is {event_id: {"recorded_at": ..., "event_end": ...}} for this calendar
    (either key may be missing) - taken from the ledger refs (see _extract_event_refs), used
    only to decide which missing ids are worth confirming.

    Returns (cancelled_ids, unknown_ids) - see _confirm_missing_ids for what distinguishes
    them. A syncToken delta itself only ever reports items Calendar has an explicit status
    for, so `unknown_ids` is only ever non-empty via the bootstrap path's targeted
    confirmation of ids missing from a full listing.

    Tokens are stored per (calendar account, calendar id), the account being read from the
    connection making the call (`api_dst.src`, see connections.calendar_account_key) - never
    from the caller. A calendar id alone doesn't identify a calendar: "primary" is every
    account's own primary calendar, so a token obtained by one account must never be handed to
    another. Tokens from the previous format, keyed by calendar id alone, can't be attributed
    to an account after the fact: the first call that finds any abandons them all - logged,
    and dropped from the file - and each calendar's next sync re-bootstraps from the
    _SYNC_BOOTSTRAP_WINDOW_DAYS listing like a first run. When the connection has no usable
    account key, no token is read or stored: every call bootstraps.

    `dry_run=True` (reconcile under --dry-run-ledger) makes every Calendar call a real call
    would - the listing and the targeted lookups are read-only - but writes nothing to the
    token file: no new token, and legacy tokens are ignored exactly as a real call would ignore
    them, but not dropped from the file. Advancing a token during a preview would make the real
    run that follows ask Calendar only for what changed since the preview, so the deletions the
    preview reported - notably the first bootstrap's whole backlog - would never be applied.
    """
    path = Path(path) if path else calendar_sync_state_file()
    tokens = _load_sync_tokens(path)
    legacy_tokens = _legacy_sync_tokens(path)
    if legacy_tokens and not (dry_run and str(path) in _dry_run_legacy_warned):
        prefix = "DRY RUN: would abandon" if dry_run else "Abandoning"
        logging.warning(
            f"{prefix} {len(legacy_tokens)} Calendar sync token(s) keyed by calendar id alone "
            f"({', '.join(sorted(legacy_tokens))}) in {path}: a token can't be attributed to a "
            "calendar account after the fact, so none is reused. The next sync of each calendar "
            f"re-bootstraps from a {_SYNC_BOOTSTRAP_WINDOW_DAYS}-day listing."
        )
        if dry_run:
            _dry_run_legacy_warned.add(str(path))
        else:
            _save_sync_tokens(path, tokens)
    account_key = calendar_account_key(getattr(api_dst, "src", None))
    if account_key is None:
        logging.info(
            f"No calendar account key for this connection: no sync token read or stored for "
            f"{calendar_id}, bootstrapping."
        )
    account_tokens = tokens.setdefault(account_key, {}) if account_key is not None else {}
    token = account_tokens.get(calendar_id)
    client = api_dst.getClient()
    tracked_events = dict(tracked_events or {})

    def _store(fresh_token):
        if account_key is None or dry_run:
            return
        account_tokens[calendar_id] = fresh_token
        _save_sync_tokens(path, tokens)

    def _bootstrap():
        try:
            items, fresh_token = _list_all_pages(
                client, calendar_id, time_min=_bootstrap_time_min()
            )
        except Exception as error:
            logging.warning(f"Could not seed a Calendar sync token for {calendar_id}: {error}")
            return set(), set()
        if fresh_token:
            _store(fresh_token)
        else:
            logging.warning(f"Calendar did not return a sync token for {calendar_id}.")
        listed_ids = {item.get("id") for item in items if item.get("id")}
        cancelled_ids = {
            item.get("id") for item in items if item.get("status") == "cancelled" and item.get("id")
        }
        missing_ids = set(tracked_events) - listed_ids
        # Absence from the listing is never a deletion by itself: a missing ref is only ever
        # resolved by what one events.get() says (_confirm_missing_ids), and only looked up at
        # all while it still matters (_should_confirm_missing).
        confirmable_ids = {
            event_id
            for event_id in missing_ids
            if _should_confirm_missing(tracked_events.get(event_id) or {})
        }
        if confirmable_ids:
            confirmed_cancelled, confirmed_unknown = _confirm_missing_ids(
                client, calendar_id, confirmable_ids
            )
        else:
            confirmed_cancelled, confirmed_unknown = set(), set()
        return cancelled_ids | confirmed_cancelled, confirmed_unknown

    if not token:
        return _bootstrap()

    try:
        items, fresh_token = _list_all_pages(client, calendar_id, sync_token=token)
    except googleapiclient.errors.HttpError as error:
        if getattr(getattr(error, "resp", None), "status", None) == 410:
            logging.info(f"Calendar sync token expired for {calendar_id}, reseeding.")
            account_tokens.pop(calendar_id, None)
            return _bootstrap()
        logging.warning(f"Could not fetch Calendar changes for {calendar_id}: {error}")
        return set(), set()
    except Exception as error:
        logging.warning(f"Could not fetch Calendar changes for {calendar_id}: {error}")
        return set(), set()

    if fresh_token:
        _store(fresh_token)
    else:
        logging.warning(f"Calendar did not return a sync token for {calendar_id}.")

    cancelled_ids = {
        item.get("id") for item in items if item.get("status") == "cancelled" and item.get("id")
    }
    return cancelled_ids, set()


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
    api_dst = select_api(args, "gcalendar", rules=rules, title=t("extraction.select_calendar_title"))
    selected_calendars = select_calendars(api_dst, title=title, args=args)
    return api_dst, selected_calendars


def _visits_from_occupancy(event, content_text, args, rules):
    """Choose a visit before the next occupation, inside the configured hours."""
    from manage_agenda.scheduling import (
        availability_for,
        plan_room_visits,
    )

    payload = event[0] if isinstance(event, (list, tuple)) else event
    sender = _from_header(content_text)
    constraints = availability_for(sender)
    api_dst = None
    selected_calendars = []
    busy = []
    api_dst, selected_calendars = _selected_calendar(args, rules, title=t("extraction.visit_title"))
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


def _event_end_iso(event):
    """The event's own end date/time, for the ledger to purge entries by - see
    docs/investigation-limite1.md amendment 2: local state expires on event end date +
    margin, never on recorded_at.

    Callers pass whichever `end` they have authority over for that path: Calendar's own
    `existing["end"]` for a duplicate (the id already existed - Calendar's value is
    authoritative), or the locally-built body actually sent to `_insert` for a fresh insert
    (post-timezone-correction retry, if any - the exact value manage-agenda asked Calendar to
    create). The two can disagree by timezone offset on a retried insert; both are within the
    same wall-clock day, which is well inside the purge margin either way.
    """
    end = event.get("end") if isinstance(event, dict) else None
    if not isinstance(end, dict):
        return None
    return end.get("dateTime") or end.get("date") or None


def _publish_event_to_calendar(
    api_dst, event, selected_calendar, source_id="", generation=0, event_index=0
):
    """Publish an event under a deterministic id, skipping one that is already on the
    calendar and refusing to insert over a colliding (even cancelled) id.

    `source_id` is the identity generation/event_index are scoped to - mail_identity() for
    email (ledger-tracked, generation bumped on requeue), or a plain per-run source id for
    web/txt sources (which have no ledger/requeue concept and always pass generation=0).
    """
    from manage_agenda.events import _ensure_valid_event_timezones

    event_id = deterministic_event_id(source_id, generation, event_index) if source_id else ""
    # Stamped even without a source_id (no deterministic id to check/insert under): origin
    # alone still marks the event as manage-agenda's for events.list(privateExtendedProperty=
    # "origin=manage-agenda") to find, even though there is no sourceMailId to key it by.
    _stamp_reconstructible_properties(event, source_id, generation, event_index)
    if event_id:
        event["id"] = event_id

        client = api_dst.getClient()
        try:
            existing = _get_event_if_present(client, selected_calendar, event_id)
        except Exception as error:
            logging.warning(f"Could not check for an existing event at id {event_id}: {error}")
            return False, {
                "success": False,
                "error_message": str(error),
                "calendar_id": selected_calendar,
                "event_id": event_id,
            }

        if existing is not None:
            if isinstance(existing, dict) and existing.get("status") == "cancelled":
                logging.warning(
                    f"Deterministic id {event_id} collides with a cancelled event on "
                    f"{selected_calendar} - not inserting. This should be rare (a fresh "
                    "requeue always changes the generation); if it recurs, the identity or "
                    "generation bookkeeping likely drifted."
                )
                return False, {
                    "success": False,
                    "error_message": "id_collision_with_cancelled_event",
                    "calendar_id": selected_calendar,
                    "event_id": event_id,
                }
            link = existing.get("htmlLink", "") if isinstance(existing, dict) else ""
            existing_end = existing.get("end") if isinstance(existing, dict) else None
            return True, {
                "success": True,
                "duplicate": True,
                "post_url": link,
                "calendar_id": selected_calendar,
                "event_id": event_id,
                "event_end": _event_end_iso({"end": existing_end}) or _event_end_iso(event),
            }

    def _insert(body):
        result = api_dst.publishPost(post={"event": body, "idCal": selected_calendar}, api=api_dst)
        if isinstance(result, dict) and result.get("success"):
            result.setdefault("calendar_id", selected_calendar)
            result.setdefault(
                "event_id", event_id or (result.get("raw_response") or {}).get("id", "")
            )
            result.setdefault("event_end", _event_end_iso(body))
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
