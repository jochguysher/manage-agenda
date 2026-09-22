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
    header = title or f"First {n} lines of {content_type}"
    print(f"\n--- {header} ---")
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
            print(f"There is no {target_dir} directory")
        else:
            print(f"There are no posts in {target_dir}")
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

    New entries look like: {"events": [{"calendar_id": ..., "event_id": ...}], "status": "created"}.
    A message with no recorded event ("status": "no_event", e.g. too old or empty content) or one
    read from the legacy {"ids": [...]} format ("status": "legacy") is always kept as handled: there
    is nothing to check against Calendar, so behavior for those stays exactly as before.
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
                status = entry.get("status") or ("created" if events else "no_event")
            else:
                events, status = [], "no_event"
            state[str(identity)] = {"events": events, "status": status}
        return state
    ids = data.get("ids") if isinstance(data, dict) else None
    if isinstance(ids, list):
        return {str(item): {"events": [], "status": "legacy"} for item in ids}
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

    `events` is a list of {"calendar_id": ..., "event_id": ...}. Without it, the message is
    recorded as handled with no known event (its identity is skipped, but never un-skipped,
    since there is nothing to check against Calendar).
    """
    if not identity:
        return
    path = Path(path) if path else handled_mail_file()
    state = _load_state(path)
    entry = state.get(identity, {"events": [], "status": "no_event"})
    if events:
        merged = list(entry.get("events") or [])
        for ref in events:
            if ref not in merged:
                merged.append(ref)
        if merged == entry.get("events") and entry.get("status") == "created" and identity in state:
            return
        entry["events"] = merged
        entry["status"] = "created"
    elif identity in state:
        return
    state[identity] = entry
    _save_state(path, state)


def _extract_event_refs(calendar_result):
    """Pull {calendar_id, event_id} pairs out of the per-event results of calendar publishing."""
    refs = []
    for result in calendar_result or []:
        if not isinstance(result, dict):
            continue
        calendar_id = result.get("calendar_id")
        event_id = result.get("event_id") or (result.get("raw_response") or {}).get("id")
        if calendar_id and event_id:
            refs.append({"calendar_id": calendar_id, "event_id": str(event_id)})
    return refs


def reconcile_handled_events(args, path=None):
    """Drop messages whose recorded Calendar events have all been deleted, so they get reprocessed.

    Messages with no recorded event (too old, empty content, output=file, or migrated from the
    legacy ledger format) are left untouched: there is nothing to check, so they stay skipped.
    Uses one grouped (batched) Calendar lookup for every event on record, instead of one API
    call per message, to limit API traffic.
    """
    path = Path(path) if path else handled_mail_file()
    state = _load_state(path)
    api_dst = getattr(args, "calendar_api", None)
    client = api_dst.getClient() if api_dst is not None else None
    if client is None:
        return set(state.keys())

    from manage_agenda.extraction import _check_events_exist

    triples = [
        (identity, ev.get("calendar_id"), ev.get("event_id"))
        for identity, entry in state.items()
        for ev in entry.get("events") or []
        if ev.get("calendar_id") and ev.get("event_id")
    ]
    exists = _check_events_exist(api_dst, triples)

    still_handled = set()
    changed = False
    for identity in list(state.keys()):
        entry = state[identity]
        events = entry.get("events") or []
        if not events:
            still_handled.add(identity)
            continue
        remaining = [
            ev for ev in events if exists.get((identity, ev.get("calendar_id"), ev.get("event_id")), True)
        ]
        if remaining:
            still_handled.add(identity)
            if len(remaining) != len(events):
                entry["events"] = remaining
                changed = True
        else:
            del state[identity]
            changed = True

    if changed:
        _save_state(path, state)

    return still_handled


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
        print("IMAP is not connected")
        return None
    typ, _data = client.select(folder)
    if typ != "OK":
        print(f"Could not open {folder}")
        return None
    typ, data = client.search(None, criteria)
    if typ != "OK" or not data or not data[0]:
        print(f"No messages match {criteria}")
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
        print(f"Skipped {skipped} message(s) already handled")
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
            print(f"No sender rules for {folder}. Nothing is read.")
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
        print(f"There are no posts tagged with label {folder}")
    else:
        api_src.setChannel(folder)
        api_src.setPosts()
        posts = api_src.getPosts()

    return posts


def list_folder(args, service):
    """List posts from the selected folder for a supported service."""
    rules = moduleRules.from_config()
    if service in ["email", "imap", "gmail"]:
        api_src = rules.selectRuleInteractive(service=service, title="Select mail account")
        posts = _get_emails_from_folder(args, api_src)
    elif service == "gcalendar":
        api_src = rules.selectRuleInteractive(service=service, title="Select calendar account")
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
        confirmation = input("Do you want to remove the label from the email? (y/n): ")
        if confirmation.lower() == "y":
            delete_confirmed = True
    else:
        delete_confirmed = True

    if delete_confirmed:
        max_retries = 1
        label = None
        for attempt in range(max_retries + 1):
            try:
                print(f"Service: {api_src.service.lower()}")
                res = ""
                if "imap" not in api_src.service.lower():
                    print(f"label: {api_src.getChannel()}")
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
            confirmation = input(
                f"The post has {time_difference.days} days. Do you want to process it? (y/n): "
            )
            if confirmation.lower() != "y":
                return True
        else:
            if args.verbose:
                print(f"Too old ({time_difference.days} days), skipping.")
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

    metadata_extractor: func(item, index) -> (post_id, post_title, post_date)
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
            post_id, post_title, post_date = metadata_extractor(item, i)

            print(f"Processing Title: {post_title}", flush=True)

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
                    args, model, content_text, post_date_time, post_id, post_title, rules=rules
                )
            except (LLMError, CalendarError) as error:
                print(error)
                print("Stopping this scan. Unfinished messages will be tried again.")
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
            f"Enter filenames separated by spaces (leave empty to use {config.MSG_TXT_DIR}): "
        ).split()
        if not source_name:
            print(f"No filenames entered. Extracting texts from {config.MSG_TXT_DIR}...")

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
            return post_id, title, date

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
        print("No message was read. Fix the calendar connection, then run the scan again.")
        return False

    handled = reconcile_handled_events(args)

    posts = _get_emails_from_folder(args, api_src, source_details=source_details, handled=handled)
    if posts:
        posts, skipped = unseen_messages(posts, handled=handled)
        if skipped:
            print(f"Skipped {skipped} message(s) already handled")

    if posts:

        def metadata_extractor(post, i):
            # Use getPostIdM if it exists, otherwise use getPostId
            if hasattr(api_src, "getPostIdM"):
                post_id = api_src.getPostIdM(post)
            else:
                post_id = api_src.getPostId(post)
            return post_id, api_src.getPostTitle(post), api_src.getPostDate(post)

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
        print(f"Urls: {urls}")
    page.setUrl(urls)
    page.setApiPosts()
    posts = page.getPosts()

    if not posts:
        print(f"There are no posts with these urls {urls}")
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
            urls_input = input(
                "Enter URLs separated by spaces (leave empty to use ~/notes): "
            ).split()
        if not urls_input or not args.interactive:
            print("No URLs entered. Extracting links from ~/notes...")
            url_to_notes = _get_links_from_notes()
            if not url_to_notes:
                print("No links found in ~/notes.")
                return False
            print(f"Found notes: {url_to_notes}")
            urls = list(url_to_notes.keys())
            print(f"Found total of links: {len(urls)}")
            print(f"Found links: {urls}")
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

            hash_value = hash(urls[i])

            # Truncate to a safe length (e.g., 150 chars) to avoid "File name
            # too long" errors
            if len(safe_id) > 130:
                safe_id = safe_id[:130]
            safe_id = f"{safe_id}_{hash_value}"

            return safe_id, title, datetime.datetime.now()

        def content_extractor(post, i, post_date_time, post_title):
            web_content_reduced = reduce_html(urls[i], post, force_refresh=force_refresh)
            if not web_content_reduced:
                print(f"Could not process {urls[i]}, skipping.")
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
                    print(f"Deleting note: {note_title}")
                    manager.delete_note(note_title)

        return _process_common_flow(
            args, model, posts, metadata_extractor, content_extractor, item_cleaner, rules=rules
        )

    return False  # Default return if something went wrong before the main logic


def add_events_cli(args, rules=None):
    """Add entries to the calendar from various sources (email, web, text)."""
    rules = rules or moduleRules.from_config()

    model = select_llm(args)

    print(f"Selected model: {model.model_name}")

    sources, more_options = get_add_sources(rules=rules)
    if args.verbose:
        print(f"Source: {args.source}")
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
            sources, more_options=more_options, title="Sources of information"
        )
    else:
        selected = matches[0] if matches else None
    if selected:
        print(f"Selected source: {selected}")
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
