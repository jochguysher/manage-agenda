"""Probe (e): after events.delete() on an event with a client-supplied id, does inserting a
NEW event with that same id succeed, or does Google reject reuse of a deleted event's id?

This is not one of the spec's four lettered assumptions, but it is the single most
load-bearing unknown for the whole design: the `requeue` resolution step relies on being
able to insert again under the *same* deterministic id (derived from mail_identity + event
index) once the source message is requeued and reprocessed. If Google rejects id reuse
(deleted-id "tombstoning"), the design needs a fallback (e.g. append a generation suffix to
the id on requeue) instead of assuming a clean re-insert.

Not run by the assistant. Run manually against a TEST calendar only.
"""

import sys
import time

import googleapiclient.errors

from _common import base_parser, confirm_or_dry_run, connect_calendar

# base32hex: lowercase a-v and 0-9 only, 5-1024 chars (Google's documented constraint).
TEST_ID = "probe5reuse0test"


def main():
    parser = base_parser(__doc__)
    parser.add_argument("--calendar-id", required=True, help="Test calendar id. No default.")
    args = parser.parse_args()

    client = connect_calendar(args.calendar_id)

    if not confirm_or_dry_run(
        args.yes,
        f"Insert an event with id={TEST_ID!r} on calendar {args.calendar_id!r}, delete it, "
        "then attempt to insert a second event reusing the same id.",
    ):
        sys.exit(0)

    event_body = {
        "id": TEST_ID,
        "summary": "manage-agenda probe (e) - first insert - safe to delete",
        "start": {"dateTime": "2030-01-01T10:00:00Z"},
        "end": {"dateTime": "2030-01-01T11:00:00Z"},
    }
    print(f"--- First insert, id={TEST_ID!r} ---")
    try:
        first = client.events().insert(calendarId=args.calendar_id, body=event_body).execute()
        print(f"Insert succeeded. Returned id={first.get('id')!r}")
    except googleapiclient.errors.HttpError as error:
        print(f"First insert failed unexpectedly: {error}")
        sys.exit(1)

    client.events().delete(calendarId=args.calendar_id, eventId=TEST_ID).execute()
    print("Deleted.")
    time.sleep(2)

    reuse_body = {
        "id": TEST_ID,
        "summary": "manage-agenda probe (e) - reused id - safe to delete",
        "start": {"dateTime": "2030-01-02T10:00:00Z"},
        "end": {"dateTime": "2030-01-02T11:00:00Z"},
    }
    print(f"\n--- Second insert, reusing id={TEST_ID!r} ---")
    try:
        second = client.events().insert(calendarId=args.calendar_id, body=reuse_body).execute()
        print(f"Insert succeeded. status={second.get('status')!r}, summary={second.get('summary')!r}")
        print("=> Id reuse after deletion WORKS (at least immediately after deletion).")
    except googleapiclient.errors.HttpError as error:
        status = getattr(getattr(error, "resp", None), "status", None)
        print(f"Second insert failed, status={status}: {error}")
        print("=> Id reuse after deletion is REJECTED (at least immediately after deletion).")
        print(
            "   If so: try instead patching the deleted event back via probe (b)'s approach, "
            "or plan for a generation suffix on requeue (e.g. id + '0' if the base id was "
            "shortened to leave room)."
        )

    print(
        "\nVerdict to record: did the second insert succeed or fail, and with what status? "
        "This determines whether 'requeue = delete tombstone + re-insert same id' is viable."
    )


if __name__ == "__main__":
    main()
