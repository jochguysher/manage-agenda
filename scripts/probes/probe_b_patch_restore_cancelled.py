"""Probe (b): after events.delete(), does events.patch(eventId=..., body={"status": "confirmed"})
actually restore the event (i.e. does it become a normal, listable, retrievable event again)?

"Until when" (how long after deletion this still works) can't be answered by a single run -
this script tests the immediate case only. To test the time window, re-run this script's
"attempt restore" step alone (see --event-id) against an event you deleted earlier, at
increasing delays (1 hour, 1 day, 1 week...) and record when it stops working.

Not run by the assistant. Run manually against a TEST calendar only.
"""

import sys
import time

import googleapiclient.errors
from _common import base_parser, confirm_or_dry_run, connect_calendar


def attempt_restore(client, calendar_id, event_id):
    print(f"\n--- events.patch(eventId={event_id}, body={{'status': 'confirmed'}}) ---")
    try:
        patched = client.events().patch(
            calendarId=calendar_id, eventId=event_id, body={"status": "confirmed"}
        ).execute()
        print(f"patch() succeeded. Returned status={patched.get('status')!r}")
    except googleapiclient.errors.HttpError as error:
        status = getattr(getattr(error, "resp", None), "status", None)
        print(f"patch() raised HttpError, status={status}: {error}")
        return

    print("\n--- events.get() after the patch, to confirm it really is restored ---")
    try:
        got = client.events().get(calendarId=calendar_id, eventId=event_id).execute()
        print(f"status={got.get('status')!r}, summary={got.get('summary')!r}")
    except googleapiclient.errors.HttpError as error:
        print(f"get() after patch raised HttpError: {error}")

    print("\n--- events.list() (normal listing, no showDeleted) to confirm it shows up normally ---")
    try:
        listed = (
            client.events()
            .list(
                calendarId=calendar_id,
                singleEvents=True,
                timeMin="2029-12-31T00:00:00Z",
                timeMax="2030-01-02T00:00:00Z",
            )
            .execute()
        )
        ids = [item.get("id") for item in listed.get("items", [])]
        print(f"Event id found in a normal (non-showDeleted) list(): {event_id in ids}")
    except googleapiclient.errors.HttpError as error:
        print(f"list() raised HttpError: {error}")


def main():
    parser = base_parser(__doc__)
    parser.add_argument("--calendar-id", required=True, help="Test calendar id. No default.")
    parser.add_argument(
        "--event-id",
        default=None,
        help=(
            "Skip insert+delete and attempt restore directly on this existing (already "
            "deleted) event id - use this to re-test the time window later."
        ),
    )
    args = parser.parse_args()

    client = connect_calendar(args.calendar_id)

    if args.event_id:
        if not confirm_or_dry_run(
            args.yes, f"Attempt to restore existing event id={args.event_id!r}."
        ):
            sys.exit(0)
        attempt_restore(client, args.calendar_id, args.event_id)
        return

    event_body = {
        "summary": "manage-agenda probe (b) - safe to delete",
        "start": {"dateTime": "2030-01-01T10:00:00Z"},
        "end": {"dateTime": "2030-01-01T11:00:00Z"},
        "extendedProperties": {"private": {"probe": "b", "origin": "manage-agenda-probe"}},
    }

    if not confirm_or_dry_run(
        args.yes,
        f"Insert a test event on calendar {args.calendar_id!r}, delete it, then immediately "
        "attempt to restore it via patch(status='confirmed').",
    ):
        sys.exit(0)

    inserted = client.events().insert(calendarId=args.calendar_id, body=event_body).execute()
    event_id = inserted["id"]
    print(f"Inserted event id={event_id}")

    client.events().delete(calendarId=args.calendar_id, eventId=event_id).execute()
    print("Deleted.")
    time.sleep(2)

    attempt_restore(client, args.calendar_id, event_id)

    print(
        f"\nVerdict to record: did patch(status='confirmed') restore event {event_id}? "
        "Save this event id and re-run with --event-id after a delay to find the time window."
    )


if __name__ == "__main__":
    main()
