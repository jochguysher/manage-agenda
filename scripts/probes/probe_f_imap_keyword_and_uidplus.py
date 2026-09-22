"""Probe (f): for the target IMAP server, two independent checks needed for the mailbox-
marking design:

1. Keyword support AND persistence: does PERMANENTFLAGS advertise '\\*' (custom keywords
   accepted), and does a STORE'd keyword actually survive a re-fetch? (probe (d) already
   checks this for one server; this probe folds the same check in alongside (2) so both can
   be recorded together per server, since the design's default-detection logic needs both
   answers from the *same* account to decide keyword vs folder marking.)

2. MOVE + UIDPLUS/COPYUID support: Python's stdlib imaplib has NO built-in support for MOVE
   (RFC 6851) or UIDPLUS/COPYUID (RFC 4315) - both are sent/parsed manually here via the raw
   `uid()` escape hatch. This finds out whether the server accepts UID MOVE at all, and
   whether its response includes a parseable `[COPYUID uidvalidity src-uid dest-uid]` code
   manage-agenda could use to remember exactly where a moved message landed.

Re-run this once per configured account (Dovecot, Gmail-via-IMAP, ProtonMail Bridge, etc.) -
the answer is server-specific, and the design's default marker (keyword vs folder) is chosen
per account based on this probe's result for that account.

Sets and removes a test keyword (like probe d), and moves one message to a throwaway test
folder and back (like the design's own move-and-restore step) - leaves no lasting trace on
success. Not run by the assistant. Run manually against a TEST folder only.
"""

import re
import sys

from _common import base_parser, confirm_or_dry_run, connect_imap

TEST_KEYWORD = "$AgendaProbeTest"
TEST_FOLDER = "AgendaProbeTestFolder"

_COPYUID_RE = re.compile(rb"\[COPYUID (\d+) (\S+) (\S+)\]")


def check_keyword(client, folder):
    print(f"\n--- (1) Keyword support/persistence on {folder!r} ---")
    typ, _data = client.select(folder)
    if typ != "OK":
        print(f"Could not select {folder!r}: {typ}")
        return

    permanent_flags = client.untagged_responses.get("PERMANENTFLAGS")
    flags_text = (permanent_flags[0].decode() if permanent_flags else "") or ""
    accepts_any = "\\*" in flags_text
    print(f"PERMANENTFLAGS: {permanent_flags}")
    print(f"Advertises '\\\\*' (accepts arbitrary new keywords): {accepts_any}")

    typ, data = client.search(None, "ALL")
    if typ != "OK" or not data or not data[0]:
        print("No messages found to test STORE on.")
        return
    sequence = data[0].split()[0]
    sequence_text = sequence.decode() if isinstance(sequence, bytes) else str(sequence)

    client.store(sequence_text, "+FLAGS", f"({TEST_KEYWORD})")
    typ, fetch_data = client.fetch(sequence_text, "(FLAGS)")
    kept = fetch_data and any(
        TEST_KEYWORD.encode() in (part if isinstance(part, bytes) else b"") for part in fetch_data
    )
    print(f"Custom keyword actually present after STORE: {bool(kept)}")
    client.store(sequence_text, "-FLAGS", f"({TEST_KEYWORD})")
    print("Cleaned up (keyword removed).")


def check_move_and_uidplus(client, folder):
    print(f"\n--- (2) UID MOVE + UIDPLUS/COPYUID from {folder!r} ---")
    typ, _data = client.select(folder)
    if typ != "OK":
        print(f"Could not select {folder!r}: {typ}")
        return

    typ, data = client.uid("SEARCH", None, "ALL")
    if typ != "OK" or not data or not data[0]:
        print("No messages found to test MOVE on.")
        return
    test_uid = data[0].split()[0]
    test_uid_text = test_uid.decode() if isinstance(test_uid, bytes) else str(test_uid)
    print(f"Using UID {test_uid_text!r}.")

    client.create(TEST_FOLDER)  # ignore failure if it already exists

    print(f"--- UID MOVE {test_uid_text} -> {TEST_FOLDER!r} ---")
    typ, move_data = client.uid("MOVE", test_uid_text, TEST_FOLDER)
    print(f"MOVE result: typ={typ}, data={move_data}")
    if typ != "OK":
        print("=> Server does NOT support UID MOVE (RFC 6851). Folder-marking would need "
              "COPY + STORE \\Deleted + EXPUNGE instead, without a MOVE-based UIDPLUS shortcut.")
        return

    match = None
    for line in move_data or []:
        if isinstance(line, bytes):
            match = _COPYUID_RE.search(line)
            if match:
                break
    if match:
        uidvalidity, src_uid, dest_uid = (part.decode() for part in match.groups())
        print(f"=> COPYUID present: uidvalidity={uidvalidity}, src_uid={src_uid}, dest_uid={dest_uid}")
        print("   Server supports UIDPLUS - the design can store (uidvalidity, dest_uid) as a locator.")
    else:
        print("=> MOVE succeeded but no COPYUID response code found.")
        print("   Server likely lacks UIDPLUS - the design must fall back to UID SEARCH HEADER "
              "Message-ID in the destination folder to relocate a message, not a stored locator.")

    print(f"\n--- Moving back from {TEST_FOLDER!r} to {folder!r} (cleanup) ---")
    typ, _data = client.select(TEST_FOLDER)
    typ, data = client.uid("SEARCH", None, "ALL")
    if typ == "OK" and data and data[0]:
        back_uid = data[0].split()[-1]
        back_uid_text = back_uid.decode() if isinstance(back_uid, bytes) else str(back_uid)
        client.uid("MOVE", back_uid_text, folder)
        print(f"Moved UID {back_uid_text} back to {folder!r}.")
    else:
        print("Could not find the message to move back - check the test folder manually.")


def main():
    parser = base_parser(__doc__)
    parser.add_argument("--account", required=True, help="socialModules account name. No default.")
    parser.add_argument("--folder", required=True, help="IMAP folder/mailbox to test in. No default.")
    args = parser.parse_args()

    if not confirm_or_dry_run(
        args.yes,
        f"On account {args.account!r}, folder {args.folder!r}: test a keyword STORE, then "
        f"UID MOVE one message to a throwaway folder ({TEST_FOLDER}) and back.",
    ):
        sys.exit(0)

    api_src = connect_imap(args.account)
    client = api_src.getClient()
    if client is None:
        print("Could not get an IMAP client. Check the account is authorized.")
        sys.exit(1)

    check_keyword(client, args.folder)
    check_move_and_uidplus(client, args.folder)

    print(
        f"\nVerdict to record for account {args.account!r}: keyword accepted+persisted? "
        "MOVE supported? COPYUID present? This determines the default marker "
        "(keyword vs folder) for this specific account."
    )


if __name__ == "__main__":
    main()
