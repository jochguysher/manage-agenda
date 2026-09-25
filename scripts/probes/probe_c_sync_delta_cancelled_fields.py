"""Probe (c): in an incremental-sync (syncToken) delta, what fields does a cancelled item
actually carry? Google's docs only guarantee `id` (see docs/investigation-limite1.md) - this
finds out whether extendedProperties, summary, etc. are also present in practice for this
account, which determines whether the design can identify a deleted event's source directly
from the sync delta, or must always follow up with a separate events.get()/probe (a).

Not run by the assistant. Run manually against a TEST calendar only.
"""

import json
import sys
import time

import googleapiclient.errors
from _common import base_parser, confirm_or_dry_run, connect_calendar


def full_sync_and_seed_token(client, calendar_id):
    """One-off full listing to get a starting syncToken, the same way
    manage_agenda.extraction._list_all_pages's bootstrap path works."""
    page_token = None
    next_sync_token = None
    while True:
        response = client.events().list(
            calendarId=calendar_id,
            showDeleted=True,
            singleEvents=True,
            pageToken=page_token,
        ).execute()
        next_sync_token = response.get("nextSyncToken", next_sync_token)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return next_sync_token


def main():
    parser = base_parser(__doc__)
    parser.add_argument("--calendar-id", required=True, help="Test calendar id. No default.")
    args = parser.parse_args()

    client = connect_calendar(args.calendar_id)

    if not confirm_or_dry_run(
        args.yes,
        f"Seed a sync token on calendar {args.calendar_id!r}, insert a test event, delete it, "
        "then read the incremental sync delta to see what the cancelled item looks like.",
    ):
        sys.exit(0)

    print("Seeding sync token (full listing)...")
    token = full_sync_and_seed_token(client, args.calendar_id)
    print(f"Got sync token: {token[:20]}..." if token else "No sync token returned - stopping.")
    if not token:
        sys.exit(1)

    event_body = {
        "summary": "manage-agenda probe (c) - safe to delete",
        "start": {"dateTime": "2030-01-01T10:00:00Z"},
        "end": {"dateTime": "2030-01-01T11:00:00Z"},
        "extendedProperties": {"private": {"probe": "c", "origin": "manage-agenda-probe"}},
    }
    inserted = client.events().insert(calendarId=args.calendar_id, body=event_body).execute()
    event_id = inserted["id"]
    print(f"Inserted event id={event_id}")

    client.events().delete(calendarId=args.calendar_id, eventId=event_id).execute()
    print("Deleted.")
    time.sleep(2)

    print("\n--- Reading the incremental sync delta ---")
    page_token = None
    found = None
    while True:
        try:
            response = client.events().list(
                calendarId=args.calendar_id,
                showDeleted=True,
                singleEvents=True,
                syncToken=token,
                pageToken=page_token,
            ).execute()
        except googleapiclient.errors.HttpError as error:
            status = getattr(getattr(error, "resp", None), "status", None)
            print(f"Incremental sync call failed, status={status}: {error}")
            sys.exit(1)
        for item in response.get("items", []):
            if item.get("id") == event_id:
                found = item
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    if found is None:
        print(f"Event {event_id} did not appear in the delta at all. That is itself a finding.")
    else:
        print(f"Found the cancelled item. Full contents:\n{json.dumps(found, indent=2)}")
        print(f"\nFields present: {sorted(found.keys())}")
        print(f"extendedProperties present: {'extendedProperties' in found}")

    print(
        "\nVerdict to record: which fields (beyond id/status) survive on a cancelled sync-delta "
        "item for this account? Paste the field list back into the conversation."
    )


if __name__ == "__main__":
    main()
