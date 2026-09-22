"""Probe (d): does the target IMAP server's PERMANENTFLAGS advertise support for a custom
keyword (as opposed to only the standard \\Seen/\\Deleted/\\Answered/... flags)? If so, can we
actually STORE it on a message and read it back?

This is a per-server fact (Dovecot, Gmail's IMAP bridge, ProtonMail Bridge, etc. may all
differ) - the design's "IMAP keyword instead of Trash move" step only works where this probe
says yes. Where it says no, the design must fall back to the dedicated-folder approach.

Sets and then removes the test keyword on the first message found in --folder, so it leaves
no lasting trace on success. Not run by the assistant. Run manually against a TEST folder only
(a folder you don't mind a flag briefly appearing on one message in).
"""

import sys

from _common import base_parser, confirm_or_dry_run, connect_imap

TEST_KEYWORD = "$AgendaProbeTest"


def main():
    parser = base_parser(__doc__)
    parser.add_argument("--account", required=True, help="socialModules account name. No default.")
    parser.add_argument("--folder", required=True, help="IMAP folder/mailbox to test in. No default.")
    args = parser.parse_args()

    if not confirm_or_dry_run(
        args.yes,
        f"Select {args.folder!r} on account {args.account!r}, inspect PERMANENTFLAGS, then "
        f"briefly STORE and remove a test keyword ({TEST_KEYWORD}) on one message.",
    ):
        sys.exit(0)

    api_src = connect_imap(args.account)
    client = api_src.getClient()
    if client is None:
        print("Could not get an IMAP client. Check the account is authorized.")
        sys.exit(1)

    typ, _data = client.select(args.folder)
    if typ != "OK":
        print(f"Could not select {args.folder!r}: {typ}")
        sys.exit(1)

    print("\n--- PERMANENTFLAGS from the SELECT response ---")
    permanent_flags = client.untagged_responses.get("PERMANENTFLAGS")
    print(f"Raw: {permanent_flags}")
    flags_text = (permanent_flags[0].decode() if permanent_flags else "") or ""
    accepts_any = "\\*" in flags_text
    print(f"Server advertises '\\\\*' (accepts arbitrary new keywords): {accepts_any}")

    typ, data = client.search(None, "ALL")
    if typ != "OK" or not data or not data[0]:
        print(f"No messages found in {args.folder!r} to test STORE on. Stopping here.")
        sys.exit(0)
    sequence = data[0].split()[0]
    sequence_text = sequence.decode() if isinstance(sequence, bytes) else str(sequence)
    print(f"\nUsing message sequence {sequence_text!r} for the STORE test.")

    print(f"\n--- STORE +FLAGS ({TEST_KEYWORD}) ---")
    typ, store_data = client.store(sequence_text, "+FLAGS", f"({TEST_KEYWORD})")
    print(f"STORE result: typ={typ}, data={store_data}")

    typ, fetch_data = client.fetch(sequence_text, "(FLAGS)")
    print(f"FLAGS after STORE: {fetch_data}")
    kept = fetch_data and TEST_KEYWORD.encode() in b"".join(
        part if isinstance(part, bytes) else b"" for part in fetch_data
    )
    print(f"Custom keyword actually present after STORE: {bool(kept)}")

    print(f"\n--- Cleanup: STORE -FLAGS ({TEST_KEYWORD}) ---")
    typ, _data = client.store(sequence_text, "-FLAGS", f"({TEST_KEYWORD})")
    print(f"Cleanup STORE result: typ={typ}")

    print(
        "\nVerdict to record: did PERMANENTFLAGS advertise '\\*', and did the custom keyword "
        "actually stick when fetched back? Paste this output back into the conversation."
    )


if __name__ == "__main__":
    main()
