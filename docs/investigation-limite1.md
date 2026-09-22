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
| — | Does `modifyLabels(id, old, None)` (`addLabelIds: [null]`) work as manage-agenda currently calls it | Unresolvable by reading code | not scripted (existing behavior, not a new probe target — flagging only) |

None of the probe scripts have been run. They require a test calendar (and, for probe d,
a test IMAP account/folder) that only you can safely provide.
