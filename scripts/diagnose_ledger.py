"""Read-only diagnostic for the handled-mail ledger (handled_mail_ids.json).

Works for ONE calendar account at a time, chosen by the rule every ledger maintenance command
shares (manage_agenda.connections.select_calendar_account): the one `add` uses (the saved
calendar_account), else the only configured one, or one chosen interactively with -i; with
several configured and none saved, it stops and asks for -i, connecting nothing. Every
tracked event ref is first checked against that
account (see manage_agenda.sources.CalendarScope.owner_of - the same rule migrate-ledger and
reconcile use), then, only if it belongs to it, looked up with events.get() and classified:
  - calendar_inaccessible: the ref is not this account's - recorded for another calendar
                account, on a calendar missing from this account's calendarList, or a legacy
                "primary" ref while several calendar accounts are configured (so its owner is
                unknown). NOT queried: a 404 from a calendar this account can't see says
                nothing about the event. Rerun with -i for the other account.
  - active:     the event exists and is not cancelled.
  - cancelled:  the event exists with status="cancelled" (a genuine Calendar tombstone).
  - not_found:  404/410 on a calendar this account does see - Calendar has no record of the
                event (see docs/investigation-limite1.md §8/§9 - this is NOT proof of a user
                deletion, it is equally consistent with the event never having existed). A
                real entry of another account never lands here: it is calendar_inaccessible.
  - error:      an ambiguous API error - inconclusive, not a hard failure.
  - skipped:    the ref itself is malformed (missing calendar_id/event_id).

Also cross-references every ledger identity/calendar_id/event_id against string literals
collected (via ast, not a naive text search) from every *.py file under tests/, and reports
a confidence level for any match - real test-injected entries were found in the real ledger
before tests/conftest.py's isolation fixtures existed (see docs/investigation-limite1.md §9),
so this is a starting point for finding more, NOT a verdict on its own:
  - high:   the value looks like a real Message-ID (contains "@") and appears verbatim in the
            test suite - a strong pollution signal.
  - medium: a short, test-fixture-looking token (e.g. "e1", "cal-1") that also appears in the
            test suite - plausible pollution, but generic enough to double-check by hand.
  - low:    the value also happens to be a common real-world identifier (e.g. "primary", the
            actual default Google Calendar ID for every account, or "INBOX") - a match here
            is NOT a reliable pollution signal on its own; never delete on this alone.

Read-only with respect to application state: makes only calendarList.list() and events.get()
calls to Calendar (never insert/patch/delete), and never writes to the ledger file or any
other manage-agenda state (the saved calendar_account is read, never written).
The only file this script itself writes is its own report, and only if --output is given.
Not run by the assistant - the user runs and reviews this themselves, and decides what (if
anything) to clean up.

Usage:
    python scripts/diagnose_ledger.py [-i] [--ledger PATH] [--tests-dir PATH]
                                       [--format csv|json] [--output PATH]
"""

import argparse
import ast
import csv
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from manage_agenda.connections import select_calendar_account  # noqa: E402
from manage_agenda.exceptions import CalendarAccountChoiceRequired  # noqa: E402
from manage_agenda.sources import (  # noqa: E402
    EXIT_CALENDAR_ACCOUNT_CHOICE_REQUIRED,
    EXIT_CALENDAR_LIST_UNREADABLE,
    EXIT_NO_CALENDAR_ACCOUNT,
    Args,
    calendar_scope_for,
    handled_mail_file,
    load_handled_mail_state,
)

_COMMON_REAL_IDENTIFIERS = {"primary", "INBOX", "Sent", "Trash", "Drafts", "Archive", "", "0", "1"}


def connect_calendar(interactive, rules, config_path=None):
    """The calendar account to diagnose, authenticated, by the one selection rule of the whole
    tool (select_calendar_account, as `migrate-ledger` and `reconcile`): with -i always a
    choice; else the saved calendar_account `add` uses, else the only configured account -
    never silently the first of several, which could be a different account than the
    ledger's. Read-only: unlike prepare_calendar(), nothing is ever saved. Exits with the
    same codes as the commands when no account can be resolved."""
    args = Args(interactive=interactive)
    try:
        api_dst = select_calendar_account(args, rules, config_path=config_path)
    except CalendarAccountChoiceRequired as error:
        print(error, file=sys.stderr)
        sys.exit(EXIT_CALENDAR_ACCOUNT_CHOICE_REQUIRED)
    if api_dst is None:
        print("Could not authenticate a Google Calendar account. Run `manage-agenda auth -i` first.", file=sys.stderr)
        sys.exit(EXIT_NO_CALENDAR_ACCOUNT)
    return api_dst


def collect_test_literals(tests_dir):
    """Every string literal in tests/**/*.py, via ast (not a naive text search, so
    concatenation/f-string edge cases don't silently produce false negatives)."""
    literals = set()
    for path in sorted(Path(tests_dir).rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as error:
            print(f"Could not parse {path}, skipping: {error}", file=sys.stderr)
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
                literals.add(node.value)
    return literals


def confidence(value, test_literals):
    """"high" | "medium" | "low" | "" (no match) - see module docstring for what each means."""
    if not value or value not in test_literals:
        return ""
    if value in _COMMON_REAL_IDENTIFIERS:
        return "low"
    if "@" in value:
        return "high"
    return "medium"


def classify_event(client, calendar_id, event_id):
    """(classification, detail) - never raises; an ambiguous error is reported, not thrown."""
    import googleapiclient.errors

    try:
        response = client.events().get(calendarId=calendar_id, eventId=event_id).execute()
    except googleapiclient.errors.HttpError as error:
        status = getattr(getattr(error, "resp", None), "status", None)
        if status in (404, 410):
            return "not_found", ""
        return "error", str(error)
    except Exception as error:
        return "error", str(error)
    status = (response or {}).get("status")
    return ("cancelled" if status == "cancelled" else "active"), (status or "")


def build_rows(state, client, test_literals, scope):
    """One row per ref (or per ref-less entry). `scope` (a manage_agenda.sources.CalendarScope)
    decides which refs are this account's; only those are queried."""
    rows = []
    for identity, entry in state.items():
        identity_match = confidence(identity, test_literals)
        refs = [dict(ref, ref_source="events") for ref in (entry.get("events") or [])]
        refs += [dict(ref, ref_source="cancelled_events") for ref in (entry.get("cancelled_events") or [])]

        if not refs:
            rows.append(
                {
                    "identity": identity,
                    "status": entry.get("status", ""),
                    "ref_source": "-",
                    "ref_calendar_account": "",
                    "calendar_id": "",
                    "event_id": "",
                    "calendar_classification": "-",
                    "calendar_detail": "",
                    "identity_test_match": identity_match,
                    "calendar_id_test_match": "",
                    "event_id_test_match": "",
                }
            )
            continue

        for ref in refs:
            calendar_id = str(ref.get("calendar_id") or "")
            event_id = str(ref.get("event_id") or "")
            if not (calendar_id and event_id):
                classification, detail = "skipped", "ref missing calendar_id/event_id"
            else:
                is_owned, reason = scope.owner_of(ref)
                if is_owned:
                    classification, detail = classify_event(client, calendar_id, event_id)
                else:
                    classification, detail = "calendar_inaccessible", reason
            rows.append(
                {
                    "identity": identity,
                    "status": entry.get("status", ""),
                    "ref_source": ref.get("ref_source", "events"),
                    "ref_calendar_account": str(ref.get("calendar_account") or "(not recorded)"),
                    "calendar_id": calendar_id,
                    "event_id": event_id,
                    "calendar_classification": classification,
                    "calendar_detail": detail,
                    "identity_test_match": identity_match,
                    "calendar_id_test_match": confidence(calendar_id, test_literals),
                    "event_id_test_match": confidence(event_id, test_literals),
                }
            )
    return rows


_FIELDS = [
    "identity",
    "status",
    "ref_source",
    "ref_calendar_account",
    "calendar_id",
    "event_id",
    "calendar_classification",
    "calendar_detail",
    "identity_test_match",
    "calendar_id_test_match",
    "event_id_test_match",
]


def render(rows, fmt):
    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--ledger", default=None, help="Ledger file path. Default: the real handled_mail_ids.json."
    )
    parser.add_argument(
        "--tests-dir", default=None, help="Directory to scan for test literals. Default: <repo>/tests."
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Choose the calendar account to diagnose. Default: the saved one `add` uses, else the only configured one.",
    )
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--output", default=None, help="Output file path. Default: stdout.")
    args = parser.parse_args()

    ledger_path = Path(args.ledger) if args.ledger else handled_mail_file()
    tests_dir = Path(args.tests_dir) if args.tests_dir else REPO_ROOT / "tests"

    print(f"Ledger: {ledger_path}", file=sys.stderr)
    if not ledger_path.is_file():
        print("No ledger file found there - nothing to diagnose.", file=sys.stderr)
        sys.exit(0)

    print(f"Scanning test literals under: {tests_dir}", file=sys.stderr)
    test_literals = collect_test_literals(tests_dir)
    print(f"Collected {len(test_literals)} string literals from the test suite.", file=sys.stderr)

    state = load_handled_mail_state(ledger_path)
    print(f"{len(state)} ledger identities to check.", file=sys.stderr)

    from socialModules.moduleRules import moduleRules

    rules = moduleRules.from_config()
    scoped = Args(interactive=args.interactive)
    scoped.calendar_api = connect_calendar(args.interactive, rules)
    scope = calendar_scope_for(scoped, rules)
    print(f"Calendar account: {scope.account_key}", file=sys.stderr)
    if scope.owned_ids is None:
        print(
            "Could not read this account's calendar list - refs can't be told apart from "
            "another account's, so nothing is classified.",
            file=sys.stderr,
        )
        sys.exit(EXIT_CALENDAR_LIST_UNREADABLE)
    if not scope.sole_account:
        print(
            "Several calendar accounts are configured (or they could not be counted): legacy "
            "'primary' refs with no recorded account are reported calendar_inaccessible, "
            "never guessed.",
            file=sys.stderr,
        )

    rows = build_rows(state, scoped.calendar_api.getClient(), test_literals, scope)
    output_text = render(rows, args.format)

    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"Wrote {len(rows)} rows to {args.output}", file=sys.stderr)
    else:
        print(output_text)


if __name__ == "__main__":
    main()
