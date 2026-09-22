import datetime
import email
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import dateparser
from socialModules import moduleHtml
from socialModules.configMod import select_from_list
from socialModules.moduleContent import display_posts
from socialModules.moduleRules import moduleRules

from manage_agenda.base import write_file
from manage_agenda.config import config
from manage_agenda.connections import prepare_calendar, select_api
from manage_agenda.extraction import _process_event_with_llm_and_calendar
from manage_agenda.i18n import t
from manage_agenda.llm import select_llm
from manage_agenda.web import reduce_html


@dataclass
class Args:
    """Arguments container for CLI commands."""

    interactive: bool = False
    delete: bool | None = None
    source: str | None = None
    ai: str | None = None
    verbose: bool = False
    destination: str | None = None
    text: str | None = None
    output: str = "calendar"
    force_refresh: bool = False
    rule: str | None = None
    model: str | None = None
    reconfigure: bool = False
    dry_run: bool = False


def get_add_sources(rules=None):
    """Returns a list of available sources for the add command."""
    rules = rules or moduleRules.from_config()
    email_sources = rules.selectRule(["gmail", "imap"])
    return email_sources, [("web/http", "set", "(Enter URLs or leave empty)")] + [
        ("text", "set", "(enter filenames or leave empty)")
    ]


def print_first_lines(content, content_type="content", *, n=10, title=None):
    """Prints the first n lines of the given content, or all lines if n is None."""
    if not isinstance(content, str):
        if isinstance(content, list) and content and isinstance(content[0], dict):
            for i, item in enumerate(content):
                print_first_lines(item, n=n, title=f"{title or content_type} {i + 1}/{len(content)}")
            return
        if isinstance(content, (dict, list)):
            content = json.dumps(content, indent=2)
        else:
            content = str(content)
    header = title or t("sources.first_n_lines_header", n=n, content_type=content_type)
    print(t("sources.section_header", header=header))
    for i, line in enumerate(content.splitlines()):
        if n is not None and i >= n:
            break
        print(line)
    print("-------------------------------------\n")


# Backward-compatible alias
print_first_10_lines = print_first_lines


def _get_msgs_from_folder(args, source_name, rules=None):
    """Helper function to get posts stored in some folder."""
    # FIXME: maybe a folder argument?

    if source_name and isinstance(source_name, list):
        txt_files = source_name
    else:
        target_dir = Path(config.MSG_TXT_DIR)
        txt_files = target_dir.glob("*.txt")

    posts = []
    for file_path in txt_files:
        file_path = Path(file_path)
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
            file_name = file_path.stem
            posts.append([file_name, content])

    if not posts:
        if not os.path.exists(target_dir):
            print(t("sources.no_such_directory", target_dir=target_dir))
        else:
            print(t("sources.no_posts_in_directory", target_dir=target_dir))
        posts = None

    return None, posts


def _get_events_from_calendar(args, api_src, calendar=None):
    """Helper function to get events from a specific calendar."""
    "FIXME: maybe a folder argument?"

    if calendar:
        api_src.setCalendar(calendar)
    api_src.setPosts()
    posts = api_src.getPosts()

    return posts


IMAP_MATCH_LIMIT = 30
IMAP_SCAN_WINDOW = 200
_IMAP_HEADER = "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM DATE SUBJECT)])"


def handled_mail_file():
    """Message identities already sent through extraction, with the Calendar events they created."""
    from manage_agenda.config import DATA_DIR

    return Path(DATA_DIR) / "handled_mail_ids.json"


def _imap_marker_history_file():
    """Per-account (not per-message) record of the last IMAP marker mode used - bounded by
    the number of configured accounts, never by mail volume. See
    check_marker_mode_transition()."""
    from manage_agenda.config import DATA_DIR

    return Path(DATA_DIR) / "imap_marker_history.json"


def _load_marker_history(path=None):
    path = Path(path) if path else _imap_marker_history_file()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    accounts = data.get("accounts") if isinstance(data, dict) else None
    return {str(k): str(v) for k, v in accounts.items()} if isinstance(accounts, dict) else {}


def _save_marker_history(history, path=None):
    path = Path(path) if path else _imap_marker_history_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"accounts": history}, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def imap_marker_account_key(selected_source, source_details):
    """A stable-enough per-account key for check_marker_mode_transition(): the configured
    rule name when there is one, else folder+channel (accounts without an explicit
    selected_source - e.g. auto-selected via select_api - are not distinguished from one
    another beyond that, a documented best-effort limitation, not a hard guarantee)."""
    if selected_source:
        return str(selected_source)
    folder = source_details.get("folder") or source_details.get("channel") or "INBOX"
    return f"folder:{folder}"


def check_marker_mode_transition(account_key, current_mode, path=None):
    """Refuses (returns False) a switch away from `flag_seen` (today's `mark: seen`,
    ledger-only exclusion) to `keyword` or `folder` (server-side SEARCH exclusion) for an
    account with marker history on record, until the §6 mailbox-side migration - retroactively
    applying the new marker to every message still tracked in the ledger - has been done. That
    migration is documented but not implemented (see docs/investigation-limite1.md §6), so
    this is a fail-closed guard, not a fix: without it, a ledger entry that ages past its purge
    margin (purge_expired_ledger_entries) makes its still-unmoved, flag-only-marked message
    visible to a fresh scan again, and if the LLM's extraction isn't perfectly deterministic
    across runs (a different event count/order shifts event_index), the recomputed
    deterministic id can differ from the one already on Calendar - a genuine duplicate event,
    not merely a caught collision.

    Any other transition is allowed: an unconfigured account switching to a marker, or a
    switch between `keyword` and `folder`, don't share flag_seen's "message never physically
    moves, exclusion is ledger-only" property - a purged-then-resurfaced message under either
    of those is still excluded by the new mode's own server-side SEARCH criterion regardless
    of ledger state.

    The first time `account_key` is seen, the current mode is simply recorded and the scan is
    allowed - there is no history yet to migrate away from. This means the guard is
    forward-only: it protects a `mark: seen` -> `keyword`/`folder` switch made AFTER this
    version has run at least once for that account. A switch already made before upgrading is
    recorded as if `keyword`/`folder` had always been the mode and is never caught - the
    ledger has no per-entry record of which marker was used, by design, so there is nothing
    to detect that switch from after the fact.

    Not gated on any caller's dry_run - this only ever records the current marker mode, never
    the user's mail/calendar data, and it is a small, per-account (not per-message) file.
    """
    history = _load_marker_history(path)
    previous_mode = history.get(account_key)
    normalized_current = current_mode or "none"
    if previous_mode is None:
        history[account_key] = normalized_current
        _save_marker_history(history, path)
        return True
    if previous_mode == "flag_seen" and current_mode in ("keyword", "folder"):
        return False
    if previous_mode != normalized_current:
        history[account_key] = normalized_current
        _save_marker_history(history, path)
    return True


def _load_state(path):
    """Read the handled-mail ledger, migrating the old id-only format in memory.

    New entries look like:
    {"events": [{"calendar_id": ..., "event_id": ..., "event_end": ...}], "status": "created",
    "generation": 0, "recorded_at": "..."}.
    A message with no recorded event ("status": "no_event", e.g. too old or empty content) or one
    read from the legacy {"ids": [...]} format ("status": "legacy") is always kept as handled: there
    is nothing to check against Calendar, so behavior for those stays exactly as before.

    `generation` (default 0) feeds the deterministic Calendar event id - it is bumped only by
    the requeue resolution step, never here, so an entry with no `generation` key (written
    before that field existed) is simply generation 0, identical to a freshly created entry.

    `recorded_at` (entry-level, set once when the identity was first recorded, never updated) is
    the purge fallback for entries with no event end date to purge by - "no_event" entries, or a
    "created"/"source_lost" entry whose refs predate the `event_end` field. Absent on entries
    read from the legacy {"ids": [...]} format or an older ledger file written before this field
    existed - see purge_expired_ledger_entries(), which never purges an entry it has no age
    signal for at all.

    `cancelled_events` (same shape as `events`) holds the refs of events reconcile confirmed
    deleted under on_user_delete="ignore" - kept, not discarded, so their event_end still
    earns the entry the longer purge margin (see _entry_purge_after) and so a future manual
    `restore` command has an id to act on. A "requeue" resolution clears them instead - it
    deliberately abandons the old ids, computing a fresh one from the bumped generation.

    `imap_locator` ({"folder": ..., "uidvalidity": ..., "uid": ...}), when present, is the
    COPYUID-derived locator folder-mode marking captured at move time - see
    remember_handled_mail(). Consumed (and then cleared) by the requeue un-marking step.
    """
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("messages"), dict):
        state = {}
        for identity, entry in data["messages"].items():
            if isinstance(entry, dict):
                events = [ev for ev in (entry.get("events") or []) if isinstance(ev, dict)]
                cancelled_events = [
                    ev for ev in (entry.get("cancelled_events") or []) if isinstance(ev, dict)
                ]
                status = entry.get("status") or ("created" if events else "no_event")
                try:
                    generation = int(entry.get("generation") or 0)
                except (TypeError, ValueError):
                    generation = 0
                recorded_at = entry.get("recorded_at")
                imap_locator = entry.get("imap_locator")
            else:
                events, cancelled_events, status, generation, recorded_at, imap_locator = (
                    [],
                    [],
                    "no_event",
                    0,
                    None,
                    None,
                )
            parsed = {"events": events, "status": status, "generation": generation}
            if cancelled_events:
                parsed["cancelled_events"] = cancelled_events
            if isinstance(recorded_at, str) and recorded_at:
                parsed["recorded_at"] = recorded_at
            if isinstance(imap_locator, dict) and imap_locator:
                parsed["imap_locator"] = imap_locator
            state[str(identity)] = parsed
        return state
    ids = data.get("ids") if isinstance(data, dict) else None
    if isinstance(ids, list):
        return {str(item): {"events": [], "status": "legacy", "generation": 0} for item in ids}
    return {}


def _save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"messages": state}, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def load_handled_mail_state(path=None):
    """The full handled-mail ledger: identity -> {"events": [...], "status": "..."}."""
    return _load_state(Path(path) if path else handled_mail_file())


def mail_identity(post):
    """Stable id for a message: Message-ID, otherwise a hash of From, Date and Subject."""
    message = post[1] if isinstance(post, tuple) and len(post) >= 2 else post
    if not hasattr(message, "get"):
        return ""
    message_id = message.get("Message-ID") or message.get("Message-Id") or message.get("id") or ""
    message_id = str(message_id).strip().strip("<>")
    if message_id:
        return message_id
    parts = [str(message.get(key) or "") for key in ("From", "Date", "Subject")]
    if not any(parts):
        return ""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def load_handled_mail_ids(path=None):
    """Every identity on record, regardless of whether its Calendar event still exists.

    Use reconcile_handled_events() instead when a Calendar connection is available: it drops
    identities whose recorded events have all been deleted, so those messages are offered again.
    """
    return set(load_handled_mail_state(path).keys())


def remember_handled_mail(identity, path=None, events=None, imap_locator=None):
    """Record that a message identity was handled, with the Calendar events it created, if any.

    `events` is a list of {"calendar_id": ..., "event_id": ..., "event_end": ...}. Without it,
    the message is recorded as handled with no known event (its identity is skipped, but never
    un-skipped, since there is nothing to check against Calendar).

    `imap_locator` (e.g. {"folder": ..., "uidvalidity": ..., "uid": ...}), when given, is
    stored on the entry - the COPYUID-derived locator folder-mode marking captured while
    moving the message, so a future requeue can relocate it by UID instead of searching (see
    _imap_move_to_folder_safely / the un-marking step in process_email_cli). Always passed
    alongside `events` in the same call - never a separate call for the same identity, or the
    "already recorded, nothing changed" early-return below would silently drop it.

    `recorded_at` is stamped once, the first time this identity is recorded, and never touched
    again on later calls (e.g. adding more events to an already-known identity) - it is the
    purge fallback for entries with no event end date to purge by, see
    purge_expired_ledger_entries().
    """
    if not identity:
        return
    path = Path(path) if path else handled_mail_file()
    state = _load_state(path)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    entry = state.get(
        identity, {"events": [], "status": "no_event", "generation": 0, "recorded_at": now}
    )
    locator_changed = bool(imap_locator) and entry.get("imap_locator") != imap_locator
    if imap_locator:
        entry["imap_locator"] = imap_locator
    if events:
        merged = list(entry.get("events") or [])
        # Dedup by (calendar_id, event_id), not whole-dict equality: two refs for the same
        # event recorded at different moments carry different `recorded_at` timestamps and
        # would never compare equal, so the same ref would pile up on every re-run.
        seen_keys = {(ref.get("calendar_id"), ref.get("event_id")) for ref in merged}
        for ref in events:
            key = (ref.get("calendar_id"), ref.get("event_id"))
            if key not in seen_keys:
                merged.append(ref)
                seen_keys.add(key)
        if (
            merged == entry.get("events")
            and entry.get("status") == "created"
            and identity in state
            and not locator_changed
        ):
            return
        entry["events"] = merged
        entry["status"] = "created"
    elif identity in state and not locator_changed:
        return
    state[identity] = entry
    _save_state(path, state)


def forget_handled_mail(identity, path=None):
    """Fully remove an identity from the ledger - used once a requeue's un-marking step
    succeeds, so the message goes through the normal scan/dedup pipeline on its next
    appearance rather than a separate parallel path (see docs/investigation-limite1.md - the
    design explicitly rules out a second extraction path)."""
    if not identity:
        return
    path = Path(path) if path else handled_mail_file()
    state = _load_state(path)
    if identity not in state:
        return
    del state[identity]
    _save_state(path, state)


def mark_events_restored(identity, restored_refs, path=None):
    """Move `restored_refs` (a subset of the identity's cancelled_events, confirmed restored
    by the manual `restore` command - see restore_deleted_event_cli) back into `events`, so
    the identity is tracked exactly like any other "created" entry again: reconcile
    re-confirms it via syncToken like any other tracked event, and dedup/purge treat it
    normally from here on. Refs not in `restored_refs` (e.g. a multi-event identity where only
    some events were restorable) stay in `cancelled_events`, untouched."""
    if not identity or not restored_refs:
        return
    path = Path(path) if path else handled_mail_file()
    state = _load_state(path)
    entry = state.get(identity)
    if entry is None:
        return
    restored_keys = {(ref.get("calendar_id"), ref.get("event_id")) for ref in restored_refs}
    remaining_cancelled = [
        ref
        for ref in entry.get("cancelled_events") or []
        if (ref.get("calendar_id"), ref.get("event_id")) not in restored_keys
    ]
    current_events = list(entry.get("events") or [])
    seen_keys = {(ref.get("calendar_id"), ref.get("event_id")) for ref in current_events}
    for ref in restored_refs:
        key = (ref.get("calendar_id"), ref.get("event_id"))
        if key not in seen_keys:
            current_events.append(ref)
            seen_keys.add(key)
    entry["events"] = current_events
    entry["status"] = "created"
    if remaining_cancelled:
        entry["cancelled_events"] = remaining_cancelled
    elif "cancelled_events" in entry:
        del entry["cancelled_events"]
    state[identity] = entry
    _save_state(path, state)


def _extract_event_refs(calendar_result):
    """Pull {calendar_id, event_id, recorded_at, event_end} out of the per-event calendar
    publishing results.

    recorded_at (when this tool created/confirmed the ref, not the event's own start time) lets
    reconciliation later tell "old enough that a bootstrap listing wouldn't cover it anyway" apart
    from "recent and worth a targeted check" - without it, that distinction is impossible and a
    reseed's confirmation cost would grow with the whole ledger's history instead of its recent
    activity.

    event_end (the event's own end date/time, not recorded_at) is what the ledger purges
    entries by - see docs/investigation-limite1.md amendment 2. Absent when the publishing
    result didn't carry one (e.g. an older ref format, or a source that predates this field) -
    the purge step falls back to recorded_at for those, with a short margin.
    """
    refs = []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    for result in calendar_result or []:
        if not isinstance(result, dict):
            continue
        calendar_id = result.get("calendar_id")
        event_id = result.get("event_id") or (result.get("raw_response") or {}).get("id")
        if calendar_id and event_id:
            ref = {"calendar_id": calendar_id, "event_id": str(event_id), "recorded_at": now}
            event_end = result.get("event_end")
            if event_end:
                ref["event_end"] = event_end
            refs.append(ref)
    return refs


def reconcile_handled_events(
    args, path=None, sync_state_path=None, on_user_delete=None, dry_run=False
):
    """Resolve messages whose recorded Calendar events have all been deleted, per
    `on_user_delete` (default from config.Config.ON_USER_DELETE, itself defaulting to
    "ignore" - see docs/investigation-limite1.md, this default was explicitly validated by
    the user, never chosen unilaterally):

    `dry_run=True` still reads from Calendar (sync_calendar_changes - read-only, and its own
    syncToken bookkeeping is left as-is regardless, since it holds no user-visible data and
    advancing it doesn't affect the ledger or Calendar) and still computes every resolution
    exactly as a real call would (`still_handled` is accurate either way), but never calls
    `_save_state` - the ledger file is not written. Every identity whose resolution would have
    written something is logged instead.

    - "ignore": the message stays marked processed (its identity stays in `still_handled`,
      excluded from future scans exactly like a "no_event" entry) and the deletion stands.
      There is no way to tell an accidental deletion from a deliberate one, so recreating the
      event by default would make a deliberate deletion impossible to keep - this is the
      failure mode "limite 1" names, and `ignore` is what prevents it.
    - "requeue": the identity's `generation` is bumped (so a future re-publish computes a
      fresh deterministic id, never colliding with the deleted one - see
      deterministic_event_id()) and the entry is marked "pending_requeue", *not* added to
      `still_handled` and *not* deleted. The entry stays in the ledger so the caller
      (process_email_cli, which already holds the account's api_src/source_details) can find
      it and un-mark the source message - reconcile itself never touches any mailbox.

    Messages with no recorded event (too old, empty content, output=file, or migrated from the
    legacy ledger format) are left untouched: there is nothing to check, so they stay skipped.

    Uses Calendar's incremental sync (syncToken) - the mechanism sync clients use - to learn
    what was cancelled since the last run: one cheap call per calendar, regardless of how many
    events are on record, instead of one check per known event.
    """
    on_user_delete = on_user_delete or config.ON_USER_DELETE
    path = Path(path) if path else handled_mail_file()
    state = _load_state(path)
    api_dst = getattr(args, "calendar_api", None)
    client = api_dst.getClient() if api_dst is not None else None
    if client is None:
        return set(state.keys())

    from manage_agenda.extraction import sync_calendar_changes

    tracked_by_calendar = {}
    for entry in state.values():
        for ev in entry.get("events") or []:
            calendar_id, event_id = ev.get("calendar_id"), ev.get("event_id")
            if calendar_id and event_id:
                tracked_by_calendar.setdefault(calendar_id, {})[event_id] = ev.get("recorded_at")

    cancelled_by_calendar = {
        calendar_id: sync_calendar_changes(
            api_dst, calendar_id, tracked_events=tracked_events, path=sync_state_path
        )
        for calendar_id, tracked_events in tracked_by_calendar.items()
    }

    still_handled = set()
    changed = False
    for identity in list(state.keys()):
        entry = state[identity]
        events = entry.get("events") or []
        if not events:
            still_handled.add(identity)
            continue
        remaining = [
            ev
            for ev in events
            if ev.get("event_id") not in cancelled_by_calendar.get(ev.get("calendar_id"), set())
        ]
        if remaining:
            still_handled.add(identity)
            if len(remaining) != len(events):
                partially_cancelled = len(events) - len(remaining)
                prefix = "DRY RUN " if dry_run else ""
                logging.info(
                    f"{prefix}reconcile: {identity}: {partially_cancelled} of {len(events)} "
                    "tracked event(s) cancelled, keeping the identity handled for the rest."
                )
                entry["events"] = remaining
                changed = True
            continue

        # Every tracked event for this identity was cancelled - a user deletion.
        changed = True
        prefix = "DRY RUN " if dry_run else ""
        if on_user_delete == "requeue":
            # Deliberately abandons the old ids - a requeue always computes a fresh
            # deterministic id from the bumped generation, so there is nothing to keep them
            # for; see deterministic_event_id()'s "never reuse a deleted event's id" rule.
            entry["events"] = []
            entry["status"] = "pending_requeue"
            entry["generation"] = int(entry.get("generation") or 0) + 1
            logging.info(f"{prefix}{identity}: event deleted, requeueing (generation bumped).")
            # Deliberately not added to still_handled - the caller is expected to un-mark the
            # source message so the next scan can pick it up again.
        else:
            # Kept, not discarded: still the only record of which event id was deleted, which
            # a future manual `restore` command needs, and it also earns the entry the longer
            # event_end-based purge margin (see _entry_purge_after) instead of the short
            # no_event fallback, since it did have a real event until now.
            entry["cancelled_events"] = list(entry.get("cancelled_events") or []) + events
            entry["events"] = []
            entry["status"] = "no_event"
            still_handled.add(identity)
            logging.info(f"{prefix}{identity}: event deleted, ignoring per on_user_delete=ignore.")

    if changed and not dry_run:
        _save_state(path, state)

    return still_handled


def migrate_legacy_ledger_entries(args, path=None, dry_run=False):
    """One-time-per-ref migration: patch extendedProperties.private onto Calendar events
    created before deterministic ids/origin stamping existed, and backfill each ref's
    event_end while at it (free - the same events.get() call already fetches it) - see
    docs/investigation-limite1.md migration requirements. Never touches an event's own id -
    see migrate_one_legacy_event().

    `dry_run=True` still reads (events.get(), needed for an accurate preview) but performs no
    write of any kind: no events.patch() call (see migrate_one_legacy_event), and no ledger
    save - every per-ref outcome is only logged. Safe to run repeatedly against real data to
    preview exactly what a real pass would touch before ever authorizing one.

    Before a REAL (non-dry-run) pass - unconditionally, not only when something will actually
    change - the ledger file is copied to `<path>.bak` (overwritten each real call) if it
    exists, so there is always a rollback point for the most recent real migration pass.

    Idempotent per ref: a successfully-migrated or confirmed-gone ref is marked
    "migrated": true and never touched again on a later call; a ref left un-migrated (an
    ambiguous API error) is retried on a future run, matching the conservative pattern used
    throughout this module.

    Scoped to refs within the sync bootstrap window (same one reconcile's own bootstrap diff
    trusts, via _is_within_bootstrap_window) - a ref older than that is left alone: it is
    either already purged or close to it regardless of whether it ever gets the origin stamp,
    so spending an API call on it buys nothing for the "state bounded by current activity"
    goal this whole redesign exists for.

    event_end backfill source, as actually implemented: the live event's own `end` field via
    events.get() (needed anyway to check/patch it) - not a `_times.json` log-file fallback.
    Log files are keyed by the source's own per-run post_id (see process_email_cli's/
    process_txt_cli's metadata_extractor), which is never persisted in the ledger (only
    mail_identity() is, a different value) - there is no reliable way to find the right log
    file from a ledger entry alone. Leaving event_end absent for a gone event is the
    documented, safe fallback: purge_expired_ledger_entries() already handles a missing
    event_end via the shorter no_event-style margin from recorded_at - never a crash or wrong
    data, just a possibly-shorter retention than a live event would have earned.

    Returns the number of refs migrated, confirmed already-migrated, or (dry_run only)
    that would be migrated, this call.
    """
    path = Path(path) if path else handled_mail_file()
    state = _load_state(path)
    api_dst = getattr(args, "calendar_api", None)
    client = api_dst.getClient() if api_dst is not None else None
    if client is None:
        return 0

    from manage_agenda.extraction import _is_within_bootstrap_window, migrate_one_legacy_event

    if not dry_run and path.is_file():
        backup_path = path.with_suffix(path.suffix + ".bak")
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        logging.info(f"migrate: backed up {path} to {backup_path} before a real pass.")

    migrated_count = 0
    changed = False
    for identity, entry in state.items():
        # Only "created" entries have live refs worth stamping. Deliberately excludes
        # "cancelled_events" refs on an on_user_delete="ignore" entry (status "no_event") -
        # those events are cancelled on Calendar, so there is nothing to stamp, and
        # extendedProperties is not guaranteed to survive on a cancelled event anyway (see
        # §3 correction 2 in the investigation doc).
        if entry.get("status") != "created":
            continue
        events = entry.get("events") or []
        generation = entry.get("generation", 0)
        for index, ref in enumerate(events):
            if not isinstance(ref, dict) or ref.get("migrated"):
                continue
            if not _is_within_bootstrap_window(ref.get("recorded_at")):
                continue
            calendar_id, event_id = ref.get("calendar_id"), ref.get("event_id")
            if not calendar_id or not event_id:
                continue
            status, event_end = migrate_one_legacy_event(
                client, calendar_id, event_id, identity, generation, index, dry_run=dry_run
            )
            if status == "retry":
                continue
            if status in ("migrated", "already_migrated", "would_migrate"):
                migrated_count += 1
            if dry_run:
                # Never mutate the ledger in dry-run - every outcome (would_migrate,
                # already_migrated, gone) is logged (see migrate_one_legacy_event and this
                # function's own logging) but not persisted, including the "migrated" flag
                # itself: a later real run must still process every one of these refs.
                logging.info(f"DRY RUN migrate: {identity} {calendar_id}/{event_id}: {status}")
                continue
            ref["migrated"] = True
            if event_end and not ref.get("event_end"):
                ref["event_end"] = event_end
            changed = True

    if changed:
        _save_state(path, state)
    return migrated_count


LEDGER_EVENT_END_MARGIN_DAYS = 30
LEDGER_NO_EVENT_MARGIN_DAYS = 7


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


def _entry_purge_after(entry, event_margin_days, no_event_margin_days):
    """The datetime after which this entry may be purged, or None if there is no age signal to
    purge by at all (a pre-migration legacy entry, or one written before `recorded_at` existed) -
    such entries are left untouched, exactly as before purging existed for them.

    Purges on the *event's own end date* (+ margin), never on `recorded_at`, whenever at least
    one ref (live in `events`, or cancelled-but-kept in `cancelled_events` under
    on_user_delete="ignore") carries an `event_end` - taking the max across all of an entry's
    events, live or cancelled (a multi-event message expires only once every one of its events
    has ended, per amendment 2; an ignored deletion still earns this margin, since it did have
    a real event until reconcile resolved it). Falls back to the entry's own `recorded_at` (+ a
    shorter margin) for "no_event"/"source_lost"/"legacy" entries and for refs recorded before
    `event_end` was tracked - the "log-date" fallback from amendment 2's own wording.
    manage-agenda never creates recurring events (confirmed in Phase 1 by reading the
    event-building code), so there is no separate recurrence-based purge rule to apply here.
    """
    all_refs = list(entry.get("events") or []) + list(entry.get("cancelled_events") or [])
    ends = [
        parsed
        for parsed in (_parse_iso_datetime(ev.get("event_end")) for ev in all_refs)
        if parsed is not None
    ]
    if ends:
        return max(ends) + datetime.timedelta(days=event_margin_days)
    recorded_at = _parse_iso_datetime(entry.get("recorded_at"))
    if recorded_at is not None:
        return recorded_at + datetime.timedelta(days=no_event_margin_days)
    return None


def purge_expired_ledger_entries(
    path=None,
    today=None,
    event_margin_days=LEDGER_EVENT_END_MARGIN_DAYS,
    no_event_margin_days=LEDGER_NO_EVENT_MARGIN_DAYS,
    dry_run=False,
):
    """Drop ledger entries past their purge date, so local state stays bounded by current/
    future activity instead of growing with the tool's whole history - the hard constraint
    behind this whole redesign (see docs/investigation-limite1.md).

    Applies uniformly to every status ("created", "no_event", "source_lost", "legacy"): what
    differs between them is only which age signal `_entry_purge_after` finds available.

    An entry with NO age signal at all (no event_end anywhere, and no `recorded_at` - only
    possible for a pre-migration entry that also predates the `recorded_at` field) is not left
    to persist forever: `_entry_purge_after` returning None here gets exactly one grace pass,
    stamping `recorded_at` to "now" (never overwriting an existing one - see
    _entry_purge_after, this branch is only reached when there truly wasn't one), so it
    purges via the normal no_event_margin_days on a later run. No entry can be exempt from
    purging indefinitely just for lacking history it never had.

    `dry_run=True` computes exactly what a real call would (the returned count is accurate
    either way) but never calls `_save_state` - nothing is dropped and no entry is stamped
    with a grace-pass `recorded_at`. Purging is the one truly destructive step of the three
    `process_email_cli` runs in sequence (reconcile, migrate, purge) - a `--dry-run` pass that
    left this one live would silently delete real ledger entries under a flag whose entire
    point is "touch nothing".

    Returns the number of entries that were (or, dry_run only, would be) purged.
    """
    path = Path(path) if path else handled_mail_file()
    state = _load_state(path)
    today = today or datetime.datetime.now(datetime.timezone.utc)
    if today.tzinfo is None:
        today = today.replace(tzinfo=datetime.timezone.utc)
    today_iso = today.isoformat().replace("+00:00", "Z")

    remaining = {}
    purged = 0
    stamped = False
    for identity, entry in state.items():
        purge_after = _entry_purge_after(entry, event_margin_days, no_event_margin_days)
        if purge_after is not None and purge_after <= today:
            purged += 1
            if dry_run:
                # `remaining` is never saved under dry_run (see below) - not adding this
                # identity to it here is just to avoid implying otherwise.
                logging.info(f"DRY RUN purge: {identity} would be purged (past {purge_after}).")
            continue
        if purge_after is None:
            # No event_end and no recorded_at at all - give it exactly one grace pass rather
            # than leaving it permanently unpurgeable.
            if dry_run:
                logging.info(f"DRY RUN purge: {identity} would be stamped with a grace-pass recorded_at.")
            else:
                entry["recorded_at"] = today_iso
                stamped = True
        remaining[identity] = entry

    if (purged or stamped) and not dry_run:
        _save_state(path, remaining)
    return purged


def list_restorable_identities_cli(path=None):
    """Print every ledger identity with at least one cancelled event (from an
    on_user_delete="ignore" resolution) that `restore <identity>` could attempt to restore -
    so an operator can find the identity string to pass it, without needing to read the
    ledger file by hand."""
    state = load_handled_mail_state(path)
    found = False
    for identity, entry in state.items():
        cancelled = entry.get("cancelled_events") or []
        if not cancelled:
            continue
        found = True
        event_ids = ", ".join(str(ref.get("event_id", "")) for ref in cancelled)
        print(t("sources.restore_list_entry", identity=identity, event_ids=event_ids))
    if not found:
        print(t("sources.restore_list_empty"))


def _attempt_restore_one_event(client, calendar_id, event_id):
    """Try events.patch(status="confirmed") on one cancelled event and verify it actually
    took effect via a follow-up get() - Calendar's docs do not guarantee patch resurrects a
    cancelled event, nor document how long a cancelled event remains fetchable at all (see
    docs/investigation-limite1.md, probe (b), unresolved). Never trusts a 200 OK from patch()
    alone: returns True only if the follow-up get() confirms status == "confirmed", and False
    (never raises) on any other outcome, including a 404/410 (permanently gone) or an
    ambiguous API error - restore is meant to fail visibly, not pretend success.
    """
    try:
        client.events().patch(
            calendarId=calendar_id, eventId=event_id, body={"status": "confirmed"}
        ).execute()
    except Exception as error:
        # Deliberately a catch-all (network errors, auth failures, and Calendar API refusals
        # all end up "not restored" the same way) - but logged with the exception type so a
        # 401/403/connectivity failure is distinguishable, in the log, from Calendar actually
        # refusing the patch.
        logging.warning(f"restore: patch failed for {calendar_id}/{event_id}: {type(error).__name__}: {error}")
        return False

    try:
        refreshed = client.events().get(calendarId=calendar_id, eventId=event_id).execute()
    except Exception as error:
        logging.warning(
            f"restore: could not verify {calendar_id}/{event_id} after patch: "
            f"{type(error).__name__}: {error}"
        )
        return False
    return isinstance(refreshed, dict) and refreshed.get("status") == "confirmed"


def restore_deleted_event_cli(args, identity):
    """Manually attempt to restore a deleted event for one ledger identity.

    Deliberately never part of the automatic on_user_delete resolution chain
    (ignore/requeue, see reconcile_handled_events) - the amendment that demoted "restore" from
    the automatic default reasoned that automatic restoration cannot tell an accidental
    deletion from a deliberate one; only a human operator invoking this command explicitly
    can decide that. Only identities with at least one on_user_delete="ignore" resolution
    (tracked in `cancelled_events`) have anything to restore - see
    list_restorable_identities_cli() to find one.

    Since probe (b) has never been run against real data, whether events.patch(status=
    "confirmed") actually resurrects a cancelled event, and for how long, is unverified - this
    command checks the outcome itself per event (see _attempt_restore_one_event) rather than
    assuming success, and reports failure plainly (the per-event prints, not the return
    value, are the operator-facing signal).

    Returns True only if every cancelled event for this identity was restored - False on a
    partial restore too, even though the ledger *was* already updated for whichever ones did
    succeed (see mark_events_restored). Callers that care about partial success should read
    the ledger, not this return value.
    """
    entry = load_handled_mail_state().get(identity)
    if entry is None:
        print(t("sources.restore_unknown_identity", identity=identity))
        return False
    cancelled = entry.get("cancelled_events") or []
    if not cancelled:
        print(t("sources.restore_nothing_to_restore", identity=identity))
        return False

    api_cal = select_api(args, "gcalendar", rules=None, title=t("sources.restore_select_calendar_title"))
    client = api_cal.getClient()

    restored, failed = [], []
    for ref in cancelled:
        calendar_id, event_id = ref.get("calendar_id"), ref.get("event_id")
        if not calendar_id or not event_id:
            continue
        if _attempt_restore_one_event(client, calendar_id, event_id):
            restored.append(ref)
            print(t("sources.restore_succeeded", calendar_id=calendar_id, event_id=event_id))
        else:
            failed.append(ref)
            print(t("sources.restore_failed", calendar_id=calendar_id, event_id=event_id))

    if restored:
        mark_events_restored(identity, restored)
    if failed:
        print(t("sources.restore_failed_hint"))

    return bool(restored) and not failed


def unseen_messages(posts, handled=None, path=None):
    """Drop messages whose identity was already handled, including repeats inside this batch."""
    known = set(handled) if handled is not None else load_handled_mail_ids(path)
    fresh = []
    batch = set()
    skipped = 0
    for post in posts:
        identity = mail_identity(post)
        if identity and (identity in known or identity in batch):
            skipped += 1
            continue
        if identity:
            batch.add(identity)
        fresh.append(post)
    return fresh, skipped


def _split_sender_rules(value):
    """Split on commas that are not inside double quotes."""
    parts = []
    current = []
    in_quotes = False
    for char in str(value):
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif char == "," and not in_quotes:
            piece = "".join(current).strip()
            if piece:
                parts.append(piece)
            current = []
        else:
            current.append(char)
    piece = "".join(current).strip()
    if piece:
        parts.append(piece)
    return parts


def _clean_imap_text(value):
    cleaned = "".join(char for char in str(value) if char not in '"\\\r\n')
    return " ".join(cleaned.split())


def _parse_sender_rule(text):
    """One sender rule: address, domain, display name, or name plus address/domain.

    A name with spaces is quoted or prefixed with name:. Inside one rule the
    name and the address are both required (AND). Separate rules are OR.
    """
    rest = text.strip()
    if not rest:
        return None
    name = None
    if rest.lower().startswith("name:"):
        rest = rest[5:].strip()
        if rest.startswith('"'):
            end = rest.find('"', 1)
            if end < 0:
                name = rest[1:]
                rest = ""
            else:
                name = rest[1:end]
                rest = rest[end + 1 :].strip()
        else:
            bits = rest.split(None, 1)
            name = bits[0] if bits else ""
            rest = bits[1].strip() if len(bits) > 1 else ""
    elif rest.startswith('"'):
        end = rest.find('"', 1)
        if end < 0:
            name = rest[1:]
            rest = ""
        else:
            name = rest[1:end]
            rest = rest[end + 1 :].strip()
    elif "@" not in rest:
        name = rest
        rest = ""
    address = _clean_imap_text(rest) if rest else ""
    name = _clean_imap_text(name) if name else ""
    if not name and not address:
        return None
    return {"name": name or None, "address": address or None}


def parse_from_list(value):
    if not value:
        return []
    rules = []
    for part in _split_sender_rules(value):
        rule = _parse_sender_rule(part)
        if rule:
            rules.append(rule)
    return rules


def _sender_criterion(rule):
    """Match the raw From header so the display name and the address both count."""
    if not rule:
        return None
    parts = []
    if rule.get("name"):
        parts.append(f'HEADER FROM "{rule["name"]}"')
    if rule.get("address"):
        parts.append(f'HEADER FROM "{rule["address"]}"')
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return "(" + " ".join(parts) + ")"


def build_imap_from_search(senders):
    """OR-combined From criteria. Read mail is included. An empty list matches nothing."""
    criteria = []
    for sender in senders or []:
        rule = sender if isinstance(sender, dict) else _parse_sender_rule(str(sender))
        piece = _sender_criterion(rule)
        if piece:
            criteria.append(piece)
    if not criteria:
        return None
    if len(criteria) == 1:
        one = criteria[0]
        return one if one.startswith("(") else f"({one})"
    expression = criteria[-1]
    for piece in reversed(criteria[:-1]):
        expression = f"OR {piece} {expression}"
    return f"({expression})"


def _imap_rule_mode(args):
    explicit = getattr(args, "rule", None)
    if explicit:
        return explicit
    if getattr(args, "source", None) == "imap":
        return "review" if args.interactive else "auto"
    return None


@dataclass
class ImapCapabilities:
    """CAPABILITY, read once per connection and logged - every marking/deletion decision
    below is gated on this, never on server/provider identity (see
    docs/investigation-limite1.md - the IMAP backend must be quasi-universal, with zero
    Gmail-specific code, including for Gmail reached over plain IMAP)."""

    raw: list
    has_uidplus: bool
    has_move: bool
    has_special_use: bool

    @classmethod
    def detect(cls, client):
        typ, data = client.capability()
        raw = []
        if typ == "OK" and data:
            for line in data:
                text = line.decode() if isinstance(line, bytes) else str(line)
                raw.extend(text.split())
        upper = {token.upper() for token in raw}
        return cls(
            raw=raw,
            has_uidplus="UIDPLUS" in upper,
            has_move="MOVE" in upper,
            has_special_use="SPECIAL-USE" in upper,
        )


def _imap_capabilities_once(api_src):
    """ImapCapabilities.detect(), once for this connection - never call this per message."""
    client = api_src.getClient()
    if client is None:
        return None
    capabilities = ImapCapabilities.detect(client)
    logging.info(f"IMAP capabilities for this connection: {capabilities}")
    return capabilities


def _uses_imap_search_criteria(source_details):
    """Whether this account's scan goes through the raw-SEARCH-criteria path
    (_fetch_imap_matches, via folder/channel/from config) rather than the tag-based
    setLabels/setChannel/getPosts path - see _imap_marker_mode()."""
    return bool(source_details.get("folder") or source_details.get("channel") or "from" in source_details)


def _imap_marker_mode(source_details):
    """(mode, value) from the `processed_marker` config: ("keyword", name), ("folder", path),
    ("flag_seen", None), or (None, None) if unconfigured (the account keeps today's default:
    _delete_email moves the message to Trash / removes its label). Backward compatible:
    `mark: seen` with no explicit `processed_marker` is `flag_seen`, matching pre-existing
    behavior exactly.

    Only meaningful for accounts using the folder/channel/from-configured search path
    (_fetch_imap_matches): that is the only place server-side scan exclusion (UNKEYWORD/
    UNDELETED) can be injected without modifying socialModules. The tag-based default scan
    (setLabels/setChannel/getPosts) has no such seam - a marker configured there would leave
    processed messages in the scanned label forever, with each run re-fetching a set that
    grows with the tool's whole history instead of its current activity, the exact problem
    this redesign exists to eliminate. Configuring a marker on such an account is treated as
    a mistake and logged, not silently accepted.
    """
    raw = str(source_details.get("processed_marker") or "").strip()
    if raw.startswith("keyword:"):
        mode, value = "keyword", raw.split(":", 1)[1].strip()
    elif raw.startswith("folder:"):
        mode, value = "folder", raw.split(":", 1)[1].strip()
    elif raw in ("flag:seen", "flag:\\Seen", "flag"):
        mode, value = "flag_seen", None
    elif source_details.get("mark") == "seen":
        mode, value = "flag_seen", None
    else:
        return None, None

    if not _uses_imap_search_criteria(source_details):
        logging.warning(
            f"processed_marker {raw!r} is configured but this account has no folder/channel/"
            "from criteria, so it never uses the search-criteria scan path - marking would "
            "have no server-side scan exclusion and would grow the scanned set with every "
            "processed message. Ignoring it; add folder/channel/from, or drop the setting."
        )
        return None, None
    return mode, value


def _imap_exclusion_criterion(source_details):
    """Server-side SEARCH exclusion matching this account's marker mode, or None.

    "keyword" excludes via UNKEYWORD - moves the "already handled" check from a per-message
    ledger lookup (fetch header, compare identity) to the server, so an already-marked
    message is never even fetched again. "folder" excludes via UNDELETED unconditionally
    (not just when UIDPLUS is absent): see _imap_move_to_folder_safely - without UIDPLUS the
    original is left flagged \\Deleted rather than expunged, and it must never be re-offered.
    "flag_seen" adds no exclusion criterion - unchanged from today's mark:seen behavior,
    ledger-only (see docs/investigation-limite1.md §5).
    """
    mode, value = _imap_marker_mode(source_details)
    if mode == "keyword":
        return f"UNKEYWORD {value}"
    if mode == "folder":
        return "UNDELETED"
    return None


def _combine_with_marker_exclusion(criteria, source_details):
    exclusion = _imap_exclusion_criterion(source_details)
    if not exclusion:
        return criteria
    if criteria:
        return f"({criteria} {exclusion})"
    return f"({exclusion})"


_COPYUID_RE = re.compile(rb"\[COPYUID (\d+) (\S+) (\S+)\]")


def _imap_uid_for_sequence(client, sequence):
    """The UID (RFC 3501) of the message at this sequence number, in the currently-selected
    folder - needed because UID EXPUNGE (the only safe way to expunge a single message
    without UIDPLUS purging every \\Deleted message in the folder) takes a UID, not a
    sequence number."""
    typ, data = client.fetch(str(sequence), "(UID)")
    if typ != "OK" or not data or not data[0]:
        return None
    part = data[0]
    text = part.decode() if isinstance(part, bytes) else str(part)
    match = re.search(r"UID (\d+)", text)
    return match.group(1) if match else None


def _parse_copyuid(response_lines):
    """{"uidvalidity": ..., "uid": ...} from a `[COPYUID uidvalidity src-uid dest-uid]`
    response code (RFC 4315), or None if absent (no UIDPLUS, or the server didn't include
    one)."""
    for line in response_lines or []:
        if not isinstance(line, bytes):
            continue
        match = _COPYUID_RE.search(line)
        if match:
            uidvalidity, _src_uid, dest_uid = (part.decode() for part in match.groups())
            return {"uidvalidity": uidvalidity, "uid": dest_uid}
    return None


def _imap_move_known_uid_safely(client, capabilities, uid, dest_folder):
    """Core of the never-bare-EXPUNGE move logic, operating on an already-known UID. Shared by
    _imap_move_to_folder_safely (moving OUT of the scanned folder on success) and the requeue
    un-marking step (moving BACK from the dedicated folder) - same safety rule either
    direction: MOVE when advertised (RFC 6851); otherwise COPY, then delete the original only
    when UIDPLUS (RFC 4315) scopes it to exactly this UID via `UID EXPUNGE` - NEVER a bare
    EXPUNGE, which would purge every \\Deleted message already in the folder, including ones a
    user deleted through their own client and expects to stay merely flagged until that client
    expunges them. Without UIDPLUS, the original is left flagged \\Deleted instead.

    Returns (success, locator). `locator` ({"folder": dest_folder, "uidvalidity": ...,
    "uid": ...}) is present only when the server included a COPYUID response code (requires
    UIDPLUS).

    Does not SELECT anything - the caller is responsible for having the right folder selected
    before calling, and for re-selecting whatever it needs afterward.
    """
    client.create(dest_folder)  # ignore failure if it already exists
    success = False
    locator = None
    if capabilities is not None and capabilities.has_move:
        typ, data = client.uid("MOVE", uid, dest_folder)
        success = typ == "OK"
        if success:
            locator = _parse_copyuid(data)
    else:
        typ, data = client.uid("COPY", uid, dest_folder)
        if typ == "OK":
            success = True
            locator = _parse_copyuid(data)
            if capabilities is not None and capabilities.has_uidplus:
                client.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                client.uid("EXPUNGE", uid)
            else:
                # No UIDPLUS (or capabilities unknown): never a bare EXPUNGE here - leave the
                # original flagged \Deleted, excluded from future scans by UNDELETED instead.
                client.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
    if locator:
        locator = dict(locator, folder=dest_folder)
    return success, locator


def _imap_move_to_folder_safely(api_src, capabilities, source_folder, sequence, dest_folder):
    """Move one message (by sequence number, in the currently-selected source_folder) to
    dest_folder - see _imap_move_known_uid_safely for the safety rule this applies.

    Re-selects source_folder before returning either way, since the caller's scan loop
    expects to still be working against it, not whatever this move last SELECTed.

    Safe to call mid-scan, one message at a time, only because _fetch_imap_matches always
    hands its caller messages highest-sequence-number-first: an expunge (implicit in MOVE, or
    explicit via UID EXPUNGE) only renumbers messages with a HIGHER sequence number than the
    one just removed, never a lower one - so a not-yet-processed message's `sequence` is never
    invalidated by marking an earlier (higher-numbered) one. This function does not itself
    enforce that ordering; it is the caller's responsibility (see process_email_cli).

    Returns (success, locator) - see _imap_move_known_uid_safely. The caller stores `locator`
    on the ledger entry so a future requeue can relocate the message by UID instead of
    searching for it.
    """
    client = api_src.getClient()
    if client is None:
        return False, None
    client.select(source_folder)
    uid = _imap_uid_for_sequence(client, sequence)
    if uid is None:
        client.select(source_folder)
        return False, None
    success, locator = _imap_move_known_uid_safely(client, capabilities, uid, dest_folder)
    client.select(source_folder)
    return success, locator


def _imap_store_keyword(api_src, folder, sequence, name, add=True):
    """STORE (or, with add=False, remove) a custom IMAP keyword on one message, by sequence
    number - matches _mark_imap_seen's convention (valid only within the current connection's
    session, immediately after the SEARCH/FETCH that produced it)."""
    client = api_src.getClient()
    if client is None:
        return False
    client.select(folder)
    op = "+FLAGS" if add else "-FLAGS"
    typ, _data = client.store(str(sequence), op, f"({name})")
    return typ == "OK"


def _mark_imap_seen(api_src, folder, sequence):
    """Mark one message read. The message stays in its folder."""
    client = api_src.getClient()
    if client is None:
        return False
    client.select(folder)
    typ, _data = client.store(str(sequence), "+FLAGS", "\\Seen")
    return typ == "OK"


def _looks_like_message_id(identity):
    """Whether `identity` is plausibly a real Message-ID (mail_identity()'s primary form)
    rather than its sha256-hash fallback (used when no Message-ID header existed on the
    original message). The hash fallback is 32 lowercase hex characters and essentially never
    contains "@"; a real Message-ID (RFC 5322 local-part@domain) always does. Used to decide
    whether a targeted mailbox search by Message-ID is even possible - the hash fallback
    carries no header value to search for."""
    return "@" in identity


def _imap_since_bound(recorded_at, margin_days=30):
    """A `SINCE <date>` IMAP search fragment bounding a targeted search to roughly when the
    message was originally handled (margin_days matches LEDGER_EVENT_END_MARGIN_DAYS, defined
    later in this module - kept a literal default here to avoid a definition-order
    dependency), so relocating a message is never an unbounded mailbox scan - see
    docs/investigation-limite1.md. None if recorded_at is unavailable or unparseable."""
    from manage_agenda.scheduling import imap_date

    parsed = _parse_iso_datetime(recorded_at)
    if parsed is None:
        return None
    since_date = (parsed - datetime.timedelta(days=margin_days)).date()
    return f"SINCE {imap_date(since_date)}"


def _imap_search_one_uid_by_message_id(client, folder, identity, recorded_at):
    """UID of the single message in `folder` whose Message-ID header matches `identity`,
    bounded by a SINCE window derived from `recorded_at` - or None if the search is
    impossible (identity is a hash fallback, not a real Message-ID), finds nothing, or finds
    more than one candidate. Multiple matches are logged and treated exactly like zero: never
    an arbitrary pick among several candidates (see docs/investigation-limite1.md)."""
    if not _looks_like_message_id(identity):
        return None
    typ, _data = client.select(folder)
    if typ != "OK":
        return None
    criterion = f'HEADER Message-ID "{identity}"'
    since = _imap_since_bound(recorded_at)
    if since:
        criterion = f"({criterion} {since})"
    typ, data = client.uid("SEARCH", None, criterion)
    if typ != "OK" or not data or not data[0]:
        return None
    uids = data[0].split()
    if len(uids) != 1:
        logging.warning(
            f"{identity}: {len(uids)} candidate messages found by Message-ID in {folder!r} "
            "while requeueing - leaving pending rather than guessing which one to un-mark."
        )
        return None
    return uids[0].decode() if isinstance(uids[0], bytes) else str(uids[0])


def _imap_unmark_keyword_by_identity(api_src, folder, identity, name, entry):
    """Remove the keyword from the message matching `identity` in `folder`. No locator is
    needed or used - the message never moved, so a bounded Message-ID search finds it exactly
    where marking left it (see docs/investigation-limite1.md, "no locator needed" for keyword
    mode)."""
    client = api_src.getClient()
    if client is None:
        return False
    uid = _imap_search_one_uid_by_message_id(client, folder, identity, entry.get("recorded_at"))
    if uid is None:
        return False
    typ, _data = client.uid("STORE", uid, "-FLAGS", f"({name})")
    return typ == "OK"


def _imap_current_uidvalidity(client):
    values = client.untagged_responses.get("UIDVALIDITY")
    if not values:
        return None
    value = values[0]
    return value.decode() if isinstance(value, bytes) else str(value)


def _imap_unmark_folder_by_identity(api_src, capabilities, source_folder, dest_folder, identity, entry):
    """Move the message matching `identity` back from `dest_folder` to `source_folder`. Uses
    the stored COPYUID locator (see remember_handled_mail) directly when its folder and
    UIDVALIDITY still match - no search needed; otherwise falls back to a bounded Message-ID
    search in `dest_folder` (never an unbounded one - see _imap_since_bound), and treats zero
    or multiple candidates the same way: left pending, never guessed at."""
    client = api_src.getClient()
    if client is None:
        return False

    locator = entry.get("imap_locator")
    if isinstance(locator, dict) and locator.get("folder") == dest_folder and locator.get("uid"):
        typ, _data = client.select(dest_folder)
        if typ == "OK" and _imap_current_uidvalidity(client) == locator.get("uidvalidity"):
            success, _new_locator = _imap_move_known_uid_safely(
                client, capabilities, locator["uid"], source_folder
            )
            client.select(source_folder)
            return success

    uid = _imap_search_one_uid_by_message_id(client, dest_folder, identity, entry.get("recorded_at"))
    if uid is None:
        return False
    success, _new_locator = _imap_move_known_uid_safely(client, capabilities, uid, source_folder)
    client.select(source_folder)
    return success


def _requeue_pending_imap_messages(
    api_src,
    source_details,
    is_imap_source,
    imap_marker_mode,
    imap_marker_value,
    imap_capabilities,
    handled_state,
    path=None,
):
    """For each pending_requeue identity in the ledger, try to un-mark its source message in
    THIS account's folder so mail_identity() finds it fresh on the next scan - never a second
    parallel extraction path, just letting the normal scan pick it up again once un-marked.
    On success, the entry is removed entirely (forget_handled_mail) rather than left in any
    intermediate state.

    A miss here (message not found in this account's folder) is expected and harmless when
    the identity belongs to a different account - it simply stays pending_requeue and is
    retried on that account's next run (self-correcting, no cross-account tracking needed).

    flag_seen mode needs no action here: reconcile already excludes a pending_requeue
    identity from `still_handled`, and flag_seen's exclusion is ledger-only (no server-side
    SEARCH exclusion, see _imap_exclusion_criterion), so the message is already visible again
    on the very next scan with no physical un-mark required.
    """
    if not is_imap_source or imap_marker_mode not in ("keyword", "folder"):
        return
    source_folder = source_details.get("folder") or source_details.get("channel") or "INBOX"
    for identity, entry in handled_state.items():
        if entry.get("status") != "pending_requeue":
            continue
        if imap_marker_mode == "keyword":
            unmarked = _imap_unmark_keyword_by_identity(
                api_src, source_folder, identity, imap_marker_value, entry
            )
        else:
            unmarked = _imap_unmark_folder_by_identity(
                api_src, imap_capabilities, source_folder, imap_marker_value, identity, entry
            )
        if unmarked:
            forget_handled_mail(identity, path=path)


def _fetched_message(fetched):
    if not fetched:
        return None
    for part in fetched:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
            return email.message_from_bytes(part[1])
    return None


def _fetch_imap_matches(api_src, folder, criteria, handled=None):
    """Read matching mail, including messages the user has already opened.

    A read flag only means someone looked at the message. The event may still
    be missing. Messages manage-agenda has already examined are skipped.
    """
    client = api_src.getClient()
    if client is None:
        print(t("sources.imap_not_connected"))
        return None
    typ, _data = client.select(folder)
    if typ != "OK":
        print(t("sources.could_not_open_folder", folder=folder))
        return None
    typ, data = client.search(None, criteria)
    if typ != "OK" or not data or not data[0]:
        print(t("sources.no_messages_match", criteria=criteria))
        return None
    # Highest sequence numbers are the most recently arrived - and this descending order is
    # also a safety invariant folder-mode marking depends on (see
    # _imap_move_to_folder_safely): expunging (via UID MOVE or UID EXPUNGE) a message only
    # renumbers messages with a HIGHER sequence number in the mailbox, never a lower one. As
    # long as `posts` is processed highest-first (never sorted ascending, never reordered),
    # marking one message can never invalidate the still-to-be-processed sequence number of
    # another.
    sequences = list(reversed(data[0].split()))[:IMAP_SCAN_WINDOW]
    known = set(handled) if handled is not None else load_handled_mail_ids()
    posts = []
    skipped = 0
    for sequence in sequences:
        sequence_text = sequence.decode() if isinstance(sequence, bytes) else str(sequence)
        typ, header_fetch = client.fetch(sequence_text, _IMAP_HEADER)
        header = _fetched_message(header_fetch) if typ == "OK" else None
        identity = mail_identity((sequence_text, header)) if header is not None else ""
        if identity and identity in known:
            skipped += 1
            continue
        typ, body_fetch = client.fetch(sequence_text, "(BODY.PEEK[])")
        message = _fetched_message(body_fetch) if typ == "OK" else None
        if message is None:
            continue
        posts.append((sequence_text, message))
        if identity:
            known.add(identity)
        if len(posts) >= IMAP_MATCH_LIMIT:
            break
    if skipped:
        print(t("sources.skipped_handled_messages", skipped=skipped))
    return posts or None


def _get_emails_from_folder(args, api_src, folder=None, source_details=None, handled=None):
    """Helper function to get emails from a specific folder."""
    "FIXME: maybe a folder argument?"

    posts = None
    source_details = source_details or {}

    configured_folder = source_details.get("folder") or source_details.get("channel")
    if configured_folder or "from" in source_details:
        folder = folder or configured_folder or "INBOX"
        criteria = build_imap_from_search(parse_from_list(source_details.get("from", "")))
        if criteria is None:
            print(t("sources.no_sender_rules", folder=folder))
            return None
        from manage_agenda.scheduling import combine_imap_search, imap_age_criteria

        criteria = combine_imap_search(criteria, imap_age_criteria(source_details))
        criteria = _combine_with_marker_exclusion(criteria, source_details)
        return _fetch_imap_matches(api_src, folder, criteria, handled=handled)

    if not folder:
        tag = config.DEFAULT_EMAIL_TAG or "zAgenda"
        folder = tag
        if "imap" in (getattr(api_src, "service", "") or "").lower():
            # Dovecot-style accounts nest the tag under INBOX. Proton Bridge
            # exposes it as a top-level mailbox, so accept whichever exists.
            api_src.setLabels()
            for candidate in (f"INBOX/{tag}", tag):
                if api_src.getLabels(candidate):
                    folder = candidate
                    break
            else:
                folder = f"INBOX/{tag}"
    api_src.setPostsType("posts")
    api_src.setLabels()
    label = api_src.getLabels(folder)
    if not label:
        print(t("sources.no_posts_with_label", folder=folder))
    else:
        api_src.setChannel(folder)
        api_src.setPosts()
        posts = api_src.getPosts()

    return posts


def list_folder(args, service):
    """List posts from the selected folder for a supported service."""
    rules = moduleRules.from_config()
    if service in ["email", "imap", "gmail"]:
        api_src = rules.selectRuleInteractive(service=service, title=t("sources.select_mail_account"))
        posts = _get_emails_from_folder(args, api_src)
    elif service == "gcalendar":
        api_src = rules.selectRuleInteractive(
            service=service, title=t("sources.select_calendar_account")
        )
        posts = _get_events_from_calendar(args, api_src)
    else:
        raise ValueError(f"Unsupported folder service: {service}")
    display_posts(api_src, posts)


def _get_post_datetime_and_diff(post_date):
    """
    Calculates the post datetime and the difference in days from now.

    Args:
        post_date (str or datetime.datetime): The date of the post.

    Returns:
        tuple: A tuple containing the post datetime and the time difference in days.
    """
    if isinstance(post_date, datetime.datetime):
        post_date_time = post_date
    elif post_date.isdigit():
        post_date_time = datetime.datetime.fromtimestamp(int(post_date) / 1000)
    else:
        from email.utils import parsedate_to_datetime

        try:
            post_date_time = parsedate_to_datetime(post_date)
        except (ValueError, TypeError):
            parsed = dateparser.parse(post_date)
            if parsed is not None:
                post_date_time = parsed
            else:
                try:
                    parts = [int(p) for p in post_date.split("-") if p.isdigit()]
                    post_date_time = datetime.datetime(parts[0], parts[1], parts[2])
                except (IndexError, ValueError):
                    post_date_time = datetime.datetime.now()

    try:
        import pytz

        # Define the timezone
        madrid_tz = pytz.timezone("Europe/Madrid")

        # Make post_date_time timezone-aware if it's naive
        if post_date_time.tzinfo is None:
            post_date_time = madrid_tz.localize(post_date_time)

        # Get the current time as timezone-aware
        now_aware = datetime.datetime.now(madrid_tz)

        time_difference = now_aware - post_date_time
        logging.debug(f"Date: {post_date_time} Diff: {time_difference.days}")
    except Exception as e:
        logging.error(f"Error processing post date: {e}")
        time_difference = datetime.timedelta(0)

    return post_date_time, time_difference


def _delete_email(args, api_src, post_id, source_name, rules=None):
    """Deletes an email, handling interactive confirmation and connection errors."""
    delete_confirmed = False
    if args.interactive:
        confirmation = input(t("sources.confirm_remove_label"))
        if confirmation.lower() == "y":
            delete_confirmed = True
    else:
        delete_confirmed = True

    if delete_confirmed:
        max_retries = 1
        label = None
        for attempt in range(max_retries + 1):
            try:
                print(t("sources.service_debug", service=api_src.service.lower()))
                res = ""
                if "imap" not in api_src.service.lower():
                    print(t("sources.label_debug", label=api_src.getChannel()))
                    logging.info(f"label: {api_src.getChannel()}")
                    folder = api_src.getChannel()
                    label = api_src.getLabels(folder)
                    logging.info(f"label: {label}")
                    res = api_src.modifyLabels(post_id, label[0], None)
                    logging.info(f"Label removed from email {post_id}.")
                else:
                    label = api_src.getChannel()
                    api_src.getClient().select(label)
                    res = api_src.deletePostId(post_id)
                    logging.info(f"State: {api_src.getClient().state}")
                logging.info(f"Res: {res}")
                if "Fail!" not in res:
                    logging.info(f"Email {post_id} processed successfully.")
                    return  # Success
            except Exception as e:
                logging.warning(f"Attempt {attempt + 1} of {max_retries + 1} failed: {e}")
                if attempt < max_retries:
                    logging.info("Retrying to connect to the email server...")

                    rules = rules or moduleRules.from_config()
                    logging.info(f"Source: {source_name}")
                    source_details = rules.more.get(source_name, {})
                    api_src = rules.readConfigSrc("", source_name, source_details)
                    if label:
                        api_src.setChannel(label)
                else:
                    logging.error(
                        f"Could not delete email {post_id} after {max_retries + 1} attempts: {e}"
                    )
                    return  # Exit after last attempt failure


def _is_post_too_old(args, time_difference, max_days=7):
    """Checks if an email is too old and confirms processing if interactive."""
    if max_days is None or max_days < 0:
        return False
    if time_difference.days > max_days:
        if args.interactive:
            confirmation = input(t("sources.confirm_process_old_post", days=time_difference.days))
            if confirmation.lower() != "y":
                return True
        else:
            if args.verbose:
                print(t("sources.too_old_skipping", days=time_difference.days))
            return True
    return False


def _process_common_flow(
    args,
    model,
    items,
    metadata_extractor,
    content_extractor,
    item_cleaner=None,
    rules=None,
    on_item_done=None,
    max_message_age_days=7,
):
    """
    Common flow for processing items (emails, web pages).

    metadata_extractor: func(item, index) -> (post_id, post_title, post_date, dedup_identity,
        generation). dedup_identity/generation feed the deterministic Calendar event id (see
        extraction.deterministic_event_id()); a source with no ledger/requeue concept (web,
        txt) returns (None, 0), which falls back to post_id inside
        _process_event_with_llm_and_calendar.
    content_extractor: func(item, index, post_date_time, post_title) -> content_text
    item_cleaner: func(item, index, post_id) -> void
    on_item_done: func(item, index, calendar_result) -> void, called once the item has been
        considered. calendar_result is the list of per-event results from
        _process_event_with_llm_and_calendar (None when the item was skipped before reaching
        that step, e.g. too old or empty content).
    """
    from manage_agenda.exceptions import CalendarError, LLMError

    processed_any_event = False
    for i, item in enumerate(items):
        finished = False
        calendar_result = None
        try:
            # 1. Metadata
            post_id, post_title, post_date, dedup_identity, generation = metadata_extractor(item, i)

            print(t("sources.processing_title", post_title=post_title), flush=True)

            # 2. Check Age
            post_date_time, time_difference = _get_post_datetime_and_diff(post_date)
            if _is_post_too_old(args, time_difference, max_message_age_days):
                finished = True
                continue

            # 3. Content
            content_text = content_extractor(item, i, post_date_time, post_title)
            if not content_text:
                finished = True
                continue

            # 4. Save & Print (Common)
            write_file(f"log/{post_id}_text.txt", content_text)
            if args.verbose:
                print_first_10_lines(content_text, "content")

            # 5. Process with LLM
            try:
                processed_event, calendar_result = _process_event_with_llm_and_calendar(
                    args,
                    model,
                    content_text,
                    post_date_time,
                    post_id,
                    post_title,
                    rules=rules,
                    dedup_identity=dedup_identity,
                    generation=generation,
                )
            except (LLMError, CalendarError) as error:
                print(error)
                print(t("sources.stopping_scan"))
                return processed_any_event
            finished = True

            if processed_event:
                processed_any_event = True
                # 6. Post-process
                if item_cleaner:
                    item_cleaner(item, i, post_id)
        finally:
            if finished and on_item_done:
                on_item_done(item, i, calendar_result)

    return processed_any_event


def process_txt_cli(args, model, source_name=None, rules=None):
    """Processes txt files and creates calendar events."""

    if not source_name:
        source_name = input(
            t("sources.enter_filenames", msg_txt_dir=config.MSG_TXT_DIR)
        ).split()
        if not source_name:
            print(t("sources.no_filenames_entered", msg_txt_dir=config.MSG_TXT_DIR))

    api_src, posts = _get_msgs_from_folder(args, source_name, rules=rules)

    if posts:

        def metadata_extractor(post, i):
            # Use getPostIdM if it exists, otherwise use getPostId
            if hasattr(api_src, "getPostIdM"):
                post_id = api_src.getPostIdM(post)
            else:
                post_id = post[0]

            # print(f"Post id: {post_id}")
            # print(f"Post id: {post_id}")
            lines_txt = post[1].split("\n")
            import re

            date = ""
            for line in reversed(lines_txt):
                match = re.search(r"(?i)date:\s*([^\s\n]+)", line)
                if match:
                    date = match.group(1)
                    break

            if not date and len(lines_txt) > 1:
                last_line = lines_txt[-1].strip() or lines_txt[-2].strip()
                if last_line:
                    parts = last_line.split(": ")
                    if len(parts) > 1:
                        date = "".join(parts[1:])

            if not date and len(lines_txt) > 1:
                date = lines_txt[1].split(" ")[-1]

            if " " in date:
                date = date.split(" ")[0]

            if not args.interactive:
                date = datetime.datetime.today()

            if "Subject: " in lines_txt:
                title = next((i for i, s in enumerate(lines_txt) if "Subject: " in s), -1)
            else:
                title = lines_txt[0]
            logging.info(f"Extracted info. PostId: {post_id} Title: {title} Date: {date}")
            return post_id, title, date, None, 0

        def content_extractor(post, i, post_date_time, post_title):
            lines_txt = post[1].split("\n")
            if "Subject: " in lines_txt:
                post_title = next((i for i, s in enumerate(lines_txt) if "Subject: " in s), -1)
            else:
                post_title = lines_txt[0]
            full_email_content = "".join(lines_txt[3:-1])
            date_message = lines_txt[-1].split(" ")[-1]
            # FIXME is this ok?
            date_message = datetime.datetime.today()
            return (
                f"Subject: {post_title}\n"
                f"Message: {full_email_content}\n"
                f"Message date: {date_message}\n"
            )

        def item_cleaner(post, i, post_id):
            pass

        return _process_common_flow(
            args, model, posts, metadata_extractor, content_extractor, item_cleaner, rules=rules
        )
    return False  # Default return if something went wrong before the main logic


def process_email_cli(args, model, selected_source=None, rules=None):
    """Processes emails and creates calendar events."""

    rules = rules or moduleRules.from_config()
    source_details = {}
    if selected_source:
        source_details = rules.more.get(selected_source, {}) or {}
        api_src = rules.readConfigSrc("", selected_source, source_details)
    else:
        api_src = select_api(args, "email", rules=rules)

    if not prepare_calendar(args, rules):
        print(t("sources.no_message_read_fix_calendar"))
        return False

    # --dry-run (args.dry_run) was requested scoped to reconcile and migrate specifically
    # (the two decision/mutation points against real Calendar/ledger data), and the rest of
    # this function (scanning/extraction/publishing) deliberately still runs normally under
    # it. purge is included too, even though it wasn't named: it writes the exact same ledger
    # file in the same three-call sequence, and skipping it here would let a "touch nothing"
    # flag permanently delete real ledger entries.
    dry_run = bool(getattr(args, "dry_run", False))

    # Reconcile BEFORE purge, always: reconcile is what notices a deleted event and applies
    # the on_user_delete resolution (ignore keeps the identity excluded; requeue bumps its
    # generation and marks it pending_requeue) - purging an entry first would drop it before
    # reconcile ever sees it, silently turning "the event was deleted" into "this message was
    # never seen", defeating on_user_delete entirely for anything past its purge margin too.
    handled = reconcile_handled_events(args, dry_run=dry_run)
    # Migrate BEFORE purge too: it backfills event_end on legacy refs that predate that field,
    # which purge_expired_ledger_entries() needs to give them their full margin instead of the
    # shorter no_event-style fallback it would otherwise fall back to.
    migrate_legacy_ledger_entries(args, dry_run=dry_run)
    purge_expired_ledger_entries(dry_run=dry_run)
    # Loaded once, after reconcile/migrate/purge - metadata_extractor below does one dict
    # lookup per message instead of re-reading the ledger file each time, and is also where a
    # pending_requeue entry (identity intentionally left out of `handled` above) is found for
    # the un-marking step below.
    handled_state = load_handled_mail_state()

    # Computed once per connection (never per message - see ImapCapabilities), and
    # unconditionally (not gated on `posts`): the un-marking step below acts on entries left
    # over from a *previous* run, regardless of whether this run's scan finds anything new.
    is_imap_source = "imap" in (getattr(api_src, "service", "") or "").lower()
    imap_marker_mode, imap_marker_value = (
        _imap_marker_mode(source_details) if is_imap_source else (None, None)
    )
    imap_capabilities = (
        _imap_capabilities_once(api_src)
        if is_imap_source and imap_marker_mode == "folder"
        else None
    )

    # Checked (and history recorded) for every IMAP account, every mode - not just when
    # switching to keyword/folder - so a later switch away from flag_seen has something to
    # compare against. Blocks only the specific flag_seen -> keyword/folder transition; see
    # check_marker_mode_transition() for why that one risks genuine duplicate events without
    # the (documented but unimplemented) §6 mailbox-side migration.
    marker_transition_blocked = False
    if is_imap_source:
        account_key = imap_marker_account_key(selected_source, source_details)
        if not check_marker_mode_transition(account_key, imap_marker_mode):
            marker_transition_blocked = True
            print(
                t(
                    "sources.marker_migration_required",
                    account=account_key,
                    mode=imap_marker_mode or "none",
                )
            )

    # A pending_requeue identity is only ever un-marked in the account whose folder actually
    # has it - a miss here is expected and harmless when the identity belongs to a different
    # account (self-correcting: it stays pending_requeue for that account's next run, no
    # cross-account tracking needed). Not gated on marker_transition_blocked - unlike a broad
    # scan, this only ever acts on a specific, already-known identity via a targeted search,
    # not the "purged-then-resurfaced messages match a wide criterion" risk the guard above
    # exists for.
    _requeue_pending_imap_messages(
        api_src, source_details, is_imap_source, imap_marker_mode, imap_marker_value,
        imap_capabilities, handled_state,
    )

    posts = (
        None
        if marker_transition_blocked
        else _get_emails_from_folder(args, api_src, source_details=source_details, handled=handled)
    )
    if posts:
        posts, skipped = unseen_messages(posts, handled=handled)
        if skipped:
            print(t("sources.skipped_handled_messages", skipped=skipped))

    if posts:

        def metadata_extractor(post, i):
            # Use getPostIdM if it exists, otherwise use getPostId
            if hasattr(api_src, "getPostIdM"):
                post_id = api_src.getPostIdM(post)
            else:
                post_id = api_src.getPostId(post)
            identity = mail_identity(post)
            generation = handled_state.get(identity, {}).get("generation", 0) if identity else 0
            return post_id, api_src.getPostTitle(post), api_src.getPostDate(post), identity, generation

        def content_extractor(post, i, post_date_time, post_title):
            full_email_content = api_src.getPostBody(post)
            date_message = str(post_date_time).split(" ")[0]
            sender = ""
            if hasattr(api_src, "getPostFrom"):
                try:
                    sender = api_src.getPostFrom(post) or ""
                except Exception:
                    sender = ""
            return (
                f"From: {sender}\n"
                f"Subject: {post_title}\n"
                f"Message: {full_email_content}\n"
                f"Message date: {date_message}\n"
            )

        def item_cleaner(post, i, post_id):
            if is_imap_source and imap_marker_mode:
                return  # marked instead of deleted/untagged - see on_item_done
            if is_imap_source:
                post_pos = i + 1
            else:
                post_pos = post_id
            _delete_email(args, api_src, post_pos, selected_source, rules=rules)

        def on_item_done(post, i, calendar_result):
            # Marking happens BEFORE remember_handled_mail, not after: a folder-mode move is
            # the only source of the COPYUID locator, and it needs to reach the ledger in the
            # SAME write remember_handled_mail makes - a second, later call for the same
            # identity would hit its "already recorded, nothing changed" early return and
            # silently drop the locator (see remember_handled_mail's docstring).
            imap_locator = None
            if is_imap_source and imap_marker_mode:
                sequence = post[0] if isinstance(post, tuple) else None
                folder = source_details.get("folder") or source_details.get("channel") or "INBOX"
                if sequence:
                    if imap_marker_mode == "keyword":
                        _imap_store_keyword(api_src, folder, sequence, imap_marker_value, add=True)
                    elif imap_marker_mode == "flag_seen":
                        _mark_imap_seen(api_src, folder, sequence)
                    elif imap_marker_mode == "folder":
                        _, imap_locator = _imap_move_to_folder_safely(
                            api_src, imap_capabilities, folder, sequence, imap_marker_value
                        )
            remember_handled_mail(
                mail_identity(post),
                events=_extract_event_refs(calendar_result),
                imap_locator=imap_locator,
            )

        from manage_agenda.scheduling import message_age_limit_days

        return _process_common_flow(
            args,
            model,
            posts,
            metadata_extractor,
            content_extractor,
            item_cleaner,
            rules=rules,
            on_item_done=on_item_done,
            max_message_age_days=message_age_limit_days(source_details),
        )
    return False  # Default return if something went wrong before the main logic


def _get_pages_from_urls(args, urls):

    page = moduleHtml.moduleHtml()
    if args.verbose:
        print(t("sources.urls_debug", urls=urls))
    page.setUrl(urls)
    page.setApiPosts()
    posts = page.getPosts()

    if not posts:
        print(t("sources.no_posts_with_urls", urls=urls))
        posts = None

    return page, posts


def _get_links_from_notes():
    """Extracts URLs from all notes in ~/notes."""
    try:
        from note_app import NoteManager

        notes_dir = os.path.expanduser("~/notes")
        if not os.path.exists(notes_dir):
            logging.warning(f"Notes directory {notes_dir} does not exist.")
            return {}

        manager = NoteManager(storage_dir=notes_dir)
        titles = manager.list_notes()
        url_to_notes = {}
        for title in titles:
            note = manager.read_note(title)
            if note:
                # get_urls() returns explicitly added URLs
                # get_links() returns URLs extracted from content
                note_urls = set(note.get_urls()) | set(note.get_links())
                for url in note_urls:
                    if url not in url_to_notes:
                        url_to_notes[url] = []
                    url_to_notes[url].append(title)
        return url_to_notes
    except ImportError:
        logging.warning("note_app not found. Cannot extract links from notes.")
        return {}
    except Exception as e:
        logging.error(f"Error extracting links from notes: {e}")
        return {}


def process_web_cli(args, model, urls=None, force_refresh=False, rules=None):
    """Processes web pages and creates calendar events."""

    url_to_notes = {}
    urls_input = None
    if not urls:
        if args.interactive:
            urls_input = input(t("sources.enter_urls")).split()
        if not urls_input or not args.interactive:
            print(t("sources.no_urls_entered"))
            url_to_notes = _get_links_from_notes()
            if not url_to_notes:
                print(t("sources.no_links_found"))
                return False
            print(t("sources.found_notes", url_to_notes=url_to_notes))
            urls = list(url_to_notes.keys())
            print(t("sources.found_total_links", count=len(urls)))
            print(t("sources.found_links", urls=urls))
        else:
            urls = urls_input

    api_src, posts = _get_pages_from_urls(args, urls)

    if posts:
        # Instantiate manager if we might need to delete notes
        manager = None
        if url_to_notes:
            try:
                from note_app import NoteManager

                notes_dir = os.path.expanduser("~/notes")
                manager = NoteManager(storage_dir=notes_dir)
            except ImportError:
                pass

        def metadata_extractor(post, i):
            title = api_src.getPostTitle(post)
            if not title:
                title = urls[i]

            # Generate a safe, readable filename from the URL
            import re

            from .web import extract_domain_and_path_from_url

            processed_url = extract_domain_and_path_from_url(urls[i])
            # Replace unsafe characters with underscores
            safe_id = re.sub(r"[^a-zA-Z0-9.-]", "_", processed_url)

            # A stable hash, not Python's built-in hash() (randomized per process since 3.3):
            # this id also seeds the deterministic Calendar event id below, which needs to be
            # the same across separate runs to be idempotent at all.
            hash_value = hashlib.sha256(urls[i].encode("utf-8")).hexdigest()[:16]

            # Truncate to a safe length (e.g., 150 chars) to avoid "File name
            # too long" errors
            if len(safe_id) > 130:
                safe_id = safe_id[:130]
            safe_id = f"{safe_id}_{hash_value}"

            return safe_id, title, datetime.datetime.now(), None, 0

        def content_extractor(post, i, post_date_time, post_title):
            web_content_reduced = reduce_html(urls[i], post, force_refresh=force_refresh)
            if not web_content_reduced:
                print(t("sources.could_not_process_url", url=urls[i]))
                return None

            date_message = str(post_date_time).split(" ")[0]
            return (
                f"Url: {urls[i]}\n"
                f"Subject: {post_title}\n"
                f"Message: {web_content_reduced}\n"
                f"Message date: {date_message}\n"
            )

        def item_cleaner(post, i, post_id):
            url = urls[i]
            if url in url_to_notes and manager:
                for note_title in url_to_notes[url]:
                    print(t("sources.deleting_note", note_title=note_title))
                    manager.delete_note(note_title)

        return _process_common_flow(
            args, model, posts, metadata_extractor, content_extractor, item_cleaner, rules=rules
        )

    return False  # Default return if something went wrong before the main logic


def add_events_cli(args, rules=None):
    """Add entries to the calendar from various sources (email, web, text)."""
    rules = rules or moduleRules.from_config()

    model = select_llm(args)

    print(t("sources.selected_model", model_name=model.model_name))

    sources, more_options = get_add_sources(rules=rules)
    if args.verbose:
        print(t("sources.source_debug", source=args.source))
        logging.debug(f"Sources: {sources}")
        logging.debug(f"More options: {more_options}")
    matches = []
    if args.source:
        matches = [item for item in sources if args.source in item]
        if not matches and more_options:
            matches = [item for item in more_options if args.source in str(item)]
    mode = _imap_rule_mode(args)
    if mode and matches:
        tagged = [item for item in matches if (rules.more.get(item) or {}).get("mode") == mode]
        if tagged:
            matches = tagged
    if args.interactive and not (args.source == "imap" and mode):
        sel, selected = select_from_list(
            sources, more_options=more_options, title=t("sources.sources_of_information_title")
        )
    else:
        selected = matches[0] if matches else None
    if selected:
        print(t("sources.selected_source", selected=selected))
        if hasattr(selected, "__iter__") and (
            ("web" in str(selected)) or ("http" in str(selected))
        ):
            url_list = None
            if isinstance(selected, str) and "http" in selected:
                url_list = selected.split(" ")
            process_web_cli(
                args, model, urls=url_list, force_refresh=args.force_refresh, rules=rules
            )
        elif hasattr(selected, "__iter__") and (
            ("text" in str(selected)) or os.path.exists(str(selected))
        ):
            file_list = None
            if isinstance(selected, str) and "." in selected:
                file_list = selected.split(" ")
            process_txt_cli(args, model, source_name=file_list, rules=rules)
        else:
            process_email_cli(args, model, selected_source=selected, rules=rules)
