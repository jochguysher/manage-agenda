import datetime
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import googleapiclient.errors

from manage_agenda.extraction import (
    _is_within_bootstrap_window,
    _load_sync_tokens,
    sync_calendar_changes,
)
from manage_agenda.sources import (
    LEDGER_NO_EVENT_MARGIN_DAYS,
    Args,
    _entry_purge_after,
    _extract_event_refs,
    load_handled_mail_ids,
    load_handled_mail_state,
    purge_expired_ledger_entries,
    reconcile_handled_events,
    remember_handled_mail,
    unseen_messages,
)


def http_error(status):
    return googleapiclient.errors.HttpError(SimpleNamespace(status=status, reason=""), b"{}")


def recent_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def old_iso(days=200):
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return moment.isoformat().replace("+00:00", "Z")


class ScriptedCalendarClient:
    """list(...) pops the next scripted response/exception in order; get(...) is looked up
    by (calendarId, eventId) - order-independent, since _confirm_missing_ids may call it for
    several ids in whatever order a set iterates."""

    def __init__(self, responses, get_responses=None):
        self._responses = list(responses)
        self._get_responses = dict(get_responses or {})
        self.calls = []
        self.get_calls = []

    def events(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._responses.pop(0)
        request = MagicMock()
        if isinstance(outcome, BaseException):
            request.execute.side_effect = outcome
        else:
            request.execute.return_value = outcome
        return request

    def get(self, calendarId, eventId):
        self.get_calls.append((calendarId, eventId))
        if (calendarId, eventId) not in self._get_responses:
            raise AssertionError(
                f"Unscripted get() for {(calendarId, eventId)} - add it to get_responses"
            )
        outcome = self._get_responses[(calendarId, eventId)]
        request = MagicMock()
        if isinstance(outcome, BaseException):
            request.execute.side_effect = outcome
        else:
            request.execute.return_value = outcome
        return request


def _api(responses, get_responses=None):
    client = ScriptedCalendarClient(responses, get_responses=get_responses)
    api = MagicMock()
    api.getClient.return_value = client
    return api, client


class TestSyncCalendarChanges(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_first_call_seeds_a_token_and_reports_no_deletions(self):
        api, client = _api([{"items": [{"id": "e1", "status": "confirmed"}], "nextSyncToken": "tok-1"}])

        cancelled, unknown = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(cancelled, set())
        self.assertEqual(unknown, set())
        self.assertEqual(_load_sync_tokens(self.path), {"cal-1": "tok-1"})
        self.assertNotIn("syncToken", client.calls[0])

    def test_bootstrap_listing_is_bounded_by_a_time_window(self):
        api, client = _api([{"items": [], "nextSyncToken": "tok-1"}])

        sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertIn("timeMin", client.calls[0])
        self.assertTrue(client.calls[0]["timeMin"].endswith("Z"))

    def test_time_min_is_never_combined_with_sync_token(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, client = _api([{"items": [], "nextSyncToken": "tok-new"}])

        sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertNotIn("timeMin", client.calls[0])

    def test_page_token_is_omitted_rather_than_sent_as_none(self):
        api, client = _api([{"items": [], "nextSyncToken": "tok-1"}])

        sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertNotIn("pageToken", client.calls[0])

    def test_bootstrap_confirms_a_missing_tracked_id_as_unknown_not_cancelled(self):
        """A 404 on the targeted confirmation is NOT proof of a user deletion - Calendar has
        no tombstone for it at all, which is equally consistent with the event never having
        existed. It must come back as `unknown`, never as `cancelled` (see
        docs/investigation-limite1.md §8 / reconcile_handled_events' unknown_event branch)."""
        api, client = _api(
            [{"items": [{"id": "e-still-there", "status": "confirmed"}]}],
            get_responses={("cal-1", "e-gone"): http_error(404)},
        )

        cancelled, unknown = sync_calendar_changes(
            api,
            "cal-1",
            tracked_events={"e-still-there": recent_iso(), "e-gone": recent_iso()},
            path=self.path,
        )

        self.assertEqual(cancelled, set())
        self.assertEqual(unknown, {"e-gone"})
        self.assertEqual(client.get_calls, [("cal-1", "e-gone")])

    def test_bootstrap_confirms_a_missing_tracked_id_with_an_explicit_cancelled_status(self):
        """The other confirmable outcome: get() succeeds and reports status="cancelled" - a
        genuine Calendar tombstone, correctly `cancelled`, not `unknown`."""
        api, client = _api(
            [{"items": []}],
            get_responses={("cal-1", "e-gone"): {"id": "e-gone", "status": "cancelled"}},
        )

        cancelled, unknown = sync_calendar_changes(
            api, "cal-1", tracked_events={"e-gone": recent_iso()}, path=self.path
        )

        self.assertEqual(cancelled, {"e-gone"})
        self.assertEqual(unknown, set())

    def test_id_missing_from_the_window_but_still_on_calendar_is_not_reported(self):
        """A tracked id can be absent from the bounded bootstrap listing just because its start
        time falls outside the window, not because it was deleted - the targeted confirmation
        must tell the two apart instead of treating "absent from the listing" as proof."""
        api, client = _api(
            [{"items": []}],
            get_responses={("cal-1", "e-far-future"): {"status": "confirmed"}},
        )

        cancelled, unknown = sync_calendar_changes(
            api, "cal-1", tracked_events={"e-far-future": recent_iso()}, path=self.path
        )

        self.assertEqual(cancelled, set())
        self.assertEqual(unknown, set())
        self.assertEqual(client.get_calls, [("cal-1", "e-far-future")])

    def test_confirmation_call_is_not_made_for_ids_already_seen_in_the_listing(self):
        api, client = _api([{"items": [{"id": "e-still-there", "status": "confirmed"}]}])

        sync_calendar_changes(
            api, "cal-1", tracked_events={"e-still-there": recent_iso()}, path=self.path
        )

        self.assertEqual(client.get_calls, [])

    def test_reseed_after_expiry_also_confirms_missing_tracked_ids_as_unknown(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, _client = _api(
            [http_error(410), {"items": [{"id": "e-still-there", "status": "confirmed"}]}],
            get_responses={("cal-1", "e-gone"): http_error(410)},
        )

        cancelled, unknown = sync_calendar_changes(
            api,
            "cal-1",
            tracked_events={"e-still-there": recent_iso(), "e-gone": recent_iso()},
            path=self.path,
        )

        self.assertEqual(cancelled, set())
        self.assertEqual(unknown, {"e-gone"})

    def test_ids_older_than_the_bootstrap_window_are_never_confirmed(self):
        """Discriminates the fix: without the recency filter, every tracked id missing from a
        bounded listing gets its own get() call regardless of age, so a reseed's cost would grow
        with the whole ledger's history instead of its recent activity."""
        api, client = _api([{"items": []}])
        tracked_events = {f"e-old-{i}": old_iso() for i in range(200)}

        cancelled, unknown = sync_calendar_changes(
            api, "cal-1", tracked_events=tracked_events, path=self.path
        )

        self.assertEqual(cancelled, set())
        self.assertEqual(unknown, set())
        self.assertEqual(client.get_calls, [])

    def test_a_ref_with_no_recorded_at_is_treated_as_outside_the_window(self):
        api, client = _api([{"items": []}])

        cancelled, unknown = sync_calendar_changes(
            api, "cal-1", tracked_events={"e-unknown-age": None}, path=self.path
        )

        self.assertEqual(cancelled, set())
        self.assertEqual(unknown, set())
        self.assertEqual(client.get_calls, [])

    def test_pagination_is_followed_until_the_last_page(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, client = _api(
            [
                {"items": [{"id": "e1", "status": "confirmed"}], "nextPageToken": "page-2"},
                {"items": [{"id": "e2", "status": "cancelled"}], "nextSyncToken": "tok-2"},
            ]
        )

        cancelled, unknown = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1]["pageToken"], "page-2")
        self.assertEqual(cancelled, {"e2"})
        self.assertEqual(unknown, set())
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-2")

    def test_existing_token_is_sent_and_cancelled_ids_are_reported(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, client = _api(
            [
                {
                    "items": [
                        {"id": "e1", "status": "confirmed"},
                        {"id": "e2", "status": "cancelled"},
                    ],
                    "nextSyncToken": "tok-new",
                }
            ]
        )

        cancelled, unknown = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(client.calls[0]["syncToken"], "tok-old")
        self.assertEqual(cancelled, {"e2"})
        self.assertEqual(unknown, set())
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-new")

    def test_a_syncToken_delta_never_reports_unknown_ids(self):
        """A delta only ever reports items Calendar has an explicit status for - the unknown
        (404/never-confirmed) case is only ever produced via the bootstrap path's targeted
        confirmation of ids missing from a full listing, never from a plain delta."""
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, _client = _api(
            [{"items": [{"id": "e2", "status": "cancelled"}], "nextSyncToken": "tok-new"}]
        )

        _cancelled, unknown = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(unknown, set())

    def test_expired_token_is_reseeded_without_reporting_deletions(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, client = _api(
            [
                http_error(410),
                {"items": [{"id": "e1", "status": "confirmed"}], "nextSyncToken": "tok-fresh"},
            ]
        )

        cancelled, unknown = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(cancelled, set())
        self.assertEqual(unknown, set())
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-fresh")
        self.assertNotIn("syncToken", client.calls[1])

    def test_other_api_error_is_conservative_and_keeps_the_old_token(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, _client = _api([http_error(500)])

        cancelled, unknown = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(cancelled, set())
        self.assertEqual(unknown, set())
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-old")


class TestExtractEventRefs(unittest.TestCase):
    def test_pulls_calendar_and_event_id_from_publish_results(self):
        calendar_result = [
            {"success": True, "calendar_id": "primary", "event_id": "abc"},
            {"success": True, "duplicate": True, "calendar_id": "primary", "event_id": ""},
            "not-a-dict",
        ]
        refs = _extract_event_refs(calendar_result)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["calendar_id"], "primary")
        self.assertEqual(refs[0]["event_id"], "abc")

    def test_records_when_the_ref_was_created(self):
        calendar_result = [{"success": True, "calendar_id": "primary", "event_id": "abc"}]
        refs = _extract_event_refs(calendar_result)
        self.assertTrue(_is_within_bootstrap_window(refs[0]["recorded_at"]))

    def test_falls_back_to_raw_response_id(self):
        calendar_result = [
            {"success": True, "calendar_id": "primary", "raw_response": {"id": "xyz"}},
        ]
        refs = _extract_event_refs(calendar_result)
        self.assertEqual(refs[0]["calendar_id"], "primary")
        self.assertEqual(refs[0]["event_id"], "xyz")

    def test_one_event_published_to_two_calendars_yields_a_ref_per_calendar(self):
        """The multi-calendar feature makes calendar_result carry one dict per (event,
        calendar) pair for a single message - both must reach the deletion-detection ledger,
        not just the first one."""
        calendar_result = [
            {"success": True, "calendar_id": "cal-1", "event_id": "e1"},
            {"success": True, "calendar_id": "cal-2", "event_id": "e2"},
        ]
        refs = _extract_event_refs(calendar_result)
        self.assertEqual(
            {(ref["calendar_id"], ref["event_id"]) for ref in refs},
            {("cal-1", "e1"), ("cal-2", "e2")},
        )

    def test_none_gives_empty_list(self):
        self.assertEqual(_extract_event_refs(None), [])


class TestHandledMailStateMigration(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_legacy_id_only_file_is_read_as_events_free_entries(self):
        self.path.write_text(json.dumps({"ids": ["old-1", "old-2"]}), encoding="utf-8")

        state = load_handled_mail_state(self.path)

        self.assertEqual(state["old-1"], {"events": [], "status": "legacy", "generation": 0})
        self.assertEqual(load_handled_mail_ids(self.path), {"old-1", "old-2"})

    def test_legacy_entries_are_still_skipped_by_unseen_messages(self):
        from email.message import EmailMessage

        self.path.write_text(json.dumps({"ids": ["legacy@x"]}), encoding="utf-8")
        message = EmailMessage()
        message["Message-ID"] = "<legacy@x>"

        fresh, skipped = unseen_messages([(1, message)], path=self.path)

        self.assertEqual(skipped, 1)
        self.assertEqual(fresh, [])

    def test_remember_handled_mail_without_events_is_legacy_equivalent(self):
        remember_handled_mail("msg-1", path=self.path)
        state = load_handled_mail_state(self.path)
        entry = state["msg-1"]
        self.assertIsInstance(entry.pop("recorded_at"), str)
        self.assertEqual(entry, {"events": [], "status": "no_event", "generation": 0})

    def test_remember_handled_mail_with_events_records_them(self):
        remember_handled_mail(
            "msg-1", path=self.path, events=[{"calendar_id": "primary", "event_id": "e1"}]
        )
        state = load_handled_mail_state(self.path)
        entry = state["msg-1"]
        self.assertIsInstance(entry.pop("recorded_at"), str)
        self.assertEqual(
            entry,
            {
                "events": [{"calendar_id": "primary", "event_id": "e1"}],
                "status": "created",
                "generation": 0,
            },
        )

    def test_remember_handled_mail_preserves_an_existing_generation(self):
        """A non-zero generation (bumped by the requeue resolution step) must survive being
        re-recorded - otherwise the next publish would recompute a deterministic id from
        generation 0 instead of the ledger's actual generation, drifting from the event that
        was really created under the bumped generation."""
        self.path.write_text(
            json.dumps(
                {"messages": {"msg-1": {"events": [], "status": "no_event", "generation": 2}}}
            ),
            encoding="utf-8",
        )

        remember_handled_mail(
            "msg-1", path=self.path, events=[{"calendar_id": "primary", "event_id": "e1"}]
        )

        state = load_handled_mail_state(self.path)
        self.assertEqual(state["msg-1"]["generation"], 2)

    def test_recording_the_same_ref_twice_with_different_timestamps_does_not_duplicate_it(self):
        """recorded_at differs between calls (it is "when recorded"), so dedup must key on
        (calendar_id, event_id), not on whole-dict equality."""
        remember_handled_mail(
            "msg-1",
            path=self.path,
            events=[{"calendar_id": "primary", "event_id": "e1", "recorded_at": old_iso()}],
        )
        remember_handled_mail(
            "msg-1",
            path=self.path,
            events=[{"calendar_id": "primary", "event_id": "e1", "recorded_at": recent_iso()}],
        )
        state = load_handled_mail_state(self.path)
        self.assertEqual(len(state["msg-1"]["events"]), 1)


class TestReconcileHandledEvents(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.sync_path = Path("/tmp") / (self.id().replace(".", "_") + "_sync.json")
        self.path.unlink(missing_ok=True)
        self.sync_path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))
        self.addCleanup(lambda: self.sync_path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.sync_path) + ".tmp").unlink(missing_ok=True))

    def _write_state(self, messages):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"messages": messages}), encoding="utf-8")

    def _seed_sync_token(self, calendar_id, token):
        self.sync_path.parent.mkdir(parents=True, exist_ok=True)
        self.sync_path.write_text(json.dumps({"tokens": {calendar_id: token}}), encoding="utf-8")

    def _seed_gone_and_present(self):
        self._write_state(
            {
                "msg-gone": {
                    "events": [{"calendar_id": "cal-1", "event_id": "ev-gone"}],
                    "status": "created",
                    "generation": 0,
                },
                "msg-present": {
                    "events": [{"calendar_id": "cal-1", "event_id": "ev-present"}],
                    "status": "created",
                },
                "msg-legacy": {"events": [], "status": "legacy"},
            }
        )
        self._seed_sync_token("cal-1", "tok-old")
        return _api(
            [
                {
                    "items": [
                        {"id": "ev-gone", "status": "cancelled"},
                        {"id": "ev-present", "status": "confirmed"},
                    ],
                    "nextSyncToken": "tok-new",
                }
            ]
        )

    def test_dry_run_computes_the_same_still_handled_but_writes_nothing(self):
        api, _client = self._seed_gone_and_present()
        args = Args(interactive=False)
        args.calendar_api = api
        before = self.path.read_text(encoding="utf-8")

        still_handled = reconcile_handled_events(
            args,
            path=self.path,
            sync_state_path=self.sync_path,
            on_user_delete="ignore",
            dry_run=True,
        )

        self.assertEqual(still_handled, {"msg-gone", "msg-present", "msg-legacy"})
        after = self.path.read_text(encoding="utf-8")
        self.assertEqual(before, after)
        # The identity that would have been resolved is still exactly as it was.
        entry = load_handled_mail_state(self.path)["msg-gone"]
        self.assertEqual(entry["status"], "created")
        self.assertNotIn("cancelled_events", entry)

    def test_dry_run_requeue_also_writes_nothing(self):
        api, _client = self._seed_gone_and_present()
        args = Args(interactive=False)
        args.calendar_api = api
        before = self.path.read_text(encoding="utf-8")

        still_handled = reconcile_handled_events(
            args,
            path=self.path,
            sync_state_path=self.sync_path,
            on_user_delete="requeue",
            dry_run=True,
        )

        self.assertEqual(still_handled, {"msg-present", "msg-legacy"})
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        entry = load_handled_mail_state(self.path)["msg-gone"]
        self.assertEqual(entry["status"], "created")
        self.assertEqual(entry["generation"], 0)

    def test_ignore_default_keeps_a_deleted_event_s_identity_excluded(self):
        """on_user_delete="ignore" (the validated default): the message stays marked
        processed and the deletion stands - there is no way to tell an accidental deletion
        from a deliberate one, so recreating by default would make a deliberate deletion
        impossible to keep (this is "limite 1")."""
        api, _client = self._seed_gone_and_present()
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(
            args, path=self.path, sync_state_path=self.sync_path, on_user_delete="ignore"
        )

        self.assertEqual(still_handled, {"msg-gone", "msg-present", "msg-legacy"})
        remaining_state = load_handled_mail_state(self.path)
        self.assertEqual(remaining_state["msg-gone"]["status"], "no_event")
        self.assertEqual(remaining_state["msg-gone"]["events"], [])
        # The deleted event's id is kept, not discarded - a future manual `restore` command
        # needs it, and it's what lets the entry purge on the longer event_end margin instead
        # of the short no_event fallback (see _entry_purge_after).
        self.assertEqual(
            [ev["event_id"] for ev in remaining_state["msg-gone"]["cancelled_events"]], ["ev-gone"]
        )
        self.assertIn("msg-present", remaining_state)
        self.assertIn("msg-legacy", remaining_state)

    def test_requeue_bumps_generation_and_excludes_the_identity_from_still_handled(self):
        """on_user_delete="requeue": the entry is kept (not deleted, not purged away by this
        call) with a bumped generation and a pending_requeue status, but is deliberately left
        out of still_handled - the caller is expected to un-mark the source message so a
        future scan can find it again; reconcile itself never touches any mailbox."""
        api, _client = self._seed_gone_and_present()
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(
            args, path=self.path, sync_state_path=self.sync_path, on_user_delete="requeue"
        )

        self.assertEqual(still_handled, {"msg-present", "msg-legacy"})
        remaining_state = load_handled_mail_state(self.path)
        self.assertEqual(remaining_state["msg-gone"]["status"], "pending_requeue")
        self.assertEqual(remaining_state["msg-gone"]["generation"], 1)
        self.assertEqual(remaining_state["msg-gone"]["events"], [])

    def test_unknown_event_is_never_requeued_either(self):
        """The unknown_event branch is checked before on_user_delete's own if/else, so it must
        pre-empt "requeue" too, not just the default "ignore" - a 404 is never a signal to
        recreate the event under a fresh id."""
        self._write_state(
            {
                "msg-1": {
                    "events": [{"calendar_id": "cal-1", "event_id": "ev-404", "recorded_at": recent_iso()}],
                    "status": "created",
                    "generation": 0,
                }
            }
        )
        # No token seeded - takes the bootstrap path, the only one that reaches the targeted
        # confirmation (a syncToken delta never reports unknown ids, see
        # TestSyncCalendarChanges).
        api, _client = _api(
            [{"items": [], "nextSyncToken": "tok-first"}],
            get_responses={("cal-1", "ev-404"): http_error(404)},
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(
            args, path=self.path, sync_state_path=self.sync_path, on_user_delete="requeue"
        )

        self.assertEqual(still_handled, {"msg-1"})
        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["status"], "unknown_event")
        self.assertEqual(entry["generation"], 0)  # never bumped

    def test_a_mix_of_cancelled_and_unknown_refs_resolves_as_unknown_event(self):
        """A multi-event identity where one ref is a genuine cancellation and another is a
        404 - ambiguous, so the whole identity resolves as unknown_event rather than
        partially applying on_user_delete to the cancelled one."""
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "cal-1", "event_id": "ev-cancelled", "recorded_at": recent_iso()},
                        {"calendar_id": "cal-1", "event_id": "ev-404", "recorded_at": recent_iso()},
                    ],
                    "status": "created",
                }
            }
        )
        # A syncToken delta never reports unknown ids (see TestSyncCalendarChanges), so the
        # mixed case has to go through the bootstrap path instead - the only one that can
        # produce an unknown id via its targeted confirmation.
        api, _client = _api(
            [{"items": [], "nextSyncToken": "tok-first"}],
            get_responses={
                ("cal-1", "ev-cancelled"): {"id": "ev-cancelled", "status": "cancelled"},
                ("cal-1", "ev-404"): http_error(404),
            },
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(still_handled, {"msg-1"})
        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["status"], "unknown_event")
        self.assertNotIn("cancelled_events", entry)

    def test_an_entry_both_cancelled_and_past_its_purge_margin_goes_through_reconcile_first(self):
        """Pins the call order in process_email_cli: reconcile_handled_events() must run
        before purge_expired_ledger_entries(), never the other way around. An entry whose
        event is cancelled in the sync delta AND already past its purge margin must still be
        resolved by reconcile (the ignore/requeue decision, journaled via a status change)
        before purge gets anywhere near it - if purge ran first it would drop the "created"
        entry outright, and the deletion would never go through on_user_delete's resolution
        at all, just silently vanish."""
        long_ago = (datetime.date.today() - datetime.timedelta(days=400)).isoformat()
        self._write_state(
            {
                "msg-gone-and-old": {
                    "events": [
                        {
                            "calendar_id": "cal-1",
                            "event_id": "ev-gone",
                            "event_end": f"{long_ago}T10:00:00Z",
                        }
                    ],
                    "status": "created",
                    "recorded_at": f"{long_ago}T00:00:00Z",
                },
            }
        )
        self._seed_sync_token("cal-1", "tok-old")
        api, _client = _api(
            [{"items": [{"id": "ev-gone", "status": "cancelled"}], "nextSyncToken": "tok-new"}]
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(
            args, path=self.path, sync_state_path=self.sync_path, on_user_delete="ignore"
        )
        # Reconcile's own resolution is visible immediately, before purge ever runs: the
        # deletion was journaled (status -> no_event), not silently dropped.
        self.assertEqual(still_handled, {"msg-gone-and-old"})
        after_reconcile = load_handled_mail_state(self.path)
        self.assertEqual(after_reconcile["msg-gone-and-old"]["status"], "no_event")

        purged = purge_expired_ledger_entries(path=self.path)

        # Only now, as a routine no_event entry well past its short margin, does purge take it.
        self.assertEqual(purged, 1)
        self.assertNotIn("msg-gone-and-old", load_handled_mail_state(self.path))

    def test_one_sync_call_per_calendar_regardless_of_event_count(self):
        self._write_state(
            {
                f"msg-{i}": {
                    "events": [{"calendar_id": "cal-1", "event_id": f"ev-{i}"}],
                    "status": "created",
                }
                for i in range(10)
            }
        )
        self._seed_sync_token("cal-1", "tok-old")
        api, client = _api([{"items": [], "nextSyncToken": "tok-new"}])
        args = Args(interactive=False)
        args.calendar_api = api

        reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(len(client.calls), 1)

    def test_no_calendar_connection_keeps_everything_handled(self):
        self._write_state(
            {"msg-1": {"events": [{"calendar_id": "cal-1", "event_id": "ev-1"}], "status": "created"}}
        )
        args = Args(interactive=False)
        args.calendar_api = None

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(still_handled, {"msg-1"})
        self.assertIn("msg-1", load_handled_mail_state(self.path))

    def test_requeued_message_is_offered_again_by_unseen_messages(self):
        """Only under on_user_delete="requeue" is a deleted-event identity excluded from
        `still_handled` - "ignore" (the default) keeps it excluded, see
        test_ignore_default_keeps_a_deleted_event_s_identity_excluded."""
        from email.message import EmailMessage

        self._write_state(
            {"<gone@x>": {"events": [{"calendar_id": "cal-1", "event_id": "ev-gone"}], "status": "created"}}
        )
        self._seed_sync_token("cal-1", "tok-old")
        api, _client = _api(
            [{"items": [{"id": "ev-gone", "status": "cancelled"}], "nextSyncToken": "tok-new"}]
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(
            args, path=self.path, sync_state_path=self.sync_path, on_user_delete="requeue"
        )

        message = EmailMessage()
        message["Message-ID"] = "<gone@x>"
        fresh, skipped = unseen_messages([(1, message)], handled=still_handled)

        self.assertEqual(skipped, 0)
        self.assertEqual([item[0] for item in fresh], [1])

    def test_first_ever_run_keeps_a_still_present_event_and_seeds_a_token(self):
        self._write_state(
            {"msg-1": {"events": [{"calendar_id": "cal-1", "event_id": "ev-1"}], "status": "created"}}
        )
        api, client = _api(
            [{"items": [{"id": "ev-1", "status": "confirmed"}], "nextSyncToken": "tok-first"}]
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(still_handled, {"msg-1"})
        self.assertNotIn("syncToken", client.calls[0])
        self.assertEqual(_load_sync_tokens(self.sync_path)["cal-1"], "tok-first")

    def test_first_ever_run_also_detects_a_genuine_deletion_via_the_bootstrap_diff(self):
        """No prior sync token yet still catches a genuine deletion: a tracked id absent from
        the bootstrap listing, confirmed by a targeted lookup that returns an explicit
        status="cancelled" - not just "no baseline, report nothing"."""
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "cal-1", "event_id": "ev-gone", "recorded_at": recent_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        api, _client = _api(
            [{"items": [], "nextSyncToken": "tok-first"}],
            get_responses={("cal-1", "ev-gone"): {"id": "ev-gone", "status": "cancelled"}},
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        # Default on_user_delete="ignore": the deletion is resolved (journaled to no_event),
        # not released - the identity stays excluded.
        self.assertEqual(still_handled, {"msg-1"})
        self.assertEqual(load_handled_mail_state(self.path)["msg-1"]["status"], "no_event")

    def test_first_ever_run_bootstrap_diff_404_is_unknown_not_a_deletion(self):
        """The same "absent from the bootstrap listing" situation, but the targeted lookup
        comes back 404 (no Calendar record at all, not a tombstone) - must resolve as
        unknown_event, never as a deletion, regardless of on_user_delete."""
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "cal-1", "event_id": "ev-gone", "recorded_at": recent_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        api, _client = _api(
            [{"items": [], "nextSyncToken": "tok-first"}],
            get_responses={("cal-1", "ev-gone"): http_error(404)},
        )
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(still_handled, {"msg-1"})
        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["status"], "unknown_event")
        self.assertEqual(entry["events"], [])
        self.assertNotIn("cancelled_events", entry)

    def test_old_untraceable_events_never_trigger_a_confirmation_call_in_reconcile(self):
        """Ties the age-skip to the real entry point: an old-enough tracked event, missing from
        a first-ever bootstrap listing, is left alone rather than confirmed - and so stays
        handled, since reconcile has no way to tell whether it was deleted."""
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "cal-1", "event_id": "ev-old", "recorded_at": old_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        api, client = _api([{"items": [], "nextSyncToken": "tok-first"}])
        args = Args(interactive=False)
        args.calendar_api = api

        still_handled = reconcile_handled_events(args, path=self.path, sync_state_path=self.sync_path)

        self.assertEqual(still_handled, {"msg-1"})
        self.assertEqual(client.get_calls, [])


class TestEntryPurgeAfter(unittest.TestCase):
    """Unit tests for the purge-date computation itself - see amendment 2:
    docs/investigation-limite1.md, "purge rules must cover no_event and source_lost entries
    too, plus multi-event max(end date)"."""

    def test_purges_on_event_end_not_recorded_at(self):
        entry = {
            "events": [
                {
                    "calendar_id": "primary",
                    "event_id": "e1",
                    "event_end": "2026-01-01T10:00:00Z",
                    "recorded_at": "2020-01-01T00:00:00Z",
                }
            ],
            "status": "created",
            "recorded_at": "2020-01-01T00:00:00Z",
        }
        purge_after = _entry_purge_after(entry, event_margin_days=30, no_event_margin_days=7)
        self.assertEqual(
            purge_after,
            datetime.datetime(2026, 1, 31, 10, tzinfo=datetime.timezone.utc),
        )

    def test_multi_event_purges_on_the_latest_end_date(self):
        entry = {
            "events": [
                {"calendar_id": "primary", "event_id": "e1", "event_end": "2026-01-01T10:00:00Z"},
                {"calendar_id": "primary", "event_id": "e2", "event_end": "2026-06-01T10:00:00Z"},
            ],
            "status": "created",
        }
        purge_after = _entry_purge_after(entry, event_margin_days=10, no_event_margin_days=7)
        self.assertEqual(
            purge_after,
            datetime.datetime(2026, 6, 11, 10, tzinfo=datetime.timezone.utc),
        )

    def test_no_event_entry_falls_back_to_recorded_at(self):
        entry = {"events": [], "status": "no_event", "recorded_at": "2026-01-01T00:00:00Z"}
        purge_after = _entry_purge_after(entry, event_margin_days=30, no_event_margin_days=7)
        self.assertEqual(
            purge_after,
            datetime.datetime(2026, 1, 8, tzinfo=datetime.timezone.utc),
        )

    def test_source_lost_with_no_event_end_falls_back_to_recorded_at(self):
        """source_lost (a resolution-chain outcome, not yet produced by any code path) has no
        live event to read an end date from - same log-date fallback as no_event."""
        entry = {"events": [], "status": "source_lost", "recorded_at": "2026-01-01T00:00:00Z"}
        purge_after = _entry_purge_after(entry, event_margin_days=30, no_event_margin_days=7)
        self.assertEqual(
            purge_after,
            datetime.datetime(2026, 1, 8, tzinfo=datetime.timezone.utc),
        )

    def test_unknown_event_falls_back_to_recorded_at_like_no_event(self):
        """A 404/410-on-first-sight ref (see test_first_ever_run_bootstrap_diff_404_is_unknown_not_a_deletion
        and reconcile_handled_events' unknown_event resolution) never had a confirmed live
        event either - it must not become a new eternal category exempt from purging, and
        must not silently earn the longer event_end margin it never had anything to base that
        on. Same short no_event-style fallback as "no_event"/"source_lost"."""
        entry = {"events": [], "status": "unknown_event", "recorded_at": "2026-01-01T00:00:00Z"}
        purge_after = _entry_purge_after(entry, event_margin_days=30, no_event_margin_days=7)
        self.assertEqual(
            purge_after,
            datetime.datetime(2026, 1, 8, tzinfo=datetime.timezone.utc),
        )

    def test_ignored_deletion_earns_the_event_end_margin_not_the_short_fallback(self):
        """An on_user_delete="ignore" resolution moves the deleted ref to cancelled_events
        (see reconcile_handled_events) - it must still purge on the longer event_end margin,
        not the short no_event fallback, since it did have a real event until now."""
        entry = {
            "events": [],
            "cancelled_events": [
                {"calendar_id": "primary", "event_id": "ev-gone", "event_end": "2026-01-01T10:00:00Z"}
            ],
            "status": "no_event",
            "recorded_at": "2020-01-01T00:00:00Z",
        }
        purge_after = _entry_purge_after(entry, event_margin_days=30, no_event_margin_days=7)
        self.assertEqual(
            purge_after,
            datetime.datetime(2026, 1, 31, 10, tzinfo=datetime.timezone.utc),
        )

    def test_legacy_entry_with_no_age_signal_is_never_purged(self):
        entry = {"events": [], "status": "legacy"}
        self.assertIsNone(_entry_purge_after(entry, event_margin_days=30, no_event_margin_days=7))

    def test_date_only_event_end_is_accepted(self):
        entry = {
            "events": [{"calendar_id": "primary", "event_id": "e1", "event_end": "2026-01-01"}],
            "status": "created",
        }
        purge_after = _entry_purge_after(entry, event_margin_days=1, no_event_margin_days=7)
        self.assertEqual(purge_after, datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc))


class TestPurgeExpiredLedgerEntries(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def _write_state(self, messages):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"messages": messages}), encoding="utf-8")

    def test_expired_entries_are_dropped_and_fresh_ones_kept(self):
        self._write_state(
            {
                "old": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "event_end": "2020-01-01T00:00:00Z"}
                    ],
                    "status": "created",
                },
                "fresh": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e2", "event_end": "2099-01-01T00:00:00Z"}
                    ],
                    "status": "created",
                },
            }
        )
        today = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)

        purged = purge_expired_ledger_entries(path=self.path, today=today)

        self.assertEqual(purged, 1)
        state = load_handled_mail_state(self.path)
        self.assertEqual(set(state.keys()), {"fresh"})

    def test_no_event_entry_expires_on_its_own_short_margin(self):
        self._write_state(
            {"old-no-event": {"events": [], "status": "no_event", "recorded_at": "2020-01-01T00:00:00Z"}}
        )
        today = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)

        purged = purge_expired_ledger_entries(path=self.path, today=today)

        self.assertEqual(purged, 1)
        self.assertEqual(load_handled_mail_state(self.path), {})

    def test_unknown_event_entry_expires_on_its_own_short_margin(self):
        """unknown_event (a 404/410-on-first-sight ref, see reconcile_handled_events) must not
        become a new eternal category - it purges through the exact same code path and margin
        as no_event, not a special case that was forgotten when unknown_event was added."""
        self._write_state(
            {
                "old-unknown": {
                    "events": [],
                    "status": "unknown_event",
                    "recorded_at": "2020-01-01T00:00:00Z",
                }
            }
        )
        today = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)

        purged = purge_expired_ledger_entries(path=self.path, today=today)

        self.assertEqual(purged, 1)
        self.assertEqual(load_handled_mail_state(self.path), {})

    def test_created_entry_with_no_event_end_and_no_recorded_at_also_gets_a_grace_pass(self):
        """Same guarantee as the legacy-format test below, but for a "created" entry whose
        ref simply predates the event_end field and whose entry predates recorded_at - not
        just the {"ids": [...]} legacy format."""
        self._write_state(
            {"msg-1": {"events": [{"calendar_id": "primary", "event_id": "e1"}], "status": "created"}}
        )
        first_pass = datetime.datetime(2099, 1, 1, tzinfo=datetime.timezone.utc)

        purged = purge_expired_ledger_entries(path=self.path, today=first_pass)
        self.assertEqual(purged, 0)
        self.assertEqual(
            load_handled_mail_state(self.path)["msg-1"]["recorded_at"], "2099-01-01T00:00:00Z"
        )

        second_pass = first_pass + datetime.timedelta(days=LEDGER_NO_EVENT_MARGIN_DAYS + 1)
        purged = purge_expired_ledger_entries(path=self.path, today=second_pass)
        self.assertEqual(purged, 1)

    def test_legacy_entry_with_no_recorded_at_gets_one_grace_pass_then_purges(self):
        """No entry may be exempt from purging forever just for lacking history it never
        had (a pre-migration legacy entry with no event_end and no recorded_at at all):
        the first call stamps recorded_at (a one-time grace pass, not an immediate purge),
        and a later call past the short margin from that stamp purges it - it can no longer
        stay in the ledger indefinitely."""
        self.path.write_text(json.dumps({"ids": ["old-legacy"]}), encoding="utf-8")
        first_pass = datetime.datetime(2099, 1, 1, tzinfo=datetime.timezone.utc)

        purged = purge_expired_ledger_entries(path=self.path, today=first_pass)

        self.assertEqual(purged, 0)
        entry = load_handled_mail_state(self.path)["old-legacy"]
        self.assertEqual(entry["recorded_at"], "2099-01-01T00:00:00Z")

        second_pass = first_pass + datetime.timedelta(days=LEDGER_NO_EVENT_MARGIN_DAYS + 1)
        purged = purge_expired_ledger_entries(path=self.path, today=second_pass)

        self.assertEqual(purged, 1)
        self.assertEqual(load_handled_mail_state(self.path), {})

    def test_the_grace_period_is_a_full_margin_not_just_the_very_next_call(self):
        """Discriminates the fix from a naive "immune for exactly one call regardless of
        elapsed time" reading: a second call made at the SAME moment as the stamp (or before
        the margin elapses) must still keep the entry - the grace period is
        recorded_at + no_event_margin_days, not a call counter."""
        self.path.write_text(json.dumps({"ids": ["old-legacy"]}), encoding="utf-8")
        moment = datetime.datetime(2099, 1, 1, tzinfo=datetime.timezone.utc)

        purge_expired_ledger_entries(path=self.path, today=moment)
        # Second call, same instant - the stamp from the first call must not have already
        # expired.
        purged = purge_expired_ledger_entries(path=self.path, today=moment)
        self.assertEqual(purged, 0)
        self.assertIn("old-legacy", load_handled_mail_state(self.path))

        # A third call, one day before the margin elapses - still not purged.
        almost = moment + datetime.timedelta(days=LEDGER_NO_EVENT_MARGIN_DAYS - 1)
        purged = purge_expired_ledger_entries(path=self.path, today=almost)
        self.assertEqual(purged, 0)
        self.assertIn("old-legacy", load_handled_mail_state(self.path))

    def test_nothing_to_purge_does_not_rewrite_the_file(self):
        self._write_state(
            {
                "fresh": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "event_end": "2099-01-01T00:00:00Z"}
                    ],
                    "status": "created",
                }
            }
        )
        before = self.path.stat().st_mtime_ns

        purged = purge_expired_ledger_entries(
            path=self.path, today=datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)
        )

        self.assertEqual(purged, 0)
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_dry_run_reports_what_would_be_purged_but_writes_nothing(self):
        self._write_state(
            {
                "old": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "event_end": "2020-01-01T00:00:00Z"}
                    ],
                    "status": "created",
                },
                "fresh": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e2", "event_end": "2099-01-01T00:00:00Z"}
                    ],
                    "status": "created",
                },
            }
        )
        before = self.path.read_text(encoding="utf-8")

        purged = purge_expired_ledger_entries(
            path=self.path,
            today=datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc),
            dry_run=True,
        )

        self.assertEqual(purged, 1)  # reports what WOULD be purged
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)  # but writes nothing
        self.assertEqual(set(load_handled_mail_state(self.path).keys()), {"old", "fresh"})

    def test_dry_run_never_stamps_the_grace_pass_recorded_at(self):
        self._write_state(
            {"msg-1": {"events": [{"calendar_id": "primary", "event_id": "e1"}], "status": "created"}}
        )
        before = self.path.read_text(encoding="utf-8")

        purge_expired_ledger_entries(
            path=self.path,
            today=datetime.datetime(2099, 1, 1, tzinfo=datetime.timezone.utc),
            dry_run=True,
        )

        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertNotIn("recorded_at", load_handled_mail_state(self.path)["msg-1"])

    def test_state_size_stays_bounded_across_years_of_activity(self):
        """The hard constraint behind the whole redesign: local state size must track current
        activity, not the tool's whole history. Simulates 5 years of daily messages (each with
        an event ending the same day, plus a scattering of no_event entries) and asserts that
        after a purge, only the recent tail remains - not a set that grows with N."""
        start = datetime.date(2021, 1, 1)
        days = 5 * 365
        messages = {}
        for offset in range(days):
            day = start + datetime.timedelta(days=offset)
            iso_day = day.isoformat()
            if offset % 30 == 0:
                messages[f"no-event-{offset}"] = {
                    "events": [],
                    "status": "no_event",
                    "recorded_at": f"{iso_day}T00:00:00Z",
                }
            else:
                messages[f"msg-{offset}"] = {
                    "events": [
                        {
                            "calendar_id": "primary",
                            "event_id": f"e{offset}",
                            "event_end": f"{iso_day}T10:00:00Z",
                        }
                    ],
                    "status": "created",
                }
        self._write_state(messages)
        today = datetime.datetime(
            start.year + 5, start.month, start.day, tzinfo=datetime.timezone.utc
        )

        purge_expired_ledger_entries(
            path=self.path, today=today, event_margin_days=30, no_event_margin_days=7
        )

        remaining = load_handled_mail_state(self.path)
        # Only entries within their respective margins of `today` can possibly remain.
        self.assertLess(len(remaining), 40)
        self.assertTrue(all(not identity.startswith("no-event-") for identity in remaining))


class TestReconcileMigrateAndPurge(unittest.TestCase):
    """reconcile_migrate_and_purge() is where the reconcile -> migrate -> purge order is
    guaranteed structurally, not left to a caller to get right - see
    docs/investigation-limite1.md §9."""

    def test_calls_all_three_in_order_and_forwards_dry_run(self):
        from unittest.mock import patch

        from manage_agenda.sources import reconcile_migrate_and_purge

        order = []
        args = Args(interactive=False)

        with (
            patch("manage_agenda.sources.reconcile_handled_events") as mock_reconcile,
            patch("manage_agenda.sources.migrate_legacy_ledger_entries") as mock_migrate,
            patch("manage_agenda.sources.purge_expired_ledger_entries") as mock_purge,
        ):
            mock_reconcile.side_effect = lambda *a, **k: order.append("reconcile") or {"msg-1"}
            mock_migrate.side_effect = lambda *a, **k: order.append("migrate") or 2
            mock_purge.side_effect = lambda *a, **k: order.append("purge") or 3

            handled, migrated_count, purged_count = reconcile_migrate_and_purge(
                args, dry_run=True
            )

        self.assertEqual(order, ["reconcile", "migrate", "purge"])
        self.assertEqual(handled, {"msg-1"})
        self.assertEqual(migrated_count, 2)
        self.assertEqual(purged_count, 3)
        self.assertTrue(mock_reconcile.call_args.kwargs["dry_run"])
        self.assertTrue(mock_migrate.call_args.kwargs["dry_run"])
        self.assertTrue(mock_purge.call_args.kwargs["dry_run"])

    def test_forwards_path_sync_state_path_and_on_user_delete_to_reconcile(self):
        from unittest.mock import patch

        from manage_agenda.sources import reconcile_migrate_and_purge

        args = Args(interactive=False)

        with (
            patch("manage_agenda.sources.reconcile_handled_events") as mock_reconcile,
            patch("manage_agenda.sources.migrate_legacy_ledger_entries"),
            patch("manage_agenda.sources.purge_expired_ledger_entries"),
        ):
            mock_reconcile.return_value = set()
            reconcile_migrate_and_purge(
                args,
                path="/tmp/ledger.json",
                sync_state_path="/tmp/sync.json",
                on_user_delete="requeue",
            )

        self.assertEqual(mock_reconcile.call_args.kwargs["path"], "/tmp/ledger.json")
        self.assertEqual(mock_reconcile.call_args.kwargs["sync_state_path"], "/tmp/sync.json")
        self.assertEqual(mock_reconcile.call_args.kwargs["on_user_delete"], "requeue")


if __name__ == "__main__":
    unittest.main()
