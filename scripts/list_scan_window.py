"""Read-only preview of what `manage-agenda add` would look at on each IMAP account.

For every IMAP account whose scan goes through the search-criteria path (a `folder`,
`channel` or `from` setting - see manage_agenda.sources._uses_imap_search_criteria; an IMAP
account without them is reported as skipped, and the Gmail API account, which is not IMAP
and scans a label, is not listed at all), this
runs EXACTLY the search the scan runs - the same three builders, in the same order as
manage_agenda.sources._get_emails_from_folder:
  1. build_imap_from_search(parse_from_list(details["from"]))   - the sender filter,
  2. combine_imap_search(..., imap_age_criteria(details))       - SINCE/BEFORE,
  3. _combine_with_marker_exclusion(..., details)                - UNKEYWORD/UNDELETED when a
                                                                  processed_marker is set
                                                                  (nothing for mark: seen),
then lists every matching message, newest first as the scan orders them, with:
  date, from, subject, message_id, seen (the \\Seen flag), identity (mail_identity(), so the
  no-Message-ID hash fallback matches the ledger's), in_ledger + ledger_status (from
  handled_mail_ids.json), and two columns derived from the scan's own constants:
  - in_scan_window: within the IMAP_SCAN_WINDOW newest matches the scan even looks at;
  - would_process:  one of the first IMAP_MATCH_LIMIT in-window messages NOT in the ledger -
                    i.e. what the next `add` would extract, given the ledger as it is now.
An account whose sender filter is empty gets "criteria: none" and no rows: that is what the
scan does too (it prints "no sender rules" and processes nothing) - nothing falls back to ALL.

Nothing is marked, moved, extracted or written: folders are SELECTed read-only, headers are
fetched with BODY.PEEK (a plain BODY fetch would set \\Seen), and the ledger is only read.
The only file this script writes is its own report, and only with -o/--output - prefer it to a
shell redirection, since socialModules prints a "Checking rules" banner on stdout when its
config is read. Not run by the assistant.

Usage:
    python scripts/list_scan_window.py [--account NAME ...] [--ledger PATH] [-o PATH]
"""

import argparse
import csv
import email
import email.header
import io
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from manage_agenda.scheduling import combine_imap_search, imap_age_criteria  # noqa: E402
from manage_agenda.sources import (  # noqa: E402
    IMAP_MATCH_LIMIT,
    IMAP_SCAN_WINDOW,
    _combine_with_marker_exclusion,
    _fetched_message,
    _uses_imap_search_criteria,
    build_imap_from_search,
    handled_mail_file,
    load_handled_mail_state,
    mail_identity,
    parse_from_list,
)

_FETCH_ITEMS = "(FLAGS BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM DATE SUBJECT)])"
_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")

FIELDS = [
    "account",
    "folder",
    "sequence",
    "date",
    "from",
    "subject",
    "message_id",
    "seen",
    "identity",
    "in_ledger",
    "ledger_status",
    "in_scan_window",
    "would_process",
]


def scan_criteria(details):
    """The exact SEARCH string manage_agenda.sources._get_emails_from_folder hands to
    _fetch_imap_matches for this account - or None when the scan would process nothing
    (no usable sender rule)."""
    criteria = build_imap_from_search(parse_from_list(details.get("from", "")))
    if criteria is None:
        return None
    criteria = combine_imap_search(criteria, imap_age_criteria(details))
    return _combine_with_marker_exclusion(criteria, details)


def scan_folder(details):
    return details.get("folder") or details.get("channel") or "INBOX"


def _decode_header(value):
    if value is None:
        return ""
    try:
        parts = email.header.decode_header(str(value))
    except Exception:
        return str(value)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return " ".join(" ".join(decoded).split())


def _seen_from(fetched):
    for part in fetched or []:
        head = part[0] if isinstance(part, tuple) else part
        if isinstance(head, (bytes, bytearray)):
            match = _FLAGS_RE.search(head)
            if match:
                return b"\\Seen" in match.group(1)
    return False


def rows_for_account(client, account, folder, criteria, ledger, scan_window=IMAP_SCAN_WINDOW, match_limit=IMAP_MATCH_LIMIT):
    """One row per message matching `criteria` in `folder`, newest first, through an
    already-connected imaplib client - read-only: SELECT (readonly), SEARCH, and one
    BODY.PEEK header fetch per message. `ledger` is the loaded handled-mail state."""
    if criteria is None:
        print(f"{account}: criteria: none - the scan processes nothing for this account.", file=sys.stderr)
        return []
    typ, _data = client.select(folder, readonly=True)
    if typ != "OK":
        print(f"{account}: could not open folder {folder!r} ({typ}).", file=sys.stderr)
        return []
    print(f"{account}: folder {folder!r}, criteria: {criteria}", file=sys.stderr)
    typ, data = client.search(None, criteria)
    if typ != "OK" or not data or not data[0]:
        print(f"{account}: no message matches.", file=sys.stderr)
        return []
    sequences = list(reversed(data[0].split()))  # newest first, as the scan orders them
    rows = []
    would_process = 0
    # As in _fetch_imap_matches: an identity already taken this batch (a second copy of the
    # same Message-ID) is skipped by the scan, so it is not counted as processed twice.
    taken = set()
    for position, sequence in enumerate(sequences):
        sequence_text = sequence.decode() if isinstance(sequence, bytes) else str(sequence)
        typ, fetched = client.fetch(sequence_text, _FETCH_ITEMS)
        header = _fetched_message(fetched) if typ == "OK" else None
        identity = mail_identity((sequence_text, header)) if header is not None else ""
        entry = ledger.get(identity) if identity else None
        in_window = position < scan_window
        processed_next = (
            in_window and entry is None and would_process < match_limit and not (identity and identity in taken)
        )
        if processed_next:
            would_process += 1
            if identity:
                taken.add(identity)
        rows.append(
            {
                "account": account,
                "folder": folder,
                "sequence": sequence_text,
                "date": _decode_header(header.get("Date")) if header is not None else "",
                "from": _decode_header(header.get("From")) if header is not None else "",
                "subject": _decode_header(header.get("Subject")) if header is not None else "",
                "message_id": (str((header.get("Message-ID") if header is not None else "") or "").strip().strip("<>")),
                "seen": _seen_from(fetched),
                "identity": identity,
                "in_ledger": entry is not None,
                "ledger_status": (entry or {}).get("status", "") if entry else "",
                "in_scan_window": in_window,
                "would_process": processed_next,
            }
        )
    print(
        f"{account}: {len(rows)} match(es), {sum(r['in_ledger'] for r in rows)} in the ledger, "
        f"{would_process} would be processed by the next add.",
        file=sys.stderr,
    )
    return rows


def imap_accounts(rules, only=None):
    """[(name, rule key, details)] for every configured IMAP account - `name` being the
    tuple's section (e.g. 'acme-review'), the value --account matches."""
    accounts = []
    for src, details in (rules.more or {}).items():
        if not (isinstance(src, tuple) and src and str(src[0]).lower() == "imap"):
            continue
        name = (details or {}).get("section_name") or (src[2] if len(src) > 2 else str(src))
        if only and name not in only:
            continue
        accounts.append((name, src, details or {}))
    return accounts


def render(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", action="append", default=None, help="Only this IMAP account (repeatable). Default: every one.")
    parser.add_argument("--ledger", default=None, help="Ledger file path. Default: the real handled_mail_ids.json.")
    parser.add_argument("-o", "--output", default=None, help="Write the CSV to this file instead of stdout.")
    args = parser.parse_args()

    from socialModules.moduleRules import moduleRules

    rules = moduleRules.from_config()
    ledger_path = Path(args.ledger) if args.ledger else handled_mail_file()
    ledger = load_handled_mail_state(ledger_path)
    print(f"Ledger: {ledger_path} ({len(ledger)} identities)", file=sys.stderr)

    rows = []
    for name, src, details in imap_accounts(rules, args.account):
        if not _uses_imap_search_criteria(details):
            print(f"{name}: skipped - label scan, no search criteria.", file=sys.stderr)
            continue
        api_src = rules.readConfigSrc("", src, details)
        client = api_src.getClient() if api_src is not None else None
        if client is None:
            print(f"{name}: could not connect - skipped.", file=sys.stderr)
            continue
        try:
            rows.extend(rows_for_account(client, name, scan_folder(details), scan_criteria(details), ledger))
        finally:
            try:
                client.logout()
            except Exception:
                pass

    text = render(rows)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {len(rows)} rows to {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
