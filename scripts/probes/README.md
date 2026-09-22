# Probe scripts — verify real API behavior before designing against it

These are throwaway verification tools for the "limite 1" redesign (deleted-event
recreation). Each one checks one specific assumption from the design spec against the
*real* Google Calendar / IMAP API, because the official docs either don't say, or
explicitly disclaim a guarantee (see `docs/investigation-limite1.md` for the full writeup).

**They are not part of the application. They are not covered by the test suite. They are
not meant to be kept once the questions they answer are settled** — delete this directory
once Phase 2 (the design plan) is finalized and no longer needs re-verification.

## Safety rules — read before running any of these

- **Every script requires an explicit `--calendar-id` (and, for the IMAP one,
  `--folder`) with no default.** There is no fallback to "the first configured
  calendar" or similar — you must name a calendar/folder you are fine creating and
  deleting test events/messages in. Use a dedicated test calendar, not a real one.
- **Every mutating step prints what it is about to do and requires `--yes` on the
  command line to proceed.** Without `--yes`, the script only prints what it *would* do
  and exits.
- **None of these were run by the assistant.** They were written and left for you to run
  manually, against your own test calendar/mailbox, per your explicit instruction.
- Each script prints a plain-language verdict at the end (confirmed / contradicted /
  inconclusive) — paste that back into the conversation rather than the raw JSON, unless
  something looks surprising and you want a second opinion on the raw response.

## Scripts

| Script | Verifies (spec assumption) |
|---|---|
| `probe_a_extended_properties_on_deleted.py` | (a) Does `events.get` on a deleted event still return `extendedProperties`? |
| `probe_b_patch_restore_cancelled.py` | (b) Does `events.patch(status="confirmed")` restore a cancelled event, and until when? |
| `probe_c_sync_delta_cancelled_fields.py` | (c) What fields does a cancelled item carry in an incremental-sync (`syncToken`) delta? |
| `probe_d_imap_custom_keyword.py` | (d) Does the target IMAP server's `PERMANENTFLAGS` accept a custom keyword (e.g. `$AgendaDone`)? |
| `probe_e_deleted_id_reuse.py` | (e, not in the original four) Can a new event reuse a deleted event's id? Load-bearing for the `requeue` resolution step. |

## Usage

```bash
uv run python scripts/probes/probe_a_extended_properties_on_deleted.py --calendar-id <id> --yes
uv run python scripts/probes/probe_b_patch_restore_cancelled.py --calendar-id <id> --yes
uv run python scripts/probes/probe_c_sync_delta_cancelled_fields.py --calendar-id <id> --yes
uv run python scripts/probes/probe_d_imap_custom_keyword.py --account <name> --folder <folder> --yes
uv run python scripts/probes/probe_e_deleted_id_reuse.py --calendar-id <id> --yes
```

Run without `--yes` first to see exactly what each script will do.
