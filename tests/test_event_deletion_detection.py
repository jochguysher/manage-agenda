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

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(result, set())
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

    def test_bootstrap_confirms_a_missing_tracked_id_before_reporting_it_deleted(self):
        api, client = _api(
            [{"items": [{"id": "e-still-there", "status": "confirmed"}]}],
            get_responses={("cal-1", "e-gone"): http_error(404)},
        )

        result = sync_calendar_changes(
            api,
            "cal-1",
            tracked_events={"e-still-there": recent_iso(), "e-gone": recent_iso()},
            path=self.path,
        )

        self.assertEqual(result, {"e-gone"})
        self.assertEqual(client.get_calls, [("cal-1", "e-gone")])

    def test_id_missing_from_the_window_but_still_on_calendar_is_not_reported(self):
        """A tracked id can be absent from the bounded bootstrap listing just because its start
        time falls outside the window, not because it was deleted - the targeted confirmation
        must tell the two apart instead of treating "absent from the listing" as proof."""
        api, client = _api(
            [{"items": []}],
            get_responses={("cal-1", "e-far-future"): {"status": "confirmed"}},
        )

        result = sync_calendar_changes(
            api, "cal-1", tracked_events={"e-far-future": recent_iso()}, path=self.path
        )

        self.assertEqual(result, set())
        self.assertEqual(client.get_calls, [("cal-1", "e-far-future")])

    def test_confirmation_call_is_not_made_for_ids_already_seen_in_the_listing(self):
        api, client = _api([{"items": [{"id": "e-still-there", "status": "confirmed"}]}])

        sync_calendar_changes(
            api, "cal-1", tracked_events={"e-still-there": recent_iso()}, path=self.path
        )

        self.assertEqual(client.get_calls, [])

    def test_reseed_after_expiry_also_confirms_missing_tracked_ids(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, _client = _api(
            [http_error(410), {"items": [{"id": "e-still-there", "status": "confirmed"}]}],
            get_responses={("cal-1", "e-gone"): http_error(410)},
        )

        result = sync_calendar_changes(
            api,
            "cal-1",
            tracked_events={"e-still-there": recent_iso(), "e-gone": recent_iso()},
            path=self.path,
        )

        self.assertEqual(result, {"e-gone"})

    def test_ids_older_than_the_bootstrap_window_are_never_confirmed(self):
        """Discriminates the fix: without the recency filter, every tracked id missing from a
        bounded listing gets its own get() call regardless of age, so a reseed's cost would grow
        with the whole ledger's history instead of its recent activity."""
        api, client = _api([{"items": []}])
        tracked_events = {f"e-old-{i}": old_iso() for i in range(200)}

        result = sync_calendar_changes(api, "cal-1", tracked_events=tracked_events, path=self.path)

        self.assertEqual(result, set())
        self.assertEqual(client.get_calls, [])

    def test_a_ref_with_no_recorded_at_is_treated_as_outside_the_window(self):
        api, client = _api([{"items": []}])

        result = sync_calendar_changes(
            api, "cal-1", tracked_events={"e-unknown-age": None}, path=self.path
        )

        self.assertEqual(result, set())
        self.assertEqual(client.get_calls, [])

    def test_pagination_is_followed_until_the_last_page(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, client = _api(
            [
                {"items": [{"id": "e1", "status": "confirmed"}], "nextPageToken": "page-2"},
                {"items": [{"id": "e2", "status": "cancelled"}], "nextSyncToken": "tok-2"},
            ]
        )

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1]["pageToken"], "page-2")
        self.assertEqual(result, {"e2"})
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

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(client.calls[0]["syncToken"], "tok-old")
        self.assertEqual(result, {"e2"})
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-new")

    def test_expired_token_is_reseeded_without_reporting_deletions(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, client = _api(
            [
                http_error(410),
                {"items": [{"id": "e1", "status": "confirmed"}], "nextSyncToken": "tok-fresh"},
            ]
        )

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(result, set())
        self.assertEqual(_load_sync_tokens(self.path)["cal-1"], "tok-fresh")
        self.assertNotIn("syncToken", client.calls[1])

    def test_other_api_error_is_conservative_and_keeps_the_old_token(self):
        self.path.write_text(json.dumps({"tokens": {"cal-1": "tok-old"}}), encoding="utf-8")
        api, _client = _api([http_error(500)])

        result = sync_calendar_changes(api, "cal-1", path=self.path)

        self.assertEqual(result, set())
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

    def test_first_ever_run_also_detects_a_deletion_via_the_bootstrap_diff(self):
        """No prior sync token yet still catches a deletion: a tracked id absent from the
        bootstrap listing is confirmed by a targeted lookup, not just "no baseline, report
        nothing"."""
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

        # Default on_user_delete="ignore": the deletion is resolved (journaled to no_event),
        # not released - the identity stays excluded.
        self.assertEqual(still_handled, {"msg-1"})
        self.assertEqual(load_handled_mail_state(self.path)["msg-1"]["status"], "no_event")

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


if __name__ == "__main__":
    unittest.main()
