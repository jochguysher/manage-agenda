"""Probe (a): after events.delete(), does events.get(eventId=...) still return the event -
and if so, does extendedProperties survive? Also checks events.list(showDeleted=True) on the
same id, since the "restore" design step (events.get -> patch status=confirmed) specifically
needs the direct get() path to work, not just visibility through a sync delta.

Google's docs (see docs/investigation-limite1.md) only guarantee `id` survives on a deleted
event - extendedProperties survival is explicitly NOT guaranteed. This script finds out what
actually happens for a single (non-recurring) event on this account, right now.

Not run by the assistant. Run manually against a TEST calendar only.
"""

import sys
import time

import googleapiclient.errors

from _common import base_parser, confirm_or_dry_run, connect_calendar


def main():
    parser = base_parser(__doc__)
    parser.add_argument("--calendar-id", required=True, help="Test calendar id. No default.")
    args = parser.parse_args()

    client = connect_calendar(args.calendar_id)

    event_body = {
        "summary": "manage-agenda probe (a) - safe to delete",
        "start": {"dateTime": "2030-01-01T10:00:00Z"},
        "end": {"dateTime": "2030-01-01T11:00:00Z"},
        "extendedProperties": {"private": {"probe": "a", "origin": "manage-agenda-probe"}},
    }

    if not confirm_or_dry_run(
        args.yes, f"Insert a test event on calendar {args.calendar_id!r}, then delete it."
    ):
        sys.exit(0)

    inserted = client.events().insert(calendarId=args.calendar_id, body=event_body).execute()
    event_id = inserted["id"]
    print(f"Inserted event id={event_id}")

    client.events().delete(calendarId=args.calendar_id, eventId=event_id).execute()
    print("Deleted.")

    time.sleep(2)  # give the API a moment; if this matters, that's itself a finding

    print("\n--- events.get() on the deleted id ---")
    try:
        got = client.events().get(calendarId=args.calendar_id, eventId=event_id).execute()
        print("get() succeeded. Full response:")
        import json

        print(json.dumps(got, indent=2))
        has_extended = bool(got.get("extendedProperties"))
        print(f"\nstatus field: {got.get('status')!r}")
        print(f"extendedProperties present: {has_extended}")
        if has_extended:
            print(f"extendedProperties content: {got.get('extendedProperties')}")
    except googleapiclient.errors.HttpError as error:
        status = getattr(getattr(error, "resp", None), "status", None)
        print(f"get() raised HttpError, status={status}")
        print(f"Body: {error}")

    print("\n--- events.list(showDeleted=True, privateExtendedProperty=...) for comparison ---")
    try:
        listed = (
            client.events()
            .list(
                calendarId=args.calendar_id,
                showDeleted=True,
                singleEvents=True,
                privateExtendedProperty="probe=a",
                timeMin="2029-12-31T00:00:00Z",
                timeMax="2030-01-02T00:00:00Z",
            )
            .execute()
        )
        items = listed.get("items", [])
        print(f"{len(items)} item(s) found via list(showDeleted=True).")
        for item in items:
            print(f"  id={item.get('id')} status={item.get('status')} "
                  f"extendedProperties={item.get('extendedProperties')}")
    except googleapiclient.errors.HttpError as error:
        print(f"list() raised HttpError: {error}")

    print(
        "\nVerdict to record: does direct events.get() on a deleted single event return the "
        "event at all, and with extendedProperties? Does events.list(showDeleted=True) find it "
        "even when direct get() does not? Paste this output back into the conversation."
    )


if __name__ == "__main__":
    main()
