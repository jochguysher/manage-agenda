import datetime
import email
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import dateparser
from socialModules import moduleHtml
from socialModules.moduleContent import display_posts
from socialModules.moduleRules import moduleRules
from socialModules.configMod import CONFIGDIR, select_from_list

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
    delete: Optional[bool] = None
    source: Optional[str] = None
    ai: Optional[str] = None
    verbose: bool = False
    destination: Optional[str] = None
    text: Optional[str] = None
    output: str = "calendar"
    force_refresh: bool = False
    rule: Optional[str] = None
    model: Optional[str] = None
    reconfigure: bool = False


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
            else:
                events, cancelled_events, status, generation, recorded_at = [], [], "no_event", 0, None
            parsed = {"events": events, "status": status, "generation": generation}
            if cancelled_events:
                parsed["cancelled_events"] = cancelled_events
            if isinstance(recorded_at, str) and recorded_at:
                parsed["recorded_at"] = recorded_at
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


def remember_handled_mail(identity, path=None, events=None):
    """Record that a message identity was handled, with the Calendar events it created, if any.

    `events` is a list of {"calendar_id": ..., "event_id": ..., "event_end": ...}. Without it,
    the message is recorded as handled with no known event (its identity is skipped, but never
    un-skipped, since there is nothing to check against Calendar).

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
        if merged == entry.get("events") and entry.get("status") == "created" and identity in state:
            return
        entry["events"] = merged
        entry["status"] = "created"
    elif identity in state:
        return
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


def reconcile_handled_events(args, path=None, sync_state_path=None, on_user_delete=None):
    """Resolve messages whose recorded Calendar events have all been deleted, per
    `on_user_delete` (default from config.Config.ON_USER_DELETE, itself defaulting to
    "ignore" - see docs/investigation-limite1.md, this default was explicitly validated by
    the user, never chosen unilaterally):

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
                entry["events"] = remaining
                changed = True
            continue

        # Every tracked event for this identity was cancelled - a user deletion.
        changed = True
        if on_user_delete == "requeue":
            # Deliberately abandons the old ids - a requeue always computes a fresh
            # deterministic id from the bumped generation, so there is nothing to keep them
            # for; see deterministic_event_id()'s "never reuse a deleted event's id" rule.
            entry["events"] = []
            entry["status"] = "pending_requeue"
            entry["generation"] = int(entry.get("generation") or 0) + 1
            logging.info(f"{identity}: event deleted, requeueing (generation bumped).")
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
            logging.info(f"{identity}: event deleted, ignoring per on_user_delete=ignore.")

    if changed:
        _save_state(path, state)

    return still_handled


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
):
    """Drop ledger entries past their purge date, so local state stays bounded by current/
    future activity instead of growing with the tool's whole history - the hard constraint
    behind this whole redesign (see docs/investigation-limite1.md).

    Applies uniformly to every status ("created", "no_event", "source_lost", "legacy"): what
    differs between them is only which age signal `_entry_purge_after` finds available.
    Returns the number of entries purged.
    """
    path = Path(path) if path else handled_mail_file()
    state = _load_state(path)
    today = today or datetime.datetime.now(datetime.timezone.utc)
    if today.tzinfo is None:
        today = today.replace(tzinfo=datetime.timezone.utc)

    remaining = {}
    purged = 0
    for identity, entry in state.items():
        purge_after = _entry_purge_after(entry, event_margin_days, no_event_margin_days)
        if purge_after is not None and purge_after <= today:
            purged += 1
            continue
        remaining[identity] = entry

    if purged:
        _save_state(path, remaining)
    return purged


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


def _mark_imap_seen(api_src, folder, sequence):
    """Mark one message read. The message stays in its folder."""
    client = api_src.getClient()
    if client is None:
        return False
    client.select(folder)
    typ, _data = client.store(str(sequence), "+FLAGS", "\\Seen")
    return typ == "OK"


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
    # Highest sequence numbers are the most recently arrived.
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

    # Reconcile BEFORE purge, always: reconcile is what notices a deleted event and applies
    # the on_user_delete resolution (ignore keeps the identity excluded; requeue bumps its
    # generation and marks it pending_requeue) - purging an entry first would drop it before
    # reconcile ever sees it, silently turning "the event was deleted" into "this message was
    # never seen", defeating on_user_delete entirely for anything past its purge margin too.
    handled = reconcile_handled_events(args)
    purge_expired_ledger_entries()
    # Loaded once, after reconcile and purge - metadata_extractor below does one dict lookup
    # per message instead of re-reading the ledger file each time. Also how a pending_requeue
    # entry (identity intentionally left out of `handled` above) would be found by a future
    # un-marking step - not wired yet, this commit only lands the local resolution decision.
    handled_state = load_handled_mail_state()

    posts = _get_emails_from_folder(args, api_src, source_details=source_details, handled=handled)
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
            if "imap" in api_src.service.lower() and source_details.get("mark") == "seen":
                return
            if "imap" in api_src.service.lower():
                post_pos = i + 1
            else:
                post_pos = post_id
            _delete_email(args, api_src, post_pos, selected_source, rules=rules)

        def on_item_done(post, i, calendar_result):
            remember_handled_mail(mail_identity(post), events=_extract_event_refs(calendar_result))
            if "imap" in (getattr(api_src, "service", "") or "").lower() and source_details.get(
                "mark"
            ) == "seen":
                sequence = post[0] if isinstance(post, tuple) else None
                folder = source_details.get("folder") or source_details.get("channel") or "INBOX"
                if sequence:
                    _mark_imap_seen(api_src, folder, sequence)

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
