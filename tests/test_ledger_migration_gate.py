"""The explicit `migrate-ledger` command and the per-calendar-account gate it opens in
process_email_cli (see docs/investigation-limite1.md §12).

Until `migrate-ledger` has completed a real pass for a calendar account, `add` must skip
reconcile/migrate/purge entirely - no ledger write from any of them - while still skipping
every already-handled message. Once it has, `add` runs all three automatically again.
"""

import datetime
import json
from unittest.mock import MagicMock, patch

import googleapiclient.errors
from click.testing import CliRunner

from manage_agenda import cli
from manage_agenda.extraction import calendar_sync_state_file, migrate_one_legacy_event
from manage_agenda.sources import (
    Args,
    CalendarScope,
    _extract_event_refs,
    calendar_scope_for,
    handled_mail_file,
    ledger_migrated_for,
    ledger_migration_account_key,
    ledger_migration_file,
    load_handled_mail_state,
    migrate_ledger_cli,
    migrate_legacy_ledger_entries,
    process_email_cli,
    record_ledger_migration,
)

ACCOUNT_SRC = ("gcalendar", "set", "me@example.com", "posts")
ACCOUNT_KEY = "gcalendar|set|me@example.com|posts"
OTHER_SRC = ("gcalendar", "set", "work@example.com", "posts")
OTHER_KEY = "gcalendar|set|work@example.com|posts"


def _iso(days_ago):
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return moment.isoformat().replace("+00:00", "Z")


def _request(value):
    request = MagicMock()
    if isinstance(value, BaseException):
        request.execute.side_effect = value
    else:
        request.execute.return_value = value
    return request


class FakeCalendarClient:
    """events().list() returns `list_items` as one syncToken delta page; events().get() looks
    events up by (calendarId, eventId), 404 when absent; events().patch() is recorded.
    calendarList().list() returns `calendar_ids` (None: the call fails)."""

    def __init__(self, list_items=(), events_by_id=None, calendar_ids=("cal-1",)):
        self.list_items = list(list_items)
        self.events_by_id = dict(events_by_id or {})
        self.calendar_ids = calendar_ids
        self.list_calls, self.get_calls, self.patch_calls = [], [], []

    def events(self):
        return self

    def calendarList(self):
        client = self

        class _CalendarList:
            def list(self, **kwargs):
                if client.calendar_ids is None:
                    return _request(RuntimeError("calendarList unavailable"))
                return _request({"items": [{"id": cid} for cid in client.calendar_ids]})

        return _CalendarList()

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return _request({"items": self.list_items, "nextSyncToken": "tok-next"})

    def get(self, calendarId, eventId):
        self.get_calls.append((calendarId, eventId))
        event = self.events_by_id.get((calendarId, eventId))
        if event is None:
            from types import SimpleNamespace

            return _request(googleapiclient.errors.HttpError(SimpleNamespace(status=404, reason=""), b"{}"))
        return _request(event)

    def patch(self, calendarId, eventId, body):
        self.patch_calls.append((calendarId, eventId, body))
        return _request({})


def _calendar_api(client, src=ACCOUNT_SRC):
    api = MagicMock(src=src)
    api.getClient.return_value = client
    return api


def _prepare_calendar_with(api):
    def prepare(args, rules=None):
        args.calendar_api = api
        args.calendar_ids = ["cal-1"]
        return True

    return prepare


def load_handled_mail_state_from_bytes(raw):
    """The ledger as load_handled_mail_state() would parse these file bytes."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ledger.json"
        path.write_bytes(raw)
        return load_handled_mail_state(path)


def _write_ledger(messages):
    path = handled_mail_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"messages": messages}), encoding="utf-8")
    return path


def _seed_sync_token(calendar_id="cal-1", token="tok-old"):
    path = calendar_sync_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tokens": {calendar_id: token}}), encoding="utf-8")


def _handled_message(message_id):
    message = MagicMock()
    message.get.side_effect = lambda key, default=None: {"Message-ID": f"<{message_id}>"}.get(key, default)
    return ("1", message)


def _ledger_needing_reconcile_and_purge():
    """msg-cancelled: its event comes back cancelled in the sync delta (reconcile would move
    it to cancelled_events). msg-expired: a no_event entry 400 days old (purge would drop it).
    Either one changes the ledger file if its step runs."""
    return {
        "msg-cancelled": {
            "events": [
                {
                    "calendar_id": "cal-1",
                    "event_id": "ev-cancelled",
                    "recorded_at": _iso(10),
                    "event_end": _iso(-30),  # in 30 days: well inside its purge margin
                    "migrated": True,
                }
            ],
            "status": "created",
            "recorded_at": _iso(10),
        },
        "msg-expired": {"events": [], "status": "no_event", "recorded_at": _iso(400)},
    }


def _run_add(api, posts, dry_run_ledger=False, configured=(ACCOUNT_SRC,), mail_api=None, source_details=None):
    """process_email_cli on a mail account (non-IMAP unless `mail_api` says otherwise),
    calendar account `api`, `configured` gcalendar accounts in socialModules, with the mailbox
    scan returning `posts`. Returns the mocked _process_common_flow and what the scan was told
    was already handled."""
    args = Args(interactive=False, source="gmail", dry_run_ledger=dry_run_ledger)
    if mail_api is None:
        mail_api = MagicMock()
        mail_api.service = "gmail"
    with (
        patch("manage_agenda.sources.moduleRules") as mock_rules,
        patch("manage_agenda.sources.prepare_calendar", side_effect=_prepare_calendar_with(api)),
        patch("manage_agenda.sources._get_emails_from_folder", return_value=posts) as mock_scan,
        patch("manage_agenda.sources._process_common_flow") as mock_flow,
    ):
        rules = mock_rules.from_config.return_value
        rules.more = {"mail-account": source_details or {}}
        rules.readConfigSrc.return_value = mail_api
        rules.selectRule.return_value = list(configured)
        process_email_cli(args, MagicMock(), selected_source="mail-account")
    return mock_flow, mock_scan.call_args.kwargs["handled"]


class TestAddBeforeMigration:
    def test_add_writes_nothing_to_the_ledger_and_still_skips_handled_messages(self, capsys):
        ledger = _write_ledger(_ledger_needing_reconcile_and_purge())
        before = ledger.read_bytes()
        _seed_sync_token()
        client = FakeCalendarClient(list_items=[{"id": "ev-cancelled", "status": "cancelled"}])

        mock_flow, handled = _run_add(_calendar_api(client), [_handled_message("msg-cancelled")])

        assert ledger.read_bytes() == before
        assert not ledger.with_suffix(".json.bak").exists()
        # Reconcile never ran: not even its read-only Calendar sync.
        assert client.list_calls == []
        # Already-handled messages are still excluded - an empty `handled` would rescan the
        # whole mailbox and recreate events as duplicates.
        assert handled == {"msg-cancelled", "msg-expired"}
        mock_flow.assert_not_called()
        output = capsys.readouterr().out
        assert "migrate-ledger --dry-run-ledger" in output
        assert ACCOUNT_KEY in output

    def test_a_marker_for_another_calendar_account_does_not_open_the_gate(self):
        ledger = _write_ledger(_ledger_needing_reconcile_and_purge())
        before = ledger.read_bytes()
        record_ledger_migration("some-other-account")

        _run_add(_calendar_api(FakeCalendarClient()), None)

        assert ledger.read_bytes() == before

    def test_no_calendar_connection_skips_the_trio_too(self):
        """`-o file` (and `llm evaluate --type email`) have no calendar account to key a
        marker on - fail closed: no purge of the real ledger from a run with no Calendar."""
        ledger = _write_ledger(_ledger_needing_reconcile_and_purge())
        before = ledger.read_bytes()

        _run_add(None, None)

        assert ledger.read_bytes() == before


def _migrate(api, *extra, configured=(ACCOUNT_SRC,)):
    """`manage-agenda migrate-ledger` through the real CLI, connected to calendar account
    `api`, with `configured` gcalendar accounts in socialModules."""
    with (
        patch("manage_agenda.sources.moduleRules") as mock_rules,
        patch("manage_agenda.sources.prepare_calendar", side_effect=_prepare_calendar_with(api)),
    ):
        mock_rules.from_config.return_value.selectRule.return_value = list(configured)
        return CliRunner().invoke(cli.cli, ["migrate-ledger", *extra])


def _live(event_id):
    return {"id": event_id, "status": "confirmed", "end": {"dateTime": "2030-01-15T11:00:00Z"}}


def _ref(calendar_id, event_id, **extra):
    return {"calendar_id": calendar_id, "event_id": event_id, "recorded_at": _iso(10), **extra}


def _entry(*refs, status="created"):
    return {"events": list(refs), "status": status, "recorded_at": _iso(10)}


class TestMigrateLedgerCommand:
    def _invoke(self, api, *extra):
        return _migrate(api, *extra)

    def _ledger_with_one_unmigrated_ref(self):
        return _write_ledger(
            {
                "msg-live": {
                    "events": [{"calendar_id": "cal-1", "event_id": "ev-live", "recorded_at": _iso(10)}],
                    "status": "created",
                    "recorded_at": _iso(10),
                }
            }
        )

    def _live_event(self):
        return {"id": "ev-live", "status": "confirmed", "end": {"dateTime": "2030-01-15T11:00:00Z"}}

    def test_dry_run_writes_nothing_and_does_not_mark_the_account(self):
        ledger = self._ledger_with_one_unmigrated_ref()
        before = ledger.read_bytes()
        client = FakeCalendarClient(events_by_id={("cal-1", "ev-live"): self._live_event()})

        result = self._invoke(_calendar_api(client), "--dry-run-ledger")

        assert result.exit_code == 0, result.output
        # It really looked (non-vacuous), and reported what it would do.
        assert client.get_calls == [("cal-1", "ev-live")]
        assert "1" in result.output and ACCOUNT_KEY in result.output
        assert client.patch_calls == []
        assert ledger.read_bytes() == before
        assert not ledger.with_suffix(".json.bak").exists()
        assert not ledger_migration_file().exists()
        assert not ledger_migrated_for(ACCOUNT_KEY)

    def test_real_pass_migrates_backs_up_and_marks_the_account(self):
        ledger = self._ledger_with_one_unmigrated_ref()
        client = FakeCalendarClient(events_by_id={("cal-1", "ev-live"): self._live_event()})

        result = self._invoke(_calendar_api(client))

        assert result.exit_code == 0, result.output
        assert len(client.patch_calls) == 1
        assert load_handled_mail_state(ledger)["msg-live"]["events"][0]["migrated"] is True
        assert ledger.with_suffix(".json.bak").exists()
        assert ledger_migrated_for(ACCOUNT_KEY)

    def test_real_pass_on_an_empty_ledger_still_marks_the_account(self):
        result = self._invoke(_calendar_api(FakeCalendarClient()))

        assert result.exit_code == 0, result.output
        assert ledger_migrated_for(ACCOUNT_KEY)

    def test_no_calendar_account_marks_nothing(self):
        args = Args(interactive=False)
        with (
            patch("manage_agenda.sources.moduleRules"),
            patch("manage_agenda.sources.prepare_calendar", return_value=False),
        ):
            assert migrate_ledger_cli(args) is False

        assert not ledger_migration_file().exists()

    def test_a_cancelled_event_is_never_patched_and_stays_unmigrated(self):
        """migrate-ledger runs without reconcile first - a cancelled event still returned by
        events.get() must not be patched (whether that could bring it back is unverified)."""
        ledger = _write_ledger(
            {
                "msg-cancelled": {
                    "events": [{"calendar_id": "cal-1", "event_id": "ev-cancelled", "recorded_at": _iso(10)}],
                    "status": "created",
                }
            }
        )
        client = FakeCalendarClient(
            events_by_id={("cal-1", "ev-cancelled"): {"id": "ev-cancelled", "status": "cancelled"}}
        )

        self._invoke(_calendar_api(client))

        assert client.patch_calls == []
        assert "migrated" not in load_handled_mail_state(ledger)["msg-cancelled"]["events"][0]


class TestAddAfterMigration:
    def test_add_reconciles_and_purges_normally_once_migrated(self):
        ledger = _write_ledger(_ledger_needing_reconcile_and_purge())
        _seed_sync_token()
        client = FakeCalendarClient(list_items=[{"id": "ev-cancelled", "status": "cancelled"}])
        api = _calendar_api(client)
        with (
            patch("manage_agenda.sources.moduleRules"),
            patch("manage_agenda.sources.prepare_calendar", side_effect=_prepare_calendar_with(api)),
        ):
            assert migrate_ledger_cli(Args(interactive=False)) is True

        _mock_flow, handled = _run_add(api, None)

        state = load_handled_mail_state(ledger)
        # Reconcile resolved the cancellation (on_user_delete=ignore, the default)...
        assert state["msg-cancelled"]["status"] == "no_event"
        assert state["msg-cancelled"]["cancelled_events"][0]["event_id"] == "ev-cancelled"
        # ...and purge dropped the expired entry.
        assert "msg-expired" not in state
        assert "msg-cancelled" in handled


class TestMarkerAndAccountKey:
    def test_tuple_and_list_rule_keys_give_the_same_account_key(self):
        """api.src is a tuple when picked interactively, a list once read back from
        config.yaml - both must map to the same marker."""
        from_tuple = Args(interactive=False)
        from_tuple.calendar_api = MagicMock(src=ACCOUNT_SRC)
        from_list = Args(interactive=False)
        from_list.calendar_api = MagicMock(src=list(ACCOUNT_SRC))

        assert ledger_migration_account_key(from_tuple) == ACCOUNT_KEY
        assert ledger_migration_account_key(from_list) == ACCOUNT_KEY

    def test_no_usable_key_is_none(self):
        no_api = Args(interactive=False)
        unknown_src = Args(interactive=False)
        unknown_src.calendar_api = MagicMock()  # .src is a MagicMock, not a rule key

        assert ledger_migration_account_key(no_api) is None
        assert ledger_migration_account_key(unknown_src) is None
        assert not ledger_migrated_for(None)

    def test_the_first_timestamp_is_kept(self):
        first = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        record_ledger_migration(ACCOUNT_KEY, now=first)
        record_ledger_migration(ACCOUNT_KEY, now=first + datetime.timedelta(days=30))

        stored = json.loads(ledger_migration_file().read_text(encoding="utf-8"))
        assert stored["accounts"][ACCOUNT_KEY] == "2026-01-01T00:00:00Z"

    def test_an_unreadable_marker_file_counts_as_not_migrated(self):
        path = ledger_migration_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json", encoding="utf-8")

        assert not ledger_migrated_for(ACCOUNT_KEY)


class TestMigrateOneLegacyEventCancelled:
    def test_cancelled_event_is_not_patched(self):
        client = FakeCalendarClient(
            events_by_id={("cal-1", "ev-1"): {"id": "ev-1", "status": "cancelled", "end": {"date": "2030-01-01"}}}
        )

        status, event_end = migrate_one_legacy_event(client, "cal-1", "ev-1", "msg-1", 0, 0)

        assert status == "cancelled"
        assert client.patch_calls == []
        # Still read: the caller backfills it (see the next test).
        assert event_end == "2030-01-01"

    def _ledger_and_args_with_a_cancelled_ref(self):
        ledger = _write_ledger(
            {
                "msg-1": {
                    "events": [{"calendar_id": "cal-1", "event_id": "ev-1", "recorded_at": _iso(60)}],
                    "status": "created",
                    "recorded_at": _iso(60),
                }
            }
        )
        args = Args(interactive=False)
        args.calendar_api = _calendar_api(
            FakeCalendarClient(
                events_by_id={
                    ("cal-1", "ev-1"): {"id": "ev-1", "status": "cancelled", "end": {"date": "2030-01-01"}}
                }
            )
        )
        args.calendar_scope = CalendarScope(account_key=ACCOUNT_KEY, owned_ids={"cal-1"})
        return ledger, args

    def test_migrate_legacy_ledger_entries_leaves_a_cancelled_ref_for_reconcile(self):
        ledger, args = self._ledger_and_args_with_a_cancelled_ref()

        count = migrate_legacy_ledger_entries(args)

        assert count == 0
        ref = load_handled_mail_state(ledger)["msg-1"]["events"][0]
        assert "migrated" not in ref
        # event_end backfilled: once reconcile moves this ref to cancelled_events, the entry
        # keeps the event_end-based purge margin instead of recorded_at + 7 days (already
        # past here - the entry, and `restore`'s record of it, would be purged at once).
        assert ref["event_end"] == "2030-01-01"

    def test_a_cancelled_ref_is_not_backfilled_under_dry_run(self):
        ledger, args = self._ledger_and_args_with_a_cancelled_ref()
        before = ledger.read_bytes()

        migrate_legacy_ledger_entries(args, dry_run=True)

        assert ledger.read_bytes() == before


class TestOtherCalendarAccountsEntries:
    """migrate-ledger only touches refs of the calendar account it is connected to. Anything
    else is skipped BEFORE events.get() - never marked migrated - so the migration of its own
    account still processes it later."""

    def test_another_accounts_calendar_is_skipped_unmarked_then_migrated_by_its_own_account(self):
        ledger = _write_ledger(
            {"msg-mine": _entry(_ref("cal-1", "ev-mine")), "msg-theirs": _entry(_ref("cal-work", "ev-theirs"))}
        )
        mine = FakeCalendarClient(
            events_by_id={("cal-1", "ev-mine"): _live("ev-mine"), ("cal-work", "ev-theirs"): _live("ev-theirs")},
            calendar_ids=("cal-1",),
        )

        result = _migrate(_calendar_api(mine), configured=(ACCOUNT_SRC, OTHER_SRC))

        assert result.exit_code == 0, result.output
        assert ("cal-work", "ev-theirs") not in mine.get_calls
        assert [call[:2] for call in mine.patch_calls] == [("cal-1", "ev-mine")]
        assert "migrated" not in load_handled_mail_state(ledger)["msg-theirs"]["events"][0]
        assert "1 left alone" in result.output

        theirs = FakeCalendarClient(
            events_by_id={("cal-work", "ev-theirs"): _live("ev-theirs")}, calendar_ids=("cal-work",)
        )
        result = _migrate(_calendar_api(theirs, src=OTHER_SRC), configured=(ACCOUNT_SRC, OTHER_SRC))

        assert result.exit_code == 0, result.output
        assert [call[:2] for call in theirs.patch_calls] == [("cal-work", "ev-theirs")]
        assert load_handled_mail_state(ledger)["msg-theirs"]["events"][0]["migrated"] is True
        assert ledger_migrated_for(ACCOUNT_KEY) and ledger_migrated_for(OTHER_KEY)

    def test_inaccessible_calendar_is_retried_only_a_missing_event_is_gone(self):
        ledger = _write_ledger(
            {
                "msg-gone": _entry(_ref("cal-1", "ev-deleted")),
                "msg-unreachable": _entry(_ref("cal-unshared", "ev-x")),
            }
        )
        client = FakeCalendarClient(calendar_ids=("cal-1",))  # every get() is a 404

        _migrate(_calendar_api(client))

        state = load_handled_mail_state(ledger)
        # Own calendar, event absent: gone, and never retried.
        assert state["msg-gone"]["events"][0]["migrated"] is True
        # Calendar not visible from this account: never queried, left for a later run.
        assert "migrated" not in state["msg-unreachable"]["events"][0]
        assert ("cal-unshared", "ev-x") not in client.get_calls

    def test_a_ref_recorded_for_another_account_is_skipped_even_on_a_visible_calendar(self):
        ledger = _write_ledger({"msg-1": _entry(_ref("cal-1", "ev-1", calendar_account=OTHER_KEY))})
        client = FakeCalendarClient(events_by_id={("cal-1", "ev-1"): _live("ev-1")}, calendar_ids=("cal-1",))

        _migrate(_calendar_api(client))

        assert client.get_calls == []
        assert "migrated" not in load_handled_mail_state(ledger)["msg-1"]["events"][0]

    def test_an_unreadable_calendar_list_migrates_nothing_and_marks_nothing(self):
        """Without the calendar list nothing can be told apart as this account's - stamping
        the marker on such a pass would open the gate with no migration ever done."""
        ledger = _write_ledger({"msg-1": _entry(_ref("cal-1", "ev-1"))})
        before = ledger.read_bytes()
        client = FakeCalendarClient(events_by_id={("cal-1", "ev-1"): _live("ev-1")}, calendar_ids=None)
        api = _calendar_api(client)

        with (
            patch("manage_agenda.sources.moduleRules"),
            patch("manage_agenda.sources.prepare_calendar", side_effect=_prepare_calendar_with(api)),
        ):
            assert migrate_ledger_cli(Args(interactive=False)) is False

        assert client.get_calls == [] and client.patch_calls == []
        assert ledger.read_bytes() == before
        assert not ledger.with_suffix(".json.bak").exists()
        assert not ledger_migrated_for(ACCOUNT_KEY)


class TestPrimaryIsRelativeToTheAccount:
    def test_new_refs_record_their_calendar_account(self):
        result = [{"calendar_id": "primary", "event_id": "ev-1"}]

        assert _extract_event_refs(result, calendar_account=ACCOUNT_KEY)[0]["calendar_account"] == ACCOUNT_KEY
        assert "calendar_account" not in _extract_event_refs(result)[0]

    def test_add_stores_the_calendar_account_on_the_refs_it_records(self):
        _write_ledger({})
        mock_flow, _handled = _run_add(_calendar_api(FakeCalendarClient()), [_handled_message("new@example.com")])
        on_item_done = mock_flow.call_args.kwargs["on_item_done"]

        on_item_done(_handled_message("new@example.com"), 0, [{"calendar_id": "primary", "event_id": "ev-new"}])

        ref = load_handled_mail_state()["new@example.com"]["events"][0]
        assert ref["calendar_account"] == ACCOUNT_KEY

    def _legacy_primary_ledger(self):
        return _write_ledger(
            {
                "msg-live": _entry(_ref("primary", "ev-live")),
                "msg-deleted": {
                    "events": [],
                    "cancelled_events": [_ref("primary", "ev-old")],
                    "status": "no_event",
                    "recorded_at": _iso(10),
                },
            }
        )

    def test_legacy_primary_refs_are_attached_when_one_calendar_account_is_configured(self):
        ledger = self._legacy_primary_ledger()
        client = FakeCalendarClient(events_by_id={("primary", "ev-live"): _live("ev-live")})

        result = _migrate(_calendar_api(client), configured=(ACCOUNT_SRC,))

        assert result.exit_code == 0, result.output
        state = load_handled_mail_state(ledger)
        live = state["msg-live"]["events"][0]
        assert live["calendar_account"] == ACCOUNT_KEY and live["migrated"] is True
        assert state["msg-deleted"]["cancelled_events"][0]["calendar_account"] == ACCOUNT_KEY

    def test_attaching_is_only_previewed_under_dry_run(self):
        ledger = self._legacy_primary_ledger()
        before = ledger.read_bytes()
        client = FakeCalendarClient(events_by_id={("primary", "ev-live"): _live("ev-live")})

        result = _migrate(_calendar_api(client), "--dry-run-ledger", configured=(ACCOUNT_SRC,))

        assert ledger.read_bytes() == before
        assert "2 legacy 'primary' ref(s) would be attached" in result.output

    def test_legacy_primary_refs_are_left_alone_when_several_accounts_are_configured(self, caplog):
        ledger = self._legacy_primary_ledger()
        before = ledger.read_bytes()
        client = FakeCalendarClient(events_by_id={("primary", "ev-live"): _live("ev-live")})

        with caplog.at_level("INFO"):
            result = _migrate(_calendar_api(client), configured=(ACCOUNT_SRC, OTHER_SRC))

        assert result.exit_code == 0, result.output
        assert client.get_calls == [] and client.patch_calls == []
        # Nothing attached, nothing marked migrated - the ledger itself is untouched.
        assert load_handled_mail_state(ledger) == load_handled_mail_state_from_bytes(before)
        assert any("owner unknown" in record.getMessage() for record in caplog.records)

    def test_reconcile_never_resolves_another_accounts_primary_ref(self):
        """The destructive case: this account's primary listing doesn't contain another
        account's event, its get() answers 404 - without the account filter the entry would be
        journaled unknown_event and its live event wiped from the ledger."""
        ledger = _write_ledger(
            {
                # event_end in the future: inside the purge margin, so only reconcile could
                # change these entries (purge is account-agnostic by design - age only).
                "msg-legacy": _entry(_ref("primary", "ev-legacy", event_end=_iso(-30))),
                "msg-theirs": _entry(_ref("primary", "ev-theirs", calendar_account=OTHER_KEY, event_end=_iso(-30))),
            }
        )
        before = load_handled_mail_state(ledger)
        record_ledger_migration(ACCOUNT_KEY)
        client = FakeCalendarClient(list_items=[])  # no sync token: bootstrap, every get() 404s

        _mock_flow, handled = _run_add(_calendar_api(client), None, configured=(ACCOUNT_SRC, OTHER_SRC))

        assert load_handled_mail_state(ledger) == before
        assert client.get_calls == []
        assert {"msg-legacy", "msg-theirs"} <= handled

    def test_reconcile_still_resolves_this_accounts_legacy_primary_ref(self):
        ledger = _write_ledger({"msg-1": _entry(_ref("primary", "ev-1", event_end=_iso(-30)))})
        record_ledger_migration(ACCOUNT_KEY)
        _seed_sync_token("primary")
        client = FakeCalendarClient(list_items=[{"id": "ev-1", "status": "cancelled"}])

        _run_add(_calendar_api(client), None, configured=(ACCOUNT_SRC,))

        assert load_handled_mail_state(ledger)["msg-1"]["status"] == "no_event"


class _FakeImapClient:
    """Answers a keyword un-mark as a real server would: one message found, flag removed."""

    def __init__(self):
        self.uid_calls = []

    def select(self, folder):
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.uid_calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [b"42"]
        return "OK", []


class TestRequeueStepIsGated:
    """The requeue un-marking removes a ledger entry on success (forget_handled_mail) - it is
    ledger maintenance too, so it waits for the migration like reconcile and purge."""

    def _imap_account(self):
        imap_client = _FakeImapClient()
        mail_api = MagicMock()
        mail_api.service = "imap"
        mail_api.getClient.return_value = imap_client
        details = {"folder": "INBOX", "processed_marker": "keyword:$AgendaDone"}
        return imap_client, mail_api, details

    def _ledger_with_a_pending_requeue(self):
        return _write_ledger(
            {"req@example.com": {"events": [], "status": "pending_requeue", "generation": 1, "recorded_at": _iso(5)}}
        )

    def test_before_migration_the_pending_requeue_entry_is_left_alone(self):
        ledger = self._ledger_with_a_pending_requeue()
        before = ledger.read_bytes()
        imap_client, mail_api, details = self._imap_account()

        _run_add(_calendar_api(FakeCalendarClient()), None, mail_api=mail_api, source_details=details)

        assert ledger.read_bytes() == before
        assert imap_client.uid_calls == []

    def test_after_migration_the_pending_requeue_entry_is_unmarked_and_forgotten(self):
        ledger = self._ledger_with_a_pending_requeue()
        record_ledger_migration(ACCOUNT_KEY)
        imap_client, mail_api, details = self._imap_account()

        _run_add(_calendar_api(FakeCalendarClient()), None, mail_api=mail_api, source_details=details)

        assert ("STORE", "42", "-FLAGS", "($AgendaDone)") in imap_client.uid_calls
        assert "req@example.com" not in load_handled_mail_state(ledger)


class TestAccountKeyThroughTheRealSelectionPaths:
    """The sole-account rule compares the account key of the connected calendar (api.src, set by
    socialModules' readConfigSrc to the rule key it was given) with the keys selectRule returns.
    Both must agree on every path prepare_calendar takes - including a rule key saved to
    config.yaml and read back as a list - or legacy "primary" refs would never be attributed."""

    def _rules(self):
        rules = MagicMock()
        rules.more = {ACCOUNT_SRC: {}}
        rules.selectRule.return_value = [ACCOUNT_SRC]

        def read_config_src(indent, src, more):
            api = MagicMock(src=src)  # what socialModules' readConfigSrc does: apiSrc.src = src
            api.getClient.return_value = FakeCalendarClient()
            return api

        rules.readConfigSrc.side_effect = read_config_src
        return rules

    def test_saved_account_read_back_from_config_yaml(self, tmp_path):
        from manage_agenda.connections import prepare_calendar
        from manage_agenda.user_config import save_user_config

        config_path = tmp_path / "config.yaml"
        save_user_config({"calendar_account": ACCOUNT_SRC, "calendar": ["cal-1"]}, config_path)
        rules = self._rules()
        args = Args(interactive=False)

        assert prepare_calendar(args, rules=rules, config_path=config_path)
        scope = calendar_scope_for(args, rules)

        assert scope.account_key == ACCOUNT_KEY
        assert scope.sole_account is True

    def test_first_configured_account_when_nothing_is_saved(self, tmp_path):
        from manage_agenda.connections import prepare_calendar

        rules = self._rules()
        args = Args(interactive=False, destination="cal-1")

        assert prepare_calendar(args, rules=rules, config_path=tmp_path / "config.yaml")
        scope = calendar_scope_for(args, rules)

        assert scope.account_key == ACCOUNT_KEY
        assert scope.sole_account is True
