# Investigation: deleted-event recreation ("limite 1") — Phase 1

Scope: read-only investigation for the redesign described in the design spec (see
conversation/commit history). No application code was changed for this phase; only
`scripts/probes/` (verification tools, not shipped) and this document were added.

## 1. Current state, as it exists today

### Ledger (`manage_agenda/sources.py`)

`handled_mail_file()` → `~/.local/share/manage-agenda/handled_mail_ids.json`:

```json
{
  "messages": {
    "<mail_identity>": {
      "events": [{"calendar_id": "...", "event_id": "...", "recorded_at": "2026-..."}],
      "status": "created" | "no_event" | "legacy"
    }
  }
}
```

- `mail_identity()` = the `Message-ID` header (stripped of `<>`), or a sha256 hash of
  `From|Date|Subject` if no `Message-ID` exists.
- Growth: one entry per processed message, forever. `reconcile_handled_events()` only
  *reads* entries whose events are still within `_SYNC_BOOTSTRAP_WINDOW_DAYS` (90d) for
  bootstrap confirmation cost purposes; it does not prune old entries. **The ledger file
  itself grows without bound today** — this is exactly what the spec's constraint targets.
- `event_id`/`calendar_id` refer to a **Google-assigned, non-deterministic** event id
  (see §3). There is currently no way to compute an event's id from `mail_identity` alone.

### `reconcile_handled_events()` (`sources.py:249`)

Groups tracked `(calendar_id, event_id)` pairs by calendar, calls
`sync_calendar_changes()` (extraction.py) once per calendar (syncToken-based), and drops
ledger entries whose events are all reported cancelled. Entries with no recorded event
(`status` != `"created"`) are never touched — they're permanently "handled" with no
way to un-handle them. This is the mechanism the spec wants everything to integrate into.

### Event creation (`extraction.py`, `_publish_event_to_calendar` → `moduleGcalendar.publishApiPost`)

```python
event = more.get("event")            # the dict manage-agenda built - no "id" key ever set
idCal = more.get("idCal")
res = api.events().insert(calendarId=idCal, body=event).execute()
```

**Confirmed: manage-agenda never sets `event["id"]` today.** Every event id in the ledger
is whatever Google auto-generated. This is the exact gap the spec's "deterministic ID"
principle needs to close, and it means the migration concern in the spec (existing events
have non-deterministic ids) is real and unconditional — there are no existing
deterministic-id events to reconcile with.

extendedProperties currently set on every created event (`_stamp_event_identity`,
`_add_ai_metadata_to_event`): `manageAgendaSlot` / `manageAgendaSource` (calendar-scoped
one-way hashes of summary+start[+source_id] — **not reversible**, can't recover
`mail_identity` from them), plus `ai_model_used`, `processing_timestamp`,
`processing_elapsed_time_seconds`, `confidence_score`. **No `origin=manage-agenda` marker
exists today.**

### Log file (`log/{post_id}_{idx}_times.json`, under `config.MSG_TXT_DIR`)

Written via `write_file(file_name, json.dumps(single_event))` — the **pre-publish** local
event dict (after AI-metadata stamping, before the per-calendar identity stamp and before
the real Calendar event id comes back). It does **not** contain the real Calendar event id
or the calendar-scoped extendedProperties. Not currently useful as a "recreate from cache"
source without changes to what gets written to it.

### `_delete_email()` (`sources.py:628`) — what "processed" does to the source message today

- **Gmail** (non-IMAP branch): `api_src.modifyLabels(post_id, label[0], None)` — see §2,
  this removes the "zAgenda" label via a single `messages().modify()` call and adds
  nothing (label param is `None`).
- **IMAP**: `api_src.deletePostId(post_id)` → `moveMails(client, idPost, self.special["Trash"])`
  — see §2, copies to Trash + flags `\Deleted` in the source; **no `EXPUNGE` is issued**
  by this call. Actual purge depends on server behavior on connection close, which this
  code doesn't control.
- Only skipped (message left untouched) when IMAP **and** `source_details.get("mark") ==
  "seen"` — the *only* existing flow where a processed message stays in its scanned
  folder. In that flow, "already handled" exclusion is done purely by ledger membership
  (`handled` set passed into `_fetch_imap_matches`) — **not** by any mailbox-side marker.
  This is exactly the gap principle 2 of the spec wants to close (move the mark onto the
  message itself, so exclusion can happen at the IMAP `SEARCH` level).

## 2. socialModules findings (external dependency, not modified)

Full detail from the sub-investigation; the short version: **no capability gaps found**.
Everything the design needs is either already a public socialModules method, or already
reachable via `api_src.getClient()` — the raw `googleapiclient`/`imaplib` object — the same
way manage-agenda's own code already reaches it elsewhere (e.g. `_mark_imap_seen`,
`sync_calendar_changes`'s direct `events().list()`/`.get()` calls).

| Need | Status |
|---|---|
| Gmail label create/modify/delete | `createLabel`/`updateLabel`/`deleteLabel` exist (`moduleGmail.py`) |
| Gmail OAuth scope for label changes | Already granted: `gmail.readonly`, `gmail.labels`, `gmail.modify` (hardcoded in `moduleGmail.initApi`) — **no re-consent needed** |
| Calendar OAuth scope | `calendar.readonly` + `calendar` (full), already granted |
| IMAP move to an arbitrary (non-Trash) folder | `moveMails(client, ids, folder)` already takes an arbitrary folder — Trash-only is a manage-agenda call-site choice (`deletePostId`), not a socialModules limit |
| IMAP folder creation | `createFolder`/`createChannel` exist (`moduleImap.py`) |
| IMAP custom keyword STORE | No dedicated wrapper, but `getClient()` gives the raw `imaplib` connection already used directly elsewhere in manage-agenda for flag STORE (`_mark_imap_seen`) — same pattern extends to a custom keyword with zero socialModules changes |
| Calendar client-supplied event `id` | `publishApiPost` passes the event dict to `insert()` unmodified — setting `event["id"]` in manage-agenda's own code is enough |
| Calendar `events().patch()` / `.get()` single event | Not exposed by `moduleGcalendar.py`, but manage-agenda already bypasses it and calls `getClient().events().get()/.list()` directly (feature: syncToken detection) — same pattern extends to `.patch()` |

**One thing not resolvable by reading code** (flagged, not a socialModules gap): whether
`modifyLabels(msgId, oldLabelId, labelId=None)` — which builds
`{"removeLabelIds": [oldLabelId], "addLabelIds": [None]}` — is silently accepted or
rejected by the real Gmail API when `addLabelIds` contains a literal `null`. This is the
exact call site the "label exchange" design step (`zAgenda` → a "done" label, in one call
instead of two) would touch, so worth confirming empirically before relying on it, though
it is not one of the spec's four lettered probes.

**Consequence for the spec's `docs/socialModules-proposals.md` step**: not needed. There
is nothing to propose upstream.

## 3. Google Calendar API doc findings — two corrections to spec assumptions

Both fetched from official docs (`developers.google.com/workspace/calendar/api/v3/...`),
not from training-data memory. See the design-spec response for full quotes.

### Correction 1 — client-supplied id + 409 is not a documented guarantee

Confirmed: base32hex, lowercase `a-v` + `0-9`, length 5–1024, unique per calendar
(`events.insert` reference). **But**: Google's own `events.insert` docs state *"Due to
the globally distributed nature of the system, we cannot guarantee that ID collisions
will be detected at event creation time."* No status code (409 or otherwise) is
documented for a collision. **The spec's "Une 409 à l'insertion signifie « a déjà
existé » et doit être gérée explicitement" cannot be relied on as the sole collision
signal** — a collision may silently not surface as an error at all. The design needs a
fallback: after any insert (success or ambiguous failure), a following `events.get()` on
the intended id, or reliance on the idempotent-retry property already built into
`_publish_event_to_calendar` (a duplicate insert is safe *if* the event's own content
would be recognized as already present), rather than 409-or-nothing.

### Correction 2 — extendedProperties is not guaranteed on a deleted/cancelled event

Event resource docs: *"Deleted events are only guaranteed to have the `id` field
populated"* (non-recurring case); cancelled recurring instances are *"only guaranteed to
have values for the `id`, `recurringEventId` and `originalStartTime` fields populated."*
This applies identically to sync-delta cancelled items (same Event resource shape) —
**only `id` (+ `status: "cancelled"`) is guaranteed** in a syncToken delta or on a direct
`get()` of a deleted event. **Consequence: the design cannot rely on reading
`extendedProperties` back off a deleted/cancelled event to identify which message it came
from.** This is not a blocker, though: if the event `id` is itself deterministically
derived from `mail_identity` (+ event index), the id *is* the correlation key — no
extendedProperties read-back is needed to know which message a cancelled id belongs to.
This makes deterministic ids not just a 409-avoidance mechanism but the actual
identification mechanism, which probes (a)/(c) below test directly.

**Not documented anywhere** (confirmed via doc fetch, not assumed): whether
`patch(status="confirmed")` actually restores a cancelled event, and how long a deleted
event remains fetchable via `get()` before permanent purge. Both are genuine unknowns —
this is exactly what probes (a)/(b) exist to test empirically.

## 4. Assumptions requiring empirical verification — status after Phase 1

| # | Assumption | Doc-confirmed? | Probe script |
|---|---|---|---|
| — | Deterministic id charset/length | Yes (§3) | n/a |
| — | 409 on collision | **Contradicted** — not guaranteed (§3, Correction 1) | n/a |
| a | `events.get()` on a deleted event still returns extendedProperties | **Contradicted** — not guaranteed (§3, Correction 2); whether it returns *anything at all* via direct `get()` (vs. only via sync/list `showDeleted`) is untested | `probe_a_extended_properties_on_deleted.py` |
| b | `patch(status="confirmed")` restores a cancelled event, and until when | Undocumented, untested | `probe_b_patch_restore_cancelled.py` |
| c | Which fields survive on a cancelled sync-delta item | Partially doc-confirmed (only `id`+`status` guaranteed); exact real-world set untested | `probe_c_sync_delta_cancelled_fields.py` |
| d | Target IMAP server accepts a custom keyword | Server-dependent, untested | `probe_d_imap_custom_keyword.py` |
| e | A new event can reuse a deleted event's id (load-bearing for `requeue`) | Undocumented, untested | `probe_e_deleted_id_reuse.py` |
| f | IMAP CAPABILITY (UIDPLUS/MOVE/SPECIAL-USE), keyword persistence, hierarchy separator, `\All`, COPYUID — server- and account-specific, never assumed from provider identity | Server-dependent, untested | `probe_f_imap_keyword_and_uidplus.py` |
| — | Does `modifyLabels(id, old, None)` (`addLabelIds: [null]`) work as manage-agenda currently calls it | Unresolvable by reading code | not scripted (existing behavior, not a new probe target — flagging only) |

None of the probe scripts have been run. They require a test calendar (and, for probes d
and f, a test IMAP account/folder) that only you can safely provide.

## 5. IMAP marker design (addendum, corrected — see below)

**Correction applied**: the IMAP backend must be quasi-universal — it must work against a
bare IMAP4rev1 server with **zero Gmail-specific code** (no `X-GM-LABELS`, `X-GM-MSGID`,
`X-GM-RAW`, no assumed `OBJECTID`). Gmail specifics stay confined to the separate Gmail API
backend; Gmail reached over plain IMAP is treated exactly like any other IMAP4rev1 server —
nothing about it may be assumed. An earlier draft of this section proposed
`X-GM-LABELS`-over-IMAP as a per-provider special case; that proposal is withdrawn.

`processed_marker` config (shipped under this name, not `imap_processed_marker` as first
drafted here — it lives in the same per-account `source_details` dict as the pre-existing
`mark`/`folder`/`channel`/`from` keys, which are all unprefixed, so this one is too), one of:
- `keyword:<name>` — e.g. `keyword:$AgendaDone`. Generic IMAP keyword STORE, nothing
  provider-specific.
- `flag:seen` (or bare `flag`) — kept for `mark: seen` backward compatibility (see §6
  migration); `mark: seen` with no explicit `processed_marker` is still read as `flag_seen`
  automatically, unchanged.
- `folder:<path>` — a dedicated folder (created if absent), never Trash.

**Scope limitation, shipped as implemented**: `processed_marker` only takes effect for
accounts configured with `folder`/`channel`/`from` (the `_fetch_imap_matches` raw-SEARCH-
criteria scan path). The tag-based default scan (`setLabels`/`setChannel`/`getPosts`, used
when none of those are set) has no seam to add server-side exclusion (`UNKEYWORD`/
`UNDELETED`) to without modifying socialModules — and a marker there would leave processed
messages sitting in the scanned label forever, with every run re-fetching a set that grows
with the tool's whole history instead of its current activity, which is exactly what this
redesign exists to prevent. A `processed_marker` configured on such an account is refused
(treated as a config mistake) and logged, not silently accepted; accounts on that path keep
using `_delete_email` (label removal) exactly as before.

**Requeue's un-marking step, shipped**: `on_user_delete=requeue` (see reconcile_handled_events)
marks an entry `pending_requeue`; `process_email_cli` now attempts to un-mark that identity's
source message in the *current* account's folder on every run, unconditionally (not gated on
whether this run's scan found anything new). A miss is expected and harmless when the
identity belongs to a different account - it stays `pending_requeue` and is retried on that
account's next run (self-correcting; no cross-account tracking added to the ledger).
`flag_seen` mode needs no physical action here - reconcile already excludes a
`pending_requeue` identity from `still_handled`, and `flag_seen` exclusion is ledger-only, so
the message is already visible again on the very next scan.

`keyword` mode un-marks by a bounded `UID SEARCH HEADER Message-ID` in the source folder (no
locator needed, matching "Per-marker behavior" below - the message never moved). `folder` mode
now captures the COPYUID locator at move time (stored on the ledger entry via
`remember_handled_mail`) and consumes it at un-mark time: if the locator's folder and
`UIDVALIDITY` still match, it relocates the message straight back by UID; otherwise it falls
back to the same bounded Message-ID search, in the dedicated folder. Both paths treat a
hash-fallback identity (no real Message-ID existed - see `mail_identity()`) or an ambiguous
(zero- or multi-match) search the same way: left pending, logged, never guessed at. A formal
`source_lost` status is not introduced by this commit - an un-marking attempt that never
succeeds simply lets the entry expire via the existing no_event-style purge fallback
(`recorded_at` + the short margin), which is functionally equivalent to giving up without new
purge logic.

**Default marker per account**, chosen from probe (f)'s result for that specific account:
`keyword` if `PERMANENTFLAGS` advertises `\*` **and** a STORE/FETCH round trip confirms the
keyword actually persists; `folder` otherwise. This is per-account, not global — different
configured accounts (including two different Gmail-over-IMAP accounts with different server
configurations) can land on different defaults; probe (f) must be run against each account
actually used, never assumed from a provider name.

### Capabilities detection — centralized, once per connection, logged

A single `ImapCapabilities.detect(client)` call (see probe (f)) reads `CAPABILITY` once per
connection and records: `has_uidplus` (RFC 4315), `has_move` (RFC 6851), `has_special_use`
(RFC 6154). Every subsequent decision below is gated on this object, not on server identity —
the same account can gain or lose a capability across a server upgrade, and the code must
react to that, not to a hardcoded assumption. The detection result is logged once per
connection for diagnosability.

**Python's stdlib `imaplib` has no built-in support for MOVE (RFC 6851) or UIDPLUS/COPYUID
(RFC 4315).** Confirmed by reading `imaplib.py`: `'MOVE' in imaplib.Commands` is `True` (state
`SELECTED`), so `client.uid('MOVE', uid, folder)` is callable via the generic UID-command
dispatcher — but there is no dedicated `.move()` method, and the tagged response's response-
text (where a `[COPYUID uidvalidity src-uid dest-uid]` code would appear) is returned as a
**raw, unparsed string** in the `dat` list from `_command_complete`/`_simple_command`/`uid()`.
manage-agenda has to regex-parse `[COPYUID ...]` out of that string itself — no socialModules
change needed (same "already reachable via getClient()" pattern as every other capability
found in this investigation), but no library does the parsing for us either. Probe (f) tests
this on the real client and reports whether `MOVE` is accepted at all and whether a `COPYUID`
code is present in the response — gated on `has_move`/`has_uidplus`, never assumed.

### Safe deletion without UIDPLUS — critical rule

**Without UIDPLUS, the design NEVER issues a bare `EXPUNGE`.** A bare `EXPUNGE` purges every
message flagged `\Deleted` in the currently selected folder, including messages a human user
deleted through their own mail client and expects to remain merely flagged until *their*
client expunges them — manage-agenda has no way to distinguish "its own" `\Deleted` message
from the user's. Consequences by capability:
- **With UIDPLUS**: `UID EXPUNGE <uid>` (RFC 4315) is scoped to exactly the given UID(s) and
  is safe regardless of what else in the folder is flagged `\Deleted`. Used after a COPY (or
  as part of a MOVE, if the server implements MOVE via an internal UIDPLUS-safe expunge).
- **Without UIDPLUS**: leave the original message flagged `\Deleted` and exclude it from
  future scans via a `SEARCH ... NOT DELETED` criterion (or equivalently, `UNDELETED`) added
  to the scan query. No expunge of any kind is performed by manage-agenda on this path — actual
  purging is left entirely to the user's own mail client or server-side policy.

### Hierarchy separator and `\All` — read, never assumed

- **Hierarchy separator**: always read via `LIST "" ""`, never hardcoded (`/` vs `.` is
  server-configuration-dependent, not provider-dependent — assuming one is a latent bug on
  any server configured differently, including two Dovecot instances with different configs).
- **`\All` special-use attribute (RFC 6154)**: when `has_special_use` is true, `LIST "" <folder>`
  is checked for the `\All` attribute before scanning that folder; **a folder carrying `\All`
  is refused** (it aliases the entire mailbox — scanning it would mean seeing every message
  regardless of which real folder it lives in, breaking the per-folder exclusion logic
  entirely). When `has_special_use` is false, `\All` is treated as absent (safe default — there
  is no signal to detect it by, and false-negatives here are the safe failure mode).

### Per-marker behavior

- **keyword**: mark on success = `UID STORE +FLAGS`; scan exclusion = search criteria
  including `UNKEYWORD <name>`; requeue = `UID STORE -FLAGS`. Purely generic IMAP keyword
  STORE — identical code path regardless of provider, including Gmail-over-IMAP. **No locator
  needed in the ledger** - the message never moves, so there's nothing to lose track of.
- **folder**: mark on success = `UID MOVE` (if `has_move`) or `UID COPY` + safe deletion of
  the original per the rule above (if not) to the dedicated folder (created via `createFolder`
  if absent - confirmed to exist in §2). If the response carries a `COPYUID` code (requires
  `has_uidplus`), store `(uidvalidity, uid)` in the ledger entry as the locator. Requeue: if
  the locator is present **and** the folder's current `UIDVALIDITY` still matches the stored
  one, move/copy straight back using the stored uid - no search needed. If `UIDVALIDITY` has
  changed, or no locator was ever recorded (server lacked UIDPLUS), fall back to `UID SEARCH
  HEADER Message-ID "<...>"` scoped to that one folder and bounded by `SINCE` (never an
  unbounded search); compare the found message's `Message-ID` header for an exact match before
  acting on it. **Zero or multiple matches both resolve to `source_lost`, journaled** - never
  an arbitrary pick among several candidates.
- **flag:\Seen**: unchanged from today's `mark: seen` behavior - the message is never moved
  or otherwise touched; exclusion is by the `\Seen` flag already read via `SEARCH`.

**Ordering invariant marking depends on, as shipped**: `_fetch_imap_matches` always hands
messages back highest-sequence-number-first, and that order is preserved unchanged all the
way to the per-message marking call. This is load-bearing: an expunge (implicit in `MOVE`, or
explicit via `UID EXPUNGE`) only renumbers messages with a *higher* sequence number than the
one just removed, never a lower one - so processing highest-first guarantees that marking one
message can never invalidate the still-to-be-processed sequence number of another. Nothing in
the marking code itself enforces this; it is a property of the scan order that must not be
changed (e.g. by sorting ascending, or re-fetching mid-scan) without re-deriving this
argument.

### Test coverage (expanded capability matrix)

Beyond the per-marker unit tests already planned, a capability-matrix test suite exercises
every `(has_uidplus, has_move, has_special_use)` combination against a mocked `imaplib`
client, asserting in particular: no `EXPUNGE`/`UID EXPUNGE` call is ever made when
`has_uidplus` is false (the never-bare-EXPUNGE rule), the hierarchy separator is always taken
from a `LIST` response rather than a literal, and a folder whose `LIST` response carries `\All`
is never selected for scanning when `has_special_use` is true.

Probe (f) must be run against **at least** a plain Dovecot server and a Gmail account reached
over plain IMAP (not the Gmail API), without assuming anything about either beyond what
`CAPABILITY`/`LIST` actually report for that specific connection.

## 6. Migration — no reprocessing of already-handled messages

Accounts currently configured with `mark: seen` keep `flag:\Seen` as their marker unless the
operator explicitly switches them to `keyword`/`folder`. On an explicit switch to `keyword`:
before the *first* scan under the new criteria, the migration step applies the keyword to
every message still referenced in the ledger and still present in the source folder (a
message the old mechanism already relied on staying put). This must complete before the new
exclusion criteria is used, or those messages would be picked up as new by the newly-added
`UNKEYWORD` search. A dedicated test asserts no already-handled message is reprocessed
immediately after this migration step runs.

**Status: documented, not yet implemented.** This is a mailbox-side migration (for an
operator explicitly changing `processed_marker`), distinct from the Calendar-side migration
in §7, and remains future work - nothing in the shipped code applies a keyword retroactively
on a marker-mode switch yet.

## 7. Migration — extendedProperties and event_end on pre-existing Calendar events, shipped

`migrate_legacy_ledger_entries()` (called from `process_email_cli`, between reconcile and
purge) patches `extendedProperties.private` onto Calendar events created before deterministic
ids/origin stamping existed, and backfills each ledger ref's `event_end` from the same fetch.
Per the original migration requirements: idempotent, never changes an event's own id, and
never a full-ledger sweep every run.

- **Idempotent, per-ref**: each ref gains `"migrated": true` once resolved (success or
  confirmed-gone); a ref left un-migrated after an ambiguous API error is retried on a future
  run, the same conservative pattern used throughout this codebase (see
  `_get_event_if_present`).
- **Never changes an event's own id**: only `events.patch()` is used, never delete+recreate;
  the patch body never includes an `id` field.
- **Scoped to the sync bootstrap window** (`_is_within_bootstrap_window`, the same 90-day
  window `reconcile_handled_events`'s own bootstrap diff trusts): an older, never-migrated ref
  is left alone - it is either already purged or close to it regardless of whether it ever
  gets the origin stamp, so spending an API call on it buys nothing for the "state bounded by
  current activity" goal.
- **Existing `extendedProperties.private` keys are preserved**: the patch body is built by
  reading the event's current `private` map (via the same `events.get()` used to check it)
  and adding the new keys to a copy of it, rather than sending only the new keys - whether
  Calendar's PATCH merges `extendedProperties.private` at the individual-key level or replaces
  the whole map is undocumented and unverified (no probe covers it), so this doesn't rely on
  either assumption.
- **`event_end` backfill source, as actually implemented**: the live event's own `end` field,
  read from the same `events.get()` call already needed to check/patch it - **not** a
  `_times.json` log-file fallback as originally specified. Log files are keyed by the source's
  own per-run `post_id` (see `process_email_cli`'s `metadata_extractor`), which is never
  persisted in the ledger (only `mail_identity()` is, a different value) - there is no
  reliable way to find the right log file from a ledger entry alone, so that fallback was not
  built. A gone event (404/410) or one missing an `end` field simply leaves `event_end` absent
  on the ref, which `purge_expired_ledger_entries()` already handles safely via the shorter
  `no_event`-style margin from `recorded_at` - never a crash or incorrect data, only a
  possibly shorter retention than a still-live event would have earned.
- **Generation**: already correctly defaulted to 0 for any entry with no `generation` key (see
  `_load_state`, landed in an earlier commit) - no separate migration logic needed for it.
- **Messages already moved to Trash under the old `_delete_email` behavior**: out of scope for
  this migration - it only touches Calendar events and the local ledger, never mailbox state.
  A message already in Trash under the pre-redesign behavior is unaffected either way; nothing
  attempts to recover it, and the ledger continues to correctly treat it as handled.

## 8. Safety hardening after review

Three gaps found in review of §§3-7, closed before any real data is touched:

**No entry may be exempt from purging forever.** `purge_expired_ledger_entries()`'s
`_entry_purge_after()` returned `None` (never purge) for an entry with no `event_end`
anywhere *and* no `recorded_at` - only possible for a pre-`recorded_at` legacy entry whose
events are also gone/inaccessible/outside the migration bootstrap window, so migration never
backfills `event_end` for it either. Fixed: such an entry now gets exactly one grace pass -
`recorded_at` is stamped to "now" (never overwriting a real one) on the call that finds no
signal, so it purges via the normal `no_event_margin_days` on a later call. Tested for both
the legacy `{"ids": [...]}` format and a "created" entry whose ref simply predates
`event_end`.

**§6 (mailbox-side marker-switch migration) is documented but not implemented - closed with a
fail-closed guard, not the migration itself.** Without §6, an account switching from
`mark: seen` (`flag_seen`, ledger-only exclusion, message never physically moves) to
`keyword`/`folder` (server-side SEARCH exclusion) risks a genuine duplicate event: a ledger
entry that ages past its purge margin makes its still-unmoved, flag-only-marked message
visible to a fresh scan again, and if the LLM's extraction isn't perfectly deterministic
across runs (a different event count/order shifts `event_index`), the recomputed
deterministic id can differ from the one already on Calendar - a real duplicate, not a caught
collision. `check_marker_mode_transition()` (a small per-*account* history file, bounded by
the number of configured accounts, not mail volume) refuses the scan and prints an explicit
message on exactly that transition, until §6 is implemented or the config is reverted. Every
other transition (unconfigured → anything, `keyword` ↔ `folder`) is allowed, since neither
shares `flag_seen`'s "message never moves" property.

**Important limitation, stated plainly**: the guard is forward-only. It protects a
`mark: seen` → `keyword`/`folder` switch made *after* this version has run at least once for
that account (the first run for any account simply records its current mode as the baseline).
A switch already made *before* upgrading to this version is recorded as if the new mode had
always been in effect and is never caught - the ledger has no per-entry record of which
marker was actually used historically, by design, so there is nothing to detect that switch
from after the fact.

**`--dry-run`**, covering `reconcile_handled_events()`, `migrate_legacy_ledger_entries()`, and
`purge_expired_ledger_entries()` - all three of `process_email_cli`'s ledger-writing calls, not
only the two named in the request. Purging was added to the scope during review: it writes the
same ledger file in the same three-call sequence, and skipping it would let a "touch nothing"
flag permanently delete real ledger entries. The rest of `process_email_cli` (scanning/
extraction/publishing) deliberately still runs normally under it, exactly as requested. All
three still perform their read-only Calendar calls (needed for an accurate preview) but skip
every write - no `_save_state` anywhere, `migrate_one_legacy_event()` gained a distinct
`"would_migrate"` status so a previewed ref is never marked `"migrated"` (a later real run
still processes it), and purge's grace-pass `recorded_at` stamp (see above) is skipped too.
Wired through `Args.dry_run` and `add --dry-run`. Before a real (non-dry-run) migration pass,
the ledger file is copied to `<path>.bak` (overwritten each real call) unconditionally, not
only when something will change - `check_marker_mode_transition()`'s own small history file is
not part of this backup or dry-run gating (see its docstring: it only ever records which
marker mode is configured, never mail/calendar data).

**Also confirmed** (already correct, strengthened rather than fixed): `migrate_one_legacy_event`
reads the event's existing `extendedProperties.private` map into a copy *before* adding the
new stamped keys, so third-party properties (`ai_model_used`, etc.) are never overwritten -
whether Calendar's PATCH merges or replaces that map server-side is irrelevant either way,
since the complete desired end state is always what's sent.

**Separately discovered while adding the per-account marker-history file**: `TestProcessEmailCli`
and related tests had been writing into the real `~/.local/share/manage-agenda/` directory for
as long as they exercised `process_email_cli` with no explicit `path=` override - confirmed by
finding a real Outlook Message-ID in a real `handled_mail_ids.json` after a local test run. Not
a design gap in this redesign, but real user data with test-injected entries mixed in with no
way to tell them apart after the fact. Fixed going forward with an autouse `isolated_data_dir`
fixture in `tests/conftest.py` (redirects `manage_agenda.config.DATA_DIR` to a per-test
`tmp_path`); the pre-existing pollution in the real file was not touched or "repaired" -
reconstructing which entries are real would mean guessing at the user's data.

## 9. Second review round: correctness fix, structural guarantees, deeper test isolation

Seven items from a second pre-flight review, all closed before any probe or migration is run
against real data.

**A confirmed-gone event (404/410) is no longer treated as a user deletion.**
`_confirm_missing_ids()` (extraction.py) previously returned one flat `confirmed` set,
conflating "Calendar reports an explicit `status: cancelled` tombstone" with "Calendar has no
record of this id at all" - a 404 is NOT proof of a user deletion; it is equally consistent
with the event never having been created (a past bug, ledger corruption, a wrong/stale
event_id). It now returns `(cancelled_ids, unknown_ids)`, threaded through
`sync_calendar_changes()` (same return shape) up to `reconcile_handled_events()`. An identity
whose only remaining tracked refs are all "unknown" is journaled with a new status
`"unknown_event"` - excluded from future scans, but pre-empting `on_user_delete` entirely
(neither `ignore` nor `requeue` fires) and never touching any mailbox. A mix of cancelled and
unknown refs on the same identity resolves as `unknown_event` too, rather than partially
applying `on_user_delete` to the cancelled ones - a mix is itself a sign something is off, not
something to partially resolve as a normal deletion. A syncToken delta never produces an
unknown id by itself (only the bootstrap path's targeted confirmation can), which is pinned by
its own test.

**The purge grace-pass already waited the full margin, not just one call - verified, not
"fixed".** Re-examined `purge_expired_ledger_entries()`'s grace-pass logic (§8): an entry
stamped with `recorded_at` on one call is only purged once `recorded_at + no_event_margin_days`
has actually elapsed, confirmed by a new test that calls the function twice at the *same*
instant and asserts the entry survives both times. The docstring wording ("exactly one grace
pass") was genuinely ambiguous and easy to misread as "immune for one call regardless of
elapsed time", so it was reworded, but the underlying behavior needed no code change.

**`reconcile → migrate → purge` ordering is now enforced structurally.** A new
`reconcile_migrate_and_purge()` performs all three, in that fixed order, in one call, forwarding
`dry_run` to each - `process_email_cli` now calls this single function instead of three
separate ones in sequence, so the ordering invariant (documented at length in §7/§8 for why it
matters) can no longer regress by a future call site getting the order wrong.

**`--dry-run` was renamed to `--dry-run-ledger`.** Reviewed as misleading: it only ever covered
`reconcile_handled_events()`/`migrate_legacy_ledger_entries()`/`purge_expired_ledger_entries()`
(the ledger-writing calls), never Calendar publish, mailbox marking, or
`remember_handled_mail()` - scanning/extraction/publishing/marking all still run normally under
it. Building a true global dry-run (gating publish and every mailbox-marking call too) was
the alternative considered and rejected as the more invasive, higher-risk option for what was
asked to be the simpler fix; the rename is a breaking change (`manage-agenda add --dry-run` now
fails with "no such option" rather than silently doing something narrower than its name
implied - the safe failure direction, and deliberately not aliased).

**Structural test isolation, several gaps closed.** `tests/conftest.py` gained:
- `isolated_msg_txt_dir`: patches `manage_agenda.base.DEFAULT_DATA_DIR` directly. This was the
  real, previously-unpatched gap behind `~/Documents/txt/log/` continuing to fill with
  test-run artifacts (confirmed in practice - directory names literally containing
  `<MagicMock name='mock.model_name' ...>` were found there) even after `isolated_data_dir`
  (§8) existed, since `DEFAULT_DATA_DIR` is a separate module-level constant
  (`= config.MSG_TXT_DIR` at import time), never re-read.
- `isolated_config_dir`: patches `manage_agenda.config.CONFIG_DIR` and (separately, since it's
  a distinct name binding from `from manage_agenda.config import CONFIG_DIR`)
  `manage_agenda.user_config.CONFIG_DIR` - the OAuth-credentials/`config.yaml` directory. No
  pollution was found here in practice, but the risk shape is identical to
  `DEFAULT_DATA_DIR`'s, so it was closed proactively.
- `isolated_home`: redirects `HOME`/`XDG_DATA_HOME`/`XDG_CONFIG_HOME` env vars, as explicit
  defense-in-depth for anything that resolves a real-user path lazily at call time (e.g.
  socialModules' own `~/.mySocial/config` lookup). Does **not** by itself fix the three
  already-baked constants above - those are computed once at import, before any per-test
  monkeypatch can run.
- `guard_real_data_directories_untouched`: snapshots `(mtime_ns, size)` for every file under
  the real (unredirected, computed once at collection time) data/txt directories before and
  after each test, failing loudly on any change - a safety net behind the isolation fixtures
  for any code path they miss. mtime alone was tried first and found to miss a same-tick,
  same-size-window content rewrite on this filesystem; size was added to the snapshot to catch
  it (verified empirically, not just in theory).
- `guard_no_real_network_connections`: blocks any non-loopback `socket.connect()` during a
  test, so a test that forgot to mock an API client fails immediately instead of reaching (or
  hanging trying to reach) a real Calendar/IMAP/Gmail/LLM endpoint. Loopback stays allowed.

**Pollution audit.** Direct inspection of the real directories (not a script - read-only
`stat`/`find`), reported and left untouched:
- `~/.local/share/manage-agenda/handled_mail_ids.json` - confirmed polluted (§8), last written
  before `isolated_data_dir` existed.
- `~/.local/share/manage-agenda/event_keys.json` - present, but **no reference to it exists
  anywhere in the current codebase** (`grep` found zero matches in `manage_agenda/` or
  `tests/`) - an artifact of an older version of the tool, not of this redesign's work, and
  inert regardless.
- `~/Documents/txt/log/` - confirmed polluted, and **continued to be polluted after**
  `isolated_data_dir` (§8) landed, since that fixture never covered `DEFAULT_DATA_DIR` (see
  above) - only closed by `isolated_msg_txt_dir` in this round. Directory names in there
  literally contain unconfigured mocks' reprs (e.g.
  `log/<MagicMock name='mock.model_name' id='...'>/`), an unambiguous test-pollution signature.
- `~/.config/manage-agenda/` (OAuth credentials / `config.yaml`) - empty, no evidence of
  pollution, but see `isolated_config_dir` above for why it was still closed proactively.
- `~/.mySocial/` (socialModules' own real account config/credentials) - no files newer than
  the repository itself; no evidence any test read or wrote real account configuration.

**Read-only diagnostic script**, `scripts/diagnose_ledger.py`: classifies every tracked ledger
ref via `events.get()` (`active`/`cancelled`/`not_found`/`error`), and cross-references every
ledger identity/calendar_id/event_id against string literals collected (via `ast`, not a naive
text search) from the test suite, reporting a `high`/`medium`/`low` confidence per match -
`low` explicitly for values that are also legitimate real-world identifiers (`primary`,
`INBOX`), so a match there is never read as a reliable pollution signal on its own. Makes only
`events.get()` calls (no insert/patch/delete) and writes nothing but its own optional report
file. Not run by the assistant.
