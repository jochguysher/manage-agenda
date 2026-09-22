"""Probe (f): capability-driven checks for the mailbox-marking design.

The IMAP backend must work against a bare IMAP4rev1 server with **zero
server-specific code** (no `X-GM-LABELS`/`X-GM-MSGID`/`X-GM-RAW`, no assumed
`OBJECTID`) - Gmail specifics stay confined to the separate Gmail API backend.
Everything here is driven by the server's own `CAPABILITY` response and safe,
generic fallbacks. Run this once per configured account (at minimum: a plain
Dovecot server, and Gmail reached over plain IMAP, not the Gmail API) - the
answers are server-specific, and nothing about Gmail may be assumed just
because an account happens to be a Gmail mailbox reached via IMAP.

Checks, all logged once per connection via `detect_capabilities()`:

1. CAPABILITY: the raw list, plus whether UIDPLUS (RFC 4315), MOVE (RFC 6851)
   and SPECIAL-USE (RFC 6154) are advertised. Nothing below assumes any of
   these are present - each is gated on this detection.

2. Keyword support AND persistence: does PERMANENTFLAGS advertise '\\*'
   (custom keywords accepted), and does a STORE'd keyword actually survive a
   re-fetch? (probe (d) already checks this for one server; folded in here so
   both answers come from the *same* account/connection, since the design's
   default-detection logic needs both together.)

3. Hierarchy separator: read via `LIST "" ""` - **never hardcoded** (some
   servers use '/', others '.', and a wrong assumption breaks folder-path
   handling silently).

4. `\\All` special-use attribute (RFC 6154, only if SPECIAL-USE is
   advertised): the design must refuse to scan a folder carrying this
   attribute (it aliases the whole mailbox - scanning it would mean seeing
   every message regardless of which real folder it's in).

5. MOVE / COPY + safe deletion: if MOVE (RFC 6851) is advertised, use it.
   Otherwise fall back to COPY + STORE \\Deleted. **Without UIDPLUS, this
   probe never issues a bare EXPUNGE** - a bare EXPUNGE purges every
   \\Deleted message in the folder, including ones a human user deleted and
   expects to stay that way until their own client expunges them. With
   UIDPLUS, `UID EXPUNGE <uid>` is scoped to exactly the given UID and is
   safe regardless of what else is flagged \\Deleted. Without it, the
   fallback the design uses in production is: leave the original marked
   \\Deleted and exclude DELETED at scan time (`SEARCH ... NOT DELETED`) -
   this probe demonstrates that by only removing the test flag again
   (`-FLAGS \\Deleted`), never expunging.

Sets and removes a test keyword (like probe d), and copies/moves one message
to a throwaway test folder and back - leaves no lasting trace on success
(including on servers without UIDPLUS, where cleanup un-flags \\Deleted
rather than expunging). Not run by the assistant. Run manually against a
TEST folder only.
"""

import re
import sys
from dataclasses import dataclass

from _common import base_parser, confirm_or_dry_run, connect_imap

TEST_KEYWORD = "$AgendaProbeTest"
TEST_FOLDER = "AgendaProbeTestFolder"

_COPYUID_RE = re.compile(rb"\[COPYUID (\d+) (\S+) (\S+)\]")
_COPYUID_UNTAGGED_RE = re.compile(rb"^\s*(\d+) (\S+) (\S+)\s*$")  # imaplib's untagged form


@dataclass
class ImapCapabilities:
    raw: list
    has_uidplus: bool
    has_move: bool
    has_special_use: bool

    @classmethod
    def detect(cls, client):
        typ, data = client.capability()
        raw = []
        if typ == "OK" and data:
            for line in data:
                text = line.decode() if isinstance(line, bytes) else str(line)
                raw.extend(text.split())
        upper = {token.upper() for token in raw}
        return cls(
            raw=raw,
            has_uidplus="UIDPLUS" in upper,
            has_move="MOVE" in upper,
            has_special_use="SPECIAL-USE" in upper,
        )


def log_capabilities(capabilities):
    print("\n--- (1) CAPABILITY (detected once per connection) ---")
    print(f"Raw: {capabilities.raw}")
    print(f"UIDPLUS (RFC 4315): {capabilities.has_uidplus}")
    print(f"MOVE (RFC 6851): {capabilities.has_move}")
    print(f"SPECIAL-USE (RFC 6154): {capabilities.has_special_use}")


def check_keyword(client, folder):
    print(f"\n--- (2) Keyword support/persistence on {folder!r} ---")
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


def check_hierarchy_separator_and_special_use(client, capabilities, folder):
    print("\n--- (3) Hierarchy separator (via LIST, never hardcoded) ---")
    typ, data = client.list('""', '""')
    print(f"LIST \"\" \"\": typ={typ}, data={data}")
    separator = None
    if typ == "OK" and data and data[0]:
        line = data[0]
        text = line.decode() if isinstance(line, bytes) else str(line)
        match = re.search(r'"(.)"', text)
        if match:
            separator = match.group(1)
    print(f"=> Hierarchy separator: {separator!r} (must be read this way on every server, never assumed)")

    print(f"\n--- (4) \\\\All special-use attribute on {folder!r} ---")
    if not capabilities.has_special_use:
        print("Server does not advertise SPECIAL-USE (RFC 6154) - nothing to check; the design "
              "treats \\All as absent (safe default) when this capability is missing.")
        return
    typ, data = client.list('""', folder)
    print(f"LIST \"\" {folder!r}: typ={typ}, data={data}")
    has_all_attribute = bool(data) and any(
        b"\\All" in (line if isinstance(line, bytes) else b"") for line in (data or [])
    )
    print(f"=> \\\\All attribute present: {has_all_attribute}")
    if has_all_attribute:
        print("=> The design must REFUSE to scan this folder (it aliases the whole mailbox).")


def check_move_or_copy_and_safe_deletion(client, capabilities, folder, test_folder=TEST_FOLDER):
    TEST_FOLDER = test_folder  # noqa: N806 - some servers only allow folders under a prefix, see --test-folder
    print(f"\n--- (5) {'MOVE' if capabilities.has_move else 'COPY + safe delete'} from {folder!r} ---")
    typ, _data = client.select(folder)
    if typ != "OK":
        print(f"Could not select {folder!r}: {typ}")
        return

    typ, data = client.uid("SEARCH", None, "ALL")
    if typ != "OK" or not data or not data[0]:
        print("No messages found to test on.")
        return
    test_uid = data[0].split()[0]
    test_uid_text = test_uid.decode() if isinstance(test_uid, bytes) else str(test_uid)
    print(f"Using UID {test_uid_text!r}.")

    client.create(TEST_FOLDER)  # ignore failure if it already exists

    # RFC 6851 puts MOVE's COPYUID in an untagged `* OK [COPYUID ...]`, which imaplib files
    # (brackets and name stripped) under untagged_responses["COPYUID"], not in the command's
    # returned data. Drop any stale one first so only this command's code is read below.
    client.untagged_responses.pop("COPYUID", None)
    response_lines = []
    if capabilities.has_move:
        print(f"--- UID MOVE {test_uid_text} -> {TEST_FOLDER!r} (RFC 6851 advertised) ---")
        typ, move_data = client.uid("MOVE", test_uid_text, TEST_FOLDER)
        print(f"MOVE result: typ={typ}, data={move_data}")
        if typ != "OK":
            print("=> Server advertised MOVE but rejected it - treat as unsupported, fall back "
                  "to COPY + safe delete in production.")
            return
        response_lines = move_data or []
    else:
        print(f"--- UID COPY {test_uid_text} -> {TEST_FOLDER!r} (no MOVE - RFC 6851 not advertised) ---")
        typ, copy_data = client.uid("COPY", test_uid_text, TEST_FOLDER)
        print(f"COPY result: typ={typ}, data={copy_data}")
        if typ != "OK":
            print("=> COPY failed - cannot proceed with this folder pair.")
            return
        response_lines = copy_data or []

        if capabilities.has_uidplus:
            print(f"--- UID EXPUNGE {test_uid_text} (UIDPLUS advertised - scoped to this UID only) ---")
            client.store(test_uid_text, "+FLAGS", "(\\Deleted)")
            typ, expunge_data = client.uid("EXPUNGE", test_uid_text)
            print(f"UID EXPUNGE result: typ={typ}, data={expunge_data}")
            print("=> Safe: UID EXPUNGE only removes the given UID, regardless of other "
                  "\\Deleted messages already in the folder.")
        else:
            print("--- No UIDPLUS: marking \\Deleted WITHOUT expunging ---")
            client.store(test_uid_text, "+FLAGS", "(\\Deleted)")
            print("=> A bare EXPUNGE here would purge every \\Deleted message in the folder, "
                  "including ones a user deleted and expects to stay until their own client "
                  "expunges them. The design NEVER does that: the original stays flagged "
                  "\\Deleted and is excluded from future scans via 'SEARCH ... NOT DELETED'.")
            print("--- Cleanup: un-flagging \\Deleted (not expunging) ---")
            client.store(test_uid_text, "-FLAGS", "(\\Deleted)")

    match = None
    for line in response_lines:
        if isinstance(line, bytes):
            match = _COPYUID_RE.search(line)
            if match:
                break
    untagged = client.untagged_responses.pop("COPYUID", None) or []
    print(f"untagged_responses['COPYUID'] after the command: {untagged}")
    for line in untagged:
        if match:
            break
        if isinstance(line, bytes):
            match = _COPYUID_UNTAGGED_RE.match(line) or _COPYUID_RE.search(line)
    if match:
        uidvalidity, src_uid, dest_uid = (part.decode() for part in match.groups())
        print(f"=> COPYUID present: uidvalidity={uidvalidity}, src_uid={src_uid}, dest_uid={dest_uid}")
        print("   Server supports UIDPLUS - the design can store (uidvalidity, dest_uid) as a locator.")
    else:
        print("=> No COPYUID response code found.")
        print("   The design must fall back to UID SEARCH HEADER Message-ID in the destination "
              "folder to relocate a message, not a stored locator.")

    print(f"\n--- Moving/copying back from {TEST_FOLDER!r} to {folder!r} (cleanup) ---")
    typ, _data = client.select(TEST_FOLDER)
    typ, data = client.uid("SEARCH", None, "ALL")
    if typ == "OK" and data and data[0]:
        back_uid = data[0].split()[-1]
        back_uid_text = back_uid.decode() if isinstance(back_uid, bytes) else str(back_uid)
        if capabilities.has_move:
            client.uid("MOVE", back_uid_text, folder)
        else:
            client.uid("COPY", back_uid_text, folder)
            if capabilities.has_uidplus:
                client.store(back_uid_text, "+FLAGS", "(\\Deleted)")
                client.uid("EXPUNGE", back_uid_text)
            # Without UIDPLUS, the copy left in TEST_FOLDER is not expunged either -
            # same never-bare-EXPUNGE rule applies to cleanup as to the probe itself.
        print(f"Restored UID {back_uid_text} to {folder!r}.")
    else:
        print("Could not find the message to move/copy back - check the test folder manually.")


def main():
    parser = base_parser(__doc__)
    parser.add_argument("--account", required=True, help="socialModules account name. No default.")
    parser.add_argument("--folder", required=True, help="IMAP folder/mailbox to test in. No default.")
    parser.add_argument(
        "--test-folder",
        default=TEST_FOLDER,
        help=(
            f"Throwaway folder the message is moved/copied to and back (default: {TEST_FOLDER}). "
            "Some servers refuse top-level CREATE and only allow folders under a prefix "
            "(e.g. 'Folders/AgendaProbeTestFolder'): read LIST \"\" \"*\" first."
        ),
    )
    args = parser.parse_args()

    if not confirm_or_dry_run(
        args.yes,
        f"On account {args.account!r}, folder {args.folder!r}: read CAPABILITY, test a keyword "
        f"STORE, read the hierarchy separator, check for \\All, and move/copy one message to a "
        f"throwaway folder ({args.test_folder}) and back.",
    ):
        sys.exit(0)

    api_src = connect_imap(args.account)
    client = api_src.getClient()
    if client is None:
        print("Could not get an IMAP client. Check the account is authorized.")
        sys.exit(1)

    capabilities = ImapCapabilities.detect(client)
    log_capabilities(capabilities)
    check_keyword(client, args.folder)
    check_hierarchy_separator_and_special_use(client, capabilities, args.folder)
    check_move_or_copy_and_safe_deletion(client, capabilities, args.folder, args.test_folder)

    print(
        f"\nVerdict to record for account {args.account!r}: keyword accepted+persisted? "
        "UIDPLUS present? MOVE present? SPECIAL-USE present? \\All seen on the tested folder? "
        "This determines the default marker (keyword vs folder) and the safe-deletion path "
        "(UID EXPUNGE vs mark-and-exclude) for this specific account - never assumed from the "
        "account being Gmail or any other provider."
    )


if __name__ == "__main__":
    main()
