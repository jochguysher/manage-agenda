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
purge - since §12, only once `migrate-ledger` has been run for the calendar account, which
also calls it directly) patches `extendedProperties.private` onto Calendar events created before deterministic
ids/origin stamping existed, and backfills each ledger ref's `event_end` from the same fetch.
Per the original migration requirements: idempotent, never changes an event's own id, and
never a full-ledger sweep every run.

- **Idempotent, per-ref**: each ref gains `"migrated": true` once resolved (success or
  confirmed-gone); a ref left un-migrated after an ambiguous API error is retried on a future
  run, the same conservative pattern used throughout this codebase (see
  `_get_event_if_present`).
- **Never changes an event's own id**: only `events.patch()` is used, never delete+recreate;
  the patch body never includes an `id` field.
- **Not bounded by the sync bootstrap window** (since §12's last revision; it used to skip any
  ref whose `recorded_at` was older than the 90 days `_is_within_bootstrap_window` covers).
  Every un-migrated ref of the account is attempted, whatever its age. The window bounds
  reconcile's *recurring* cost; migration is a one-off over a finite ledger, and its
  `event_end` backfill is exactly what an old ref needs: a message recorded 200 days ago for an
  event still to come would otherwise purge on the short `recorded_at` fallback while its
  event is live. After the first real pass, the recurring calls from `add`/`reconcile` cost
  one `events.get()` per ref left for retry; skipped and migrated refs make no API call.
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
events are also gone or inaccessible, so migration never backfills `event_end` for it either. Fixed: such an entry now gets exactly one grace pass -
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

## 10. Baked-at-import constants: the root cause of the real-data pollution

Shipped in `e55e683`. Several code comments point here: `config.py`, `user_config.py`,
`events.py`, `tests/conftest.py` and `tests/test_conftest_isolation.py`.

**The bug class.** `DATA_DIR`, `CONFIG_DIR`, `Config.MSG_TXT_DIR` and `Config.LOG_FILE` were
module-level values computed once, when their module was first imported. Other modules then
copied them into their own module-level names too: `base.DEFAULT_DATA_DIR =
config.MSG_TXT_DIR`, and `user_config` imported the `CONFIG_DIR` value. A later change to
`HOME`/`XDG_DATA_HOME` had no effect on code already holding the baked value. That change
could be a test's `monkeypatch.setenv()` (always "later": pytest collection imports every
module before any test body runs), or a real environment change. This is how real user data
ended up mixed with test-injected entries - the Outlook Message-ID in the real
`handled_mail_ids.json` (§8), and the `log/<MagicMock ...>/` directories under
`~/Documents/txt/log/` (§9).

**Why §8/§9 didn't close it.** Each round added an attribute-patching fixture for one more
baked name (`isolated_data_dir`, `isolated_msg_txt_dir`, `isolated_config_dir`, ...). Each
fix was correct for its own name, but the pattern producing new ones stayed. The next baked
constant, or the next module importing the value instead of the module, would leak again,
silently. §9's descriptions of those fixtures are superseded by what follows.

**The fix: resolve at call time.** The constants are replaced by `data_dir()`,
`config_dir()`, `msg_txt_dir()` and `log_file_path()` (`config.py`). Each reads its
environment variable on every call, and every caller calls the function instead of
importing a value. `data_dir()` and `config_dir()` are pure path resolvers, with no
`mkdir()` side effect: every writer already creates its own parent directory, and a
read-only caller (`scripts/diagnose_ledger.py`, whose contract is zero writes) must not
create anything just by resolving a path. `output_dir()` (§11) follows the same rule.

**Test isolation, rebuilt on that.** `tests/conftest.py`'s attribute-patching fixtures are
collapsed into one autouse `isolated_paths` fixture. It redirects `HOME`, `XDG_DATA_HOME`,
`XDG_CONFIG_HOME`, `MSG_TXT_DIR` and `LOG_FILE` through environment variables, which is now
sufficient because nothing is baked any more. `MSG_TXT_DIR` and `LOG_FILE` are listed
explicitly: the repo's own `.env` pins both at import time via `os.environ.setdefault()`, so
they don't follow `HOME`. `OUTPUT_DIR` was added later, for the same reason (§11). The
real-directory guard now also watches `~/.config/manage-agenda` and `~/.mySocial`
(socialModules' own configuration). It also fails if a test creates or removes a watched
directory outright, not only if it writes a file inside one: a `mkdir()` on path resolution
would otherwise have gone unnoticed. `tests/test_conftest_isolation.py` is the direct
regression test: it proves a redirect set *after* `manage_agenda.config` was imported still
takes effect, which is exactly the scenario the old constants broke.

**The same pattern, for a timezone.** `events.py`'s default-timezone constant was a sixth
instance of it. Fixed separately; see §11.

## 11. Read-side isolation: `Config` values and the default timezone; `log/` and `-o file`

Shipped in `470869a` and `d9544dc`. The `log/` part was refined afterwards in `e99a4b0`,
`841663c`, `db7c13c` and `0cbf636`; this section describes the current state.

**The default timezone.** `events.py` localized naive event datetimes with a module-level
`DEFAULT_NAIVE_TIMEZONE`, computed once from `Config.DEFAULT_TIMEZONE` at import time - the
§10 pattern, for a timezone instead of a path. Throughout the test session it silently read
the real `.env`'s `DEFAULT_TIMEZONE=America/Toronto` (UTC-5 in January) instead of the
Europe/Berlin (UTC+1) the tests assumed. Three `test_events.py` failures
(`test_adjust_event_times_*`) came from that 6-hour gap. They were reported as "pre-existing
and unrelated" across several review rounds before the cause was found. They were never
unrelated: an event created from a naive datetime goes through this same localization
before being sent to Calendar, and migration's `event_end`, which drives ledger purge timing
(§7), is read back from that live event. A wrong default timezone eventually skews purge
timing by the same offset. Fixed in `470869a`: `_default_naive_timezone()` is resolved on
every call.

**`Config`'s read-only values.** §10's isolation covered *writes* to real paths, not *reads*
of real configuration. `Config.DEFAULT_TIMEZONE`, `LOG_LEVEL`, `DEFAULT_EMAIL_TAG`,
`ON_USER_DELETE`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `OLLAMA_HOST` and
`OLLAMA_DEFAULT_MODEL` are plain class attributes, read via `os.getenv()` once, when the
class body executes. They were deliberately not converted to call-time functions, since
nothing needs them to change mid-process. So they are baked before any per-test fixture
runs, at the first import of `manage_agenda.config`: a per-test `monkeypatch.setenv()` is
always too late for them. `tests/conftest.py` now sets known values for all of them directly
in `os.environ`, at module level, before any test module (or `manage_agenda.config`) is
imported. It sets them unconditionally, not with `setdefault`, so a real exported shell value
is overridden too, not just `.env`'s. The two API keys are removed rather than set to `""`.
The three per-test timezone patches from `470869a` became redundant and were removed.
`test_config_does_not_leak_the_real_env_files_values` fails if `Config.DEFAULT_TIMEZONE`
ever reflects the real `.env` again.

**Debug artifacts under `MSG_TXT_DIR/log/` are opt-in** (`e99a4b0`). `write_file()` writes
raw LLM prompts and responses and the extracted event JSON: plaintext message content, one
write per processed message, growing without bound. It now writes nothing, and creates no
directory, unless the caller passes `enabled=True`. Every call site passes
`args.debug_log_extractions` (`add --debug-log-extractions`, off by default), so a caller
that forgets fails closed. When enabled, files are 0600 and the `log/` tree 0700, never
`MSG_TXT_DIR` itself, which also holds the user's `.txt` sources.
`purge_expired_log_files()` runs once per `add` while the flag is on, and deletes files older
than `--debug-log-retention-days` (default 7).

**`-o file` output moved out of `log/`** (`d9544dc`). `-o file` mode's actual result used to
be written as `log/{model}/{post}_{idx}_times.json`. That is the directory the purge sweeps,
under a name a debug artifact also used, so the purge needed a per-filename exception. It now
goes to `config.output_dir()`: `$OUTPUT_DIR`, defaulting to `MSG_TXT_DIR/output`, resolved at
call time like §10's functions. `tests/conftest.py` pins `OUTPUT_DIR` per test, like
`MSG_TXT_DIR` (`0cbf636`). `output_dir()` is never purged automatically, and grows by one
file per extracted event on every `-o file` run, which is the default for `llm evaluate`.
Files there are written 0600. Directories `write_file()` creates there are 0700. An existing
directory's permissions are never changed, since `OUTPUT_DIR` may point at a directory the
user already uses. A looser one only gets a warning in the log (`db7c13c`).

**Files that predate the purge are protected permanently** (`841663c`). Output written under
`log/` before the move may still be there. `d9544dc` first gave such files a one-time grace
pass: the first purge only stamped a marker. That was replaced by a permanent boundary. The
marker (`log/.purge_enabled_since`) records the moment of the first activation and is never
rewritten, and a file is purged only if its mtime is strictly after that moment *and* past
retention. The marker is excluded by name, whatever its mtime. An unreadable marker purges
nothing, and the warning says how to fix it: deleting the marker re-arms the protection, and
every file present at that moment becomes protected. An end-to-end test runs `llm evaluate
-o file` and checks that nothing is created under `log/`.

## 12. Explicit ledger migration: `migrate-ledger`, and the operational sequence

**Why.** `reconcile_migrate_and_purge()` used to run on every email `add`. The local install is
editable (`pip install -e .`), so a scheduled job calling `.venv/bin/manage-agenda` runs the
working tree as soon as it changes: the first real migration pass, and the first
reconcile/purge of the real ledger, could happen from a cron run, before any backup,
diagnostic or `--dry-run-ledger` preview. Migration is now an explicit operator step, and `add`
refuses to do any ledger maintenance until it has been done.

**`manage-agenda migrate-ledger [-i] [--dry-run-ledger]`** (`sources.migrate_ledger_cli`):
- Connects to one calendar account:
  - without `-i`: the saved `calendar_account` (the one `add` uses); with none saved, the
    only configured `gcalendar` account when there is exactly one; with several configured,
    nothing is guessed: one message naming the accounts asks for `-i` (and nothing else is
    printed - `select_calendar_account` raises `CalendarAccountChoiceRequired`, so the
    command doesn't add its generic "no calendar account" line), and the command stops
    before connecting any account (`readConfigSrc` can trigger OAuth) - no Calendar call,
    no ledger write, no marker. Never "the first configured account": a migration marker
    must not land on an account picked by configuration order;
  - with `-i`: **always** a choice among the configured `gcalendar` accounts, even when one is
    saved - that is how another account's refs are migrated or reconciled;
  - the saved account is **never** changed, with or without `-i`
    (`connections.select_calendar_account`, unlike `prepare_calendar()`, writes no config and
    picks no destination calendar - ledger maintenance works from the refs in the ledger).
    `add` keeps `prepare_calendar()` and its behaviour: its `-i` asks only when no account is
    saved (or with `--reconfigure`), and it saves what was picked.
- Runs `migrate_legacy_ledger_entries()` only: no reconcile, no purge. Only this calendar
  account's refs are touched (see "Only this calendar account's refs" below). Everything
  else is counted as "left alone", never marked migrated, and migrated later by running the
  command for its own account (`-i` to pick it). Every un-migrated ref of the account is
  attempted, however old its `recorded_at` (§7): the 90-day window only bounds reconcile.
- Reads the account's calendar list first. If that fails, nothing runs and nothing is
  stamped. Without it no ref can be told apart as this account's, and stamping a pass that
  migrated nothing would open the gate with no migration ever done.
- `--dry-run-ledger`: `events.get()` only. No `events.patch()`, no ledger write, no `.bak`,
  and the account is **not** marked as migrated. Every outcome is logged to `LOG_FILE`.
- Real pass: copies the ledger to `handled_mail_ids.json.bak`, patches, then stamps the
  account's marker, even when nothing needed migrating (an empty ledger must be able to
  unblock `add`). Refs left for retry after an ambiguous API error don't block the stamp:
  migrate still runs inside every automatic `add` afterwards, always before purge, and
  retries them there.
- No calendar account available → nothing runs, nothing is stamped.

**Exit codes** (`sources.EXIT_*`; `migrate-ledger`, `reconcile` and
`scripts/diagnose_ledger.py` share them, so a script can tell each stop apart). The two
commands' functions return the code and the click wrapper exits with it; the diagnostic
calls `sys.exit` with the same values. 0: the pass ran (dry or real). 1 and 2 are left to
what already produces them - an uncaught Python error, and click's usage error (unknown
option) - so they are never used for a deliberate stop.

| code | constant | when |
|---|---|---|
| 3 | `EXIT_NO_CALENDAR_ACCOUNT` | no account could be connected: none configured, not authorized, no usable account key |
| 4 | `EXIT_CALENDAR_ACCOUNT_CHOICE_REQUIRED` | several accounts configured, none saved, no `-i` - nothing connected |
| 5 | `EXIT_LEDGER_MIGRATION_REQUIRED` | `reconcile` only: no `migrate-ledger` marker for this account - no Calendar call |
| 6 | `EXIT_CALENDAR_LIST_UNREADABLE` | `migrate-ledger` and the diagnostic: this account's calendar list could not be read - nothing migrated, nothing stamped |

**The marker is per calendar account**, in `data_dir()/ledger_migration.json`
(`{"accounts": {key: first-run timestamp}}`, the same shape as `imap_marker_history.json`).
The key is the calendar account's socialModules rule key (`api.src`, joined with `|` so the
tuple from the wizard and the list read back from `config.yaml` give the same key). It is not
keyed per *mail* account: the ledger is one file shared by every mail source, and what
migration actually does - patching events through one account's Calendar client - is scoped
to the calendar account. A marker for one calendar account never opens the gate for
another. An unreadable marker file counts as "not migrated" (fail closed).

**Only this calendar account's refs.** `CalendarScope.owner_of()` decides, without any API
call, before anything is looked up. The same rule applies to migrate, reconcile and
`scripts/diagnose_ledger.py`:
1. A ref recorded with `calendar_account` belongs to that account only. Every new ref records
   it (`_extract_event_refs`, from `add`'s calendar connection).
2. `primary` is relative to the account. A legacy `primary` ref, with no `calendar_account`,
   belongs to the current account only when it is the **only** configured gcalendar account.
   In that case migrate also *attaches* it: it writes `calendar_account` on the ref (real
   pass only, in `events` and `cancelled_events`), so it stays attributed if a second account
   is configured later. With several accounts configured, nothing is guessed: the ref is left
   alone and logged.
3. Any other calendar id must be on this account's calendar list (all access roles, hidden
   calendars included). Migrate checks this. Reconcile doesn't need to: listing a calendar
   this account can't see fails, and `sync_calendar_changes()` already treats that as
   "nothing to report".

Skipping a non-owned ref *before* `events.get()` is what makes a 404 mean "this event is not
found" rather than "this calendar is not visible from here". Calendar answers `notFound` for
both. So `gone` (and its `"migrated": true`) only ever applies to an event of this account.
An inaccessible calendar is logged, left un-migrated, and retried.

Reconcile needed the filter as much as migrate does, and there the failure is destructive.
Another account's `primary` ref would be looked up in this account's primary calendar, come
back 404, and be journaled `unknown_event` - wiping a live event from the ledger. An entry
whose refs all belong to other accounts now stays handled and untouched. Purge is not
filtered: it is age-only by design (§8 forbids permanent exemptions).

**The price of not guessing.** While several calendar accounts are configured, a legacy
`primary` ref is never migrated and never reconciled: a deletion on Calendar is never
noticed for it, and `on_user_delete` never applies. The entry stays handled, so its message
is not reprocessed, and it ages out through purge like any other entry. An operator who knows
the owner can attach such a ref by hand, by adding `"calendar_account": "<key>"` to it.

**`add` (`process_email_cli`)**:
- Marker present for the current calendar account → `reconcile → migrate → purge`, exactly as
  in §9, restricted to this account's refs as above, then the requeue un-marking.
- Otherwise → the whole trio is skipped (none of the three writes the ledger, and reconcile
  doesn't even make its read-only Calendar sync call). `handled` falls back to every identity
  on record (`load_handled_mail_ids()`, read-only), so already-handled messages are still
  skipped - an empty `handled` would rescan the whole mailbox and recreate events as
  duplicates. A warning naming the account and both commands is printed and logged.
- No calendar connection at all (`-o file`, and `llm evaluate --type email`, whose default
  output is `file`) → the trio is skipped too, logged at info level. This also stops those
  runs from purging the ledger, which they previously did with no Calendar connection.
- The requeue un-marking of `pending_requeue` entries is gated too. A successful un-mark
  removes the entry from the ledger (`forget_handled_mail`), so it is ledger maintenance like
  reconcile and purge.
- Not gated, the same scope boundary as `--dry-run-ledger`: recording newly processed
  messages (`remember_handled_mail`), Calendar publishing, and IMAP marking.

**`manage-agenda reconcile [-i] [--dry-run-ledger]`** (`sources.reconcile_ledger_cli`): the
ledger side of `add`, and nothing else. `add --dry-run-ledger` is not a safe preview: it keeps
the ledger untouched, but still scans, extracts, publishes and marks new messages (§9).
- Same account selection as `migrate-ledger` (by default the saved account `add` uses, else
  the only configured one; with several configured and none saved it stops and asks for
  `-i`, connecting nothing; `-i` always offers the choice; the saved account is never
  changed). Same gate as `add`:
  without the account's migration marker it prints the `migrate-ledger` instructions and
  makes no Calendar call at all. No calendar account → nothing runs.
- Runs `reconcile_migrate_and_purge()`, exactly as `add` does: Calendar sync + reconcile,
  migrate, purge, restricted to this account's refs. Migrate is included on purpose, even
  though it is a no-op on a fully migrated ledger. A ref `migrate-ledger` left for retry has
  no `event_end` yet; purging it before migrate retries it would drop its entry on the short
  `recorded_at` fallback. `reconcile` is no less careful than `add`.
- Never opens a mail account: no scan, no extraction, no LLM, no Calendar publish, no mailbox
  marking, no `remember_handled_mail`. The requeue un-marking is a mailbox action, so it is
  not run either: an entry this command moves to `pending_requeue` is un-marked by the next
  `add`.
- `--dry-run-ledger`: the same read-only Calendar calls (listing, targeted `events.get()`),
  every would-be change logged with a `DRY RUN` prefix. Nothing is written: no ledger, no
  `.bak`, no sync token.
- A real pass writes what `add` would: the ledger, its `.bak` (migrate), the sync tokens, and
  the `extendedProperties` patch of any ref migrate retries.

**Cancelled events are never patched.** `migrate-ledger` runs without reconcile first, so a
ref whose event was deleted on Calendar but is still returned by `events.get()` (status
`cancelled`) can reach `migrate_one_legacy_event()`. It now returns a new `"cancelled"`
status without calling `patch()` - whether a PATCH on a cancelled event can bring it back is
unverified (probe (b) territory), and stamping one buys nothing. The ref is left un-migrated,
and the first automatic `add` afterwards resolves it through reconcile and `on_user_delete`.
Its `event_end` is still backfilled from the same `get()` (outside dry run): once reconcile
moves the ref to `cancelled_events`, that end date is what earns the entry the
event_end-based purge margin. Without it, the entry would fall back to `recorded_at` + 7 days
- already past for a legacy ref - and be purged, along with `restore`'s record of the
deleted event, almost at once.

**Operational sequence** (nothing here is run by the assistant):
1. Suspend every scheduled job that runs manage-agenda (`crontab -l`,
   `systemctl --user list-timers --all`, `which -a manage-agenda`). With the editable install,
   they run the working tree, not a frozen release.
2. Back up `~/.local/share/manage-agenda`, `~/.config/manage-agenda` and `MSG_TXT_DIR/log`.
3. `scripts/diagnose_ledger.py` (the same account rule as the two commands, through
   `select_calendar_account`: the saved calendar account by default, else the only
   configured one, a stop asking for `-i` with several; `-i` always offers the choice and,
   like everything this script does, changes nothing; same exit codes), then
   clean up the ledger by hand. It reports `calendar_inaccessible` for refs that aren't this
   account's, without querying them. Those are **not** `not_found` and not a cleanup signal:
   rerun with `-i` for the other account. A real entry of another account never shows up as
   `not_found`.
4. Probes on a test calendar and test folders.
5. `manage-agenda migrate-ledger --dry-run-ledger`, then read `LOG_FILE`:
   - `DRY RUN migrate: would patch ...` - will be patched;
   - `... is cancelled - not patched` - left for reconcile;
   - `... is gone` - 404/410, nothing to patch, marked as done;
   - `could not fetch` / `could not patch` - left for a retry;
   - `... skipped - <reason>. Not marked migrated` - another account's ref, a calendar this
     account can't see, or a legacy `primary` ref whose owner is unknown;
   - `legacy ref attached to <account>` - a `primary` ref attributed to the only configured
     account.
6. `manage-agenda migrate-ledger`: `.bak` written, events patched, calendar account marked as
   migrated. With several calendar accounts, run it once per account, each with its own dry
   run first: `manage-agenda migrate-ledger -i --dry-run-ledger`, then
   `manage-agenda migrate-ledger -i`, choosing the same account both times. `-i` offers the
   choice even though an account is saved, and leaves the saved account (the one `add`
   publishes to) unchanged. Same for step 7: `reconcile -i` for each other account.
7. First ledger maintenance for that account, with `reconcile` rather than `add`, so no mail
   is touched:
   - `manage-agenda reconcile --dry-run-ledger`, then read `LOG_FILE`. It writes nothing
     (ledger, `.bak`, sync tokens), so the real run that follows makes the same bootstrap
     and applies what the preview showed:
     - `DRY RUN <identity>: event deleted, ignoring per on_user_delete=ignore.` (or
       `requeueing`) - a confirmed deletion (a `cancelled` tombstone);
     - `DRY RUN <identity>: ... return 404/410 ... journaling as unknown_event` - no Calendar
       record of the event at all, never treated as a deletion;
     - `DRY RUN purge: <identity> would be purged` - past its purge date;
     - `DRY RUN migrate: ...` - refs `migrate-ledger` left for retry;
     - `DRY RUN: would abandon ... sync token(s)` - legacy tokens, dropped by the real run.
   - `manage-agenda reconcile`: the same pass, for real.
   Don't preview with `add --dry-run-ledger`: it spares the ledger only, and still scans,
   publishes and marks new messages (§9).
8. Reactivate the scheduled jobs. The next `add` runs reconcile → migrate → purge
   automatically, as routine maintenance, then un-marks any `pending_requeue` entry.

**Also fixed along the way.** A socialModules rule key is a tuple, and `config.yaml`
(`yaml.safe_dump`) stores the saved `calendar_account` as a list. `prepare_calendar()` then
looked that list up in `rules.more`, which fails on an unhashable key, so every run after the
first saved choice crashed. The saved value is now turned back into a tuple. Both
`migrate-ledger` and the diagnostic resolve the account through this saved value.

**COPYUID was never captured on a MOVE.** Probe (f), run on 2026-09-22 against the IMAP
server behind `acme-auto`/`acme-review` (UIDPLUS and MOVE advertised), reported "no COPYUID"
after `UID MOVE`. The server was not at fault: RFC 6851 sends MOVE's COPYUID in an untagged
`* OK [COPYUID ...]` before the tagged OK, and imaplib does not return that with the command's
data. Its `Response_code` match files the code, brackets and name stripped, under
`client.untagged_responses["COPYUID"]` as `[b"uidvalidity src dest"]`, where it accumulates
until the next `select()`. `_imap_move_known_uid_safely` only parsed the tagged data
(`_parse_copyuid`), so the folder-mode locator was never recorded and requeue always fell back
to the Message-ID search. Now (`_copyuid_locator`) the tagged data is read first, then the
untagged entry, which is dropped before the command runs so a stale code from an earlier
COPY/MOVE on the same connection is never attributed to this one. Tests: a MOVE whose COPYUID
only arrives untagged yields the locator and consumes the entry; a stale entry with a MOVE
that sends none yields no locator; the untagged form is read for COPY too. The probe reads
the same place, so its "no COPYUID" verdict from that run is superseded, not re-run.

**Sync tokens are per (calendar account, calendar id).** `calendar_sync_tokens.json` is now
`{"accounts": {account_key: {calendar_id: token}}}`. The account is read from the connection
that makes the call (`api_dst.src`, through `connections.calendar_account_key()`, the same
key as the migration marker and the refs' `calendar_account`), never from the caller.
A calendar id alone doesn't identify a calendar: `primary` is each account's own primary
calendar. Two accounts alternating `add` runs on `primary` therefore each keep their own
token, and neither is ever handed the other's.
- **Tokens from the old format** (`{"tokens": {calendar_id: token}}`) can't be attributed to
  an account after the fact, so they are abandoned, never reused. The first real sync that
  finds any logs a warning listing their calendar ids and rewrites the file without them,
  even if its listing then fails. Each calendar's next sync re-bootstraps from the 90-day
  listing, exactly like a first run. That first bootstrap is the only sweep that reports
  deletions made before the upgrade: a delta from a token issued afterwards never will.
- **`--dry-run-ledger` writes nothing to the token file.** Reconcile forwards its `dry_run` to
  `sync_calendar_changes()`. The preview makes the same read-only Calendar calls a real run
  would, and ignores legacy tokens the same way, logging "DRY RUN: would abandon". But it
  stores no new token and leaves legacy ones on disk (its warning is logged once per run, not
  once per calendar). Before this, a preview advanced the tokens: the real run that followed
  then asked Calendar only for what changed since the preview, and the deletions the preview
  reported were never applied. That flaw predates the account keying and already hit step 7
  (preview the first run, then run it): the preview moved the legacy token past the
  backlog it reported. It is fixed on its own merits, with or without the account keying,
  and holds for `reconcile --dry-run-ledger` and `add --dry-run-ledger` alike.

- **A connection with no usable account key** reads and stores no token. Every sync for it
  bootstraps.

**Deletions are read from tombstones, never from absence.** Every listing, bootstrap and
delta alike, passes `showDeleted=True` (`extraction._list_all_pages`), so a deleted event
comes back with `status: "cancelled"` instead of just going missing. A tracked ref absent from
a bootstrap listing is not a deletion by itself. Whether it is looked up at all
(`extraction._should_confirm_missing`):
- with an `event_end`: while the event is still to come or within the ledger's purge margin
  (`event_end` + 30 days, `LEDGER_EVENT_END_MARGIN_DAYS`, not yet past) - whatever
  `recorded_at` says. An event planned long ago for a date still ahead is exactly the one
  whose deletion matters. Past that margin the entry is about to be purged: no lookup;
- without an `event_end` (a ref recorded before it was tracked, and not migrated): only if
  `recorded_at` is within the 90-day bootstrap window. Older, or no `recorded_at`: no lookup.
A looked-up ref gets one `events.get()` (`_confirm_missing_ids`): `status: "cancelled"` → a
confirmed deletion, resolved through `on_user_delete`. 404/410 → `unknown_event`, never a
deletion. Still live, or any other error → nothing reported, the entry is untouched. A ref not
looked up is untouched too. Either way the lookups stay bounded by current activity (events
still to come or recently ended), never by the ledger's whole history. Migrate has no such
window (§7): it is a one-off over the finite ledger, and it is what gives an old ref the
`event_end` this rule then keys on.

The 404 is only trusted once the calendar is known to be visible. A calendar this account
can't see fails at the listing itself, before any `events.get()`: nothing is reported for any
of its refs. Refs of other accounts, and legacy `primary` refs whose account is unknown, are
filtered out before that (`CalendarScope.owner_of`). Migrate calls the same 404 `gone`; it
looks up only calendars on this account's calendar list, for the same reason.

**Rollback.** Restore `handled_mail_ids.json.bak` over the ledger, and remove the account's
entry from `ledger_migration.json` (or the file) to close the gate again. The
`extendedProperties.private` keys already added to Calendar events are not removed. They are
additions only, and existing keys were preserved (§7).

**Tests** (`tests/test_ledger_migration_gate.py`), each mutation-checked:
- `add` before migration: ledger byte-identical, no `.bak`, no Calendar sync call, the
  already-handled message still skipped, warning naming the command.
- A marker for another calendar account does not open the gate; nor does no calendar
  connection.
- `migrate-ledger --dry-run-ledger`: the event was read, but nothing was patched, the ledger
  is unchanged, and there is no `.bak` and no marker.
- `migrate-ledger` (real): patched, `.bak` written, marker stamped, even on an empty ledger.
- After migration, `add` reconciles a cancellation into `cancelled_events` and purges an
  expired entry.
- A cancelled event is never patched and stays un-migrated, but gets its `event_end`
  backfilled (not under dry run).
- The tuple and list forms of the rule key give the same account key.
- Another account's calendar: skipped, never queried, not marked, then migrated by its own
  account's `migrate-ledger`. On this account's calendar, a missing event is `gone`; a
  calendar missing from the list is skipped and retried. A ref recorded for another account
  is skipped even on a calendar both can see. An unreadable calendar list migrates nothing,
  writes nothing and stamps nothing.
- New refs record `calendar_account`, including those recorded through `add`. Legacy
  `primary` refs are attached with one configured account (only previewed under dry run),
  and left alone, unqueried and logged with several.
- Reconcile never resolves another account's `primary` ref, even when a 404 would come back,
  and still resolves this account's legacy one.
- Requeue un-marking: skipped before migration, with the ledger byte-identical and no IMAP
  call; after migration it runs and forgets the entry.
- `tests/test_diagnose_ledger.py`: `calendar_inaccessible` for each of the three reasons,
  never queried; `not_found` only on this account's own calendar; the saved account is read
  back from its list form; no saved account and no `-i` → the only configured account, or
  with several an exit with `EXIT_CALENDAR_ACCOUNT_CHOICE_REQUIRED` (message on stderr,
  nothing on stdout, `readConfigSrc` never called), or with none
  `EXIT_NO_CALENDAR_ACCOUNT`; an unreadable calendar list exits `main()` with
  `EXIT_CALENDAR_LIST_UNREADABLE`; with an account saved, `-i` still offers the choice and
  leaves the config file byte-identical.
- `tests/test_connections.py`: the saved rule key read back as a list still resolves.
- Sync tokens (`tests/test_event_deletion_detection.py`, and end to end through `add` in
  `tests/test_ledger_migration_gate.py`):
  - two accounts alternating on `primary` each bootstrap once and then use their own token,
    never the other's;
  - a legacy token is abandoned (logged, dropped from the file, the next sync bootstraps)
    and never reused, even when that bootstrap fails;
  - with no account key, no token is read or stored, even with another account's token on
    file;
  - every legacy token is listed in the warning and dropped, not just the synced calendar's;
  - under dry run the token file stays byte-identical: legacy tokens are ignored but kept, and
    their warning logged once; a stored token is used but not advanced. End to end: an
    `add --dry-run-ledger` reports the backlog deletion its bootstrap found, then the real
    `add` performs the same bootstrap and applies it.
- The first timestamp is kept, and an unreadable marker file means "not migrated".
- `reconcile` (`TestReconcileCommand`, through the real CLI):
  - resolves a cancellation into `cancelled_events`, purges an expired entry and stores the
    new token, while every non-ledger step (`select_api`, `select_llm`, the mailbox scan,
    `_process_common_flow`, extraction/publishing, requeue un-marking, IMAP marking,
    `_delete_email`, `remember_handled_mail`) is never called and no mail account is opened;
  - `--dry-run-ledger`: it did sync and log the would-be resolution and purge, yet the ledger
    and the token file are byte-identical and there is no `.bak`; on a first bootstrap no
    token file is created;
  - gate closed (no marker, or another account's) → no Calendar call, no write; no calendar
    account → nothing runs;
  - a ref left for retry is migrated (`event_end` backfilled) before purge, as in `add`;
  - the new step 7: a `reconcile --dry-run-ledger` reports the backlog deletion found by its
    bootstrap, then the real `reconcile` makes the same bootstrap and applies it.
  - `tests/test_cli.py`: `-i` and `--dry-run-ledger` reach `reconcile_ledger_cli`.
- Tombstones, not absence (`tests/test_event_deletion_detection.py`): bootstrap and delta both
  send `showDeleted=True`; a ref missing from the bootstrap whose `get()` fails with a 500 is
  in neither set; at the reconcile level, one found live by `get()` leaves the ledger
  byte-identical, and one on a calendar whose listing fails is never looked up.
- Looked up by `event_end`, not `recorded_at` (same file): an event still to come, recorded
  120 days ago and deleted before the bootstrap → the deletion is detected and applied; an
  event ended 10 days ago (within the margin) is looked up; one ended 60 days ago is not, even
  recorded yesterday; a date-only `event_end` is understood; without `event_end`, an old
  `recorded_at` is still never looked up.
- Account selection (`TestLedgerAccountSelection`, through the real CLI and the real
  `select_calendar_account`): with account A saved, `migrate-ledger -i` migrates B's ref and
  stamps B only, A is never connected, and the config file stays byte-identical; without
  `-i` the saved A is used and B's ref left alone; `-i` with nothing saved saves nothing;
  `reconcile -i` reconciles B with A saved, config unchanged.
- Nothing saved, no `-i` (`TestLedgerAccountSelectionWithoutSavedAccount`, same setup): with
  one configured account, `migrate-ledger` and `reconcile` use it (never the interactive
  chooser, still nothing saved); with two configured, both commands print the message naming
  the accounts and `-i` - and only that message, no "no calendar account available" line -
  exit with `EXIT_CALENDAR_ACCOUNT_CHOICE_REQUIRED`, `readConfigSrc` is never called, no
  Calendar call is made, and the ledger, the token file and the marker file are untouched.
- Exit codes: no calendar account → `EXIT_NO_CALENDAR_ACCOUNT` for both commands; the gate
  closed (no marker, or another account's) → `EXIT_LEDGER_MIGRATION_REQUIRED` from
  `reconcile`; an unreadable calendar list → `EXIT_CALENDAR_LIST_UNREADABLE` from
  `migrate-ledger`, through the real CLI; `tests/test_cli.py`: each wrapper exits with
  whatever code its function returns, and 0 stays 0.
- Migration ignores the bootstrap window (`tests/test_migration.py`): a legacy ref recorded
  200 days ago for an event ending in 2030 is patched and gets its `event_end`; a purge run
  right after keeps the entry, while the same entry without the backfill is purged.
