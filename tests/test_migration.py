import datetime
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import googleapiclient.errors

from manage_agenda.extraction import migrate_one_legacy_event
from manage_agenda.sources import Args, load_handled_mail_state, migrate_legacy_ledger_entries


def http_error(status):
    return googleapiclient.errors.HttpError(SimpleNamespace(status=status, reason=""), b"{}")


def _client_with_get(get_response):
    client = MagicMock()
    if isinstance(get_response, BaseException):
        client.events.return_value.get.return_value.execute.side_effect = get_response
    else:
        client.events.return_value.get.return_value.execute.return_value = get_response
    client.events.return_value.patch.return_value.execute.return_value = {"success": True}
    return client


class TestMigrateOneLegacyEvent(unittest.TestCase):
    def test_live_unstamped_event_is_patched(self):
        existing = {
            "id": "legacy-1",
            "end": {"dateTime": "2026-09-22T16:00:00-04:00"},
            "extendedProperties": {"private": {"ai_model_used": "gemini"}},
        }
        client = _client_with_get(existing)

        status, event_end = migrate_one_legacy_event(
            client, "primary", "legacy-1", "msg-1", 0, 0
        )

        self.assertEqual(status, "migrated")
        self.assertEqual(event_end, "2026-09-22T16:00:00-04:00")
        client.events.return_value.patch.assert_called_once()
        body = client.events.return_value.patch.call_args.kwargs["body"]
        private = body["extendedProperties"]["private"]
        # Existing properties preserved, not wiped out by sending only the new keys.
        self.assertEqual(private["ai_model_used"], "gemini")
        self.assertEqual(private["origin"], "manage-agenda")
        self.assertEqual(private["sourceMailId"], "msg-1")
        self.assertEqual(private["generation"], "0")
        self.assertEqual(private["eventIndex"], "0")
        # Never touches the event's own id.
        self.assertNotIn("id", body)

    def test_already_stamped_event_is_not_re_patched(self):
        existing = {
            "id": "legacy-1",
            "end": {"dateTime": "2026-09-22T16:00:00-04:00"},
            "extendedProperties": {"private": {"origin": "manage-agenda"}},
        }
        client = _client_with_get(existing)

        status, event_end = migrate_one_legacy_event(
            client, "primary", "legacy-1", "msg-1", 0, 0
        )

        self.assertEqual(status, "already_migrated")
        self.assertEqual(event_end, "2026-09-22T16:00:00-04:00")
        client.events.return_value.patch.assert_not_called()

    def test_confirmed_gone_event_is_not_retried_later(self):
        client = _client_with_get(http_error(404))

        status, event_end = migrate_one_legacy_event(
            client, "primary", "legacy-1", "msg-1", 0, 0
        )

        self.assertEqual(status, "gone")
        self.assertIsNone(event_end)
        client.events.return_value.patch.assert_not_called()

    def test_ambiguous_get_error_is_left_for_retry(self):
        client = _client_with_get(http_error(500))

        status, event_end = migrate_one_legacy_event(
            client, "primary", "legacy-1", "msg-1", 0, 0
        )

        self.assertEqual(status, "retry")
        self.assertIsNone(event_end)

    def test_patch_failure_is_left_for_retry_even_though_get_succeeded(self):
        existing = {"id": "legacy-1", "end": {"dateTime": "2026-09-22T16:00:00-04:00"}}
        client = _client_with_get(existing)
        client.events.return_value.patch.return_value.execute.side_effect = Exception("boom")

        status, event_end = migrate_one_legacy_event(
            client, "primary", "legacy-1", "msg-1", 0, 0
        )

        self.assertEqual(status, "retry")
        self.assertIsNone(event_end)

    def test_event_with_no_end_field_migrates_with_no_event_end(self):
        existing = {"id": "legacy-1"}
        client = _client_with_get(existing)

        status, event_end = migrate_one_legacy_event(
            client, "primary", "legacy-1", "msg-1", 0, 0
        )

        self.assertEqual(status, "migrated")
        self.assertIsNone(event_end)

    def test_dry_run_never_calls_patch(self):
        existing = {
            "id": "legacy-1",
            "end": {"dateTime": "2026-09-22T16:00:00-04:00"},
            "extendedProperties": {"private": {"ai_model_used": "gemini"}},
        }
        client = _client_with_get(existing)

        status, event_end = migrate_one_legacy_event(
            client, "primary", "legacy-1", "msg-1", 0, 0, dry_run=True
        )

        self.assertEqual(status, "would_migrate")
        self.assertEqual(event_end, "2026-09-22T16:00:00-04:00")
        client.events.return_value.patch.assert_not_called()

    def test_dry_run_still_reports_gone_and_already_migrated(self):
        client_gone = _client_with_get(http_error(404))
        status, _ = migrate_one_legacy_event(client_gone, "primary", "e1", "msg-1", 0, 0, dry_run=True)
        self.assertEqual(status, "gone")

        already = {"id": "e2", "extendedProperties": {"private": {"origin": "manage-agenda"}}}
        client_already = _client_with_get(already)
        status, _ = migrate_one_legacy_event(client_already, "primary", "e2", "msg-1", 0, 0, dry_run=True)
        self.assertEqual(status, "already_migrated")
        client_already.events.return_value.patch.assert_not_called()


class TestMigrateLegacyLedgerEntries(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def _write_state(self, messages):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"messages": messages}), encoding="utf-8")

    def _args_with_client(self, get_response):
        args = Args(interactive=False)
        api = MagicMock()
        api.getClient.return_value = _client_with_get(get_response)
        args.calendar_api = api
        return args

    def _recent_iso(self):
        return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    def _old_iso(self):
        moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=200)
        return moment.isoformat().replace("+00:00", "Z")

    def test_no_calendar_connection_is_a_no_op(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "recorded_at": self._recent_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        args = Args(interactive=False)
        args.calendar_api = None

        migrated = migrate_legacy_ledger_entries(args, path=self.path)

        self.assertEqual(migrated, 0)

    def test_migrates_a_recent_unstamped_ref_and_backfills_event_end(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "recorded_at": self._recent_iso()}
                    ],
                    "status": "created",
                    "generation": 0,
                }
            }
        )
        existing = {"id": "e1", "end": {"dateTime": "2026-09-22T16:00:00-04:00"}}
        args = self._args_with_client(existing)

        migrated = migrate_legacy_ledger_entries(args, path=self.path)

        self.assertEqual(migrated, 1)
        ref = load_handled_mail_state(self.path)["msg-1"]["events"][0]
        self.assertTrue(ref["migrated"])
        self.assertEqual(ref["event_end"], "2026-09-22T16:00:00-04:00")

    def test_a_ref_outside_the_bootstrap_window_is_left_alone(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "recorded_at": self._old_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        existing = {"id": "e1", "end": {"dateTime": "2026-09-22T16:00:00-04:00"}}
        args = self._args_with_client(existing)

        migrated = migrate_legacy_ledger_entries(args, path=self.path)

        self.assertEqual(migrated, 0)
        ref = load_handled_mail_state(self.path)["msg-1"]["events"][0]
        self.assertNotIn("migrated", ref)
        args.calendar_api.getClient.return_value.events.return_value.get.assert_not_called()

    def test_an_already_migrated_ref_is_never_touched_again(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {
                            "calendar_id": "primary",
                            "event_id": "e1",
                            "recorded_at": self._recent_iso(),
                            "migrated": True,
                            "event_end": "2026-09-22T16:00:00-04:00",
                        }
                    ],
                    "status": "created",
                }
            }
        )
        args = self._args_with_client({"id": "e1"})

        migrated = migrate_legacy_ledger_entries(args, path=self.path)

        self.assertEqual(migrated, 0)
        args.calendar_api.getClient.return_value.events.return_value.get.assert_not_called()

    def test_an_ambiguous_error_leaves_the_ref_for_a_future_retry(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "recorded_at": self._recent_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        args = self._args_with_client(http_error(500))

        migrated = migrate_legacy_ledger_entries(args, path=self.path)

        self.assertEqual(migrated, 0)
        ref = load_handled_mail_state(self.path)["msg-1"]["events"][0]
        self.assertNotIn("migrated", ref)

    def test_a_gone_ref_creates_nothing_and_is_never_retried(self):
        """A 404/410 on migration's own events.get() must never create anything (no patch,
        certainly no insert - migrate_one_legacy_event never calls events().insert() at all)
        and must not be retried forever: the ref is marked migrated on this real pass so a
        future call skips it outright, matching the "confirmed gone" handling used elsewhere
        in this module (see docs/investigation-limite1.md - a 404 is data, not something to
        keep re-probing)."""
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "recorded_at": self._recent_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        args = self._args_with_client(http_error(404))

        migrated = migrate_legacy_ledger_entries(args, path=self.path)

        self.assertEqual(migrated, 0)
        client = args.calendar_api.getClient.return_value
        client.events.return_value.patch.assert_not_called()
        client.events.return_value.insert.assert_not_called()
        ref = load_handled_mail_state(self.path)["msg-1"]["events"][0]
        self.assertTrue(ref["migrated"])
        self.assertNotIn("event_end", ref)

        # A second real pass must not call events.get() again for this ref - it is settled.
        client.events.return_value.get.reset_mock()
        migrated_again = migrate_legacy_ledger_entries(args, path=self.path)
        self.assertEqual(migrated_again, 0)
        client.events.return_value.get.assert_not_called()

    def test_non_created_status_entries_are_skipped(self):
        self._write_state({"msg-1": {"events": [], "status": "no_event"}})
        args = self._args_with_client({"id": "e1"})

        migrated = migrate_legacy_ledger_entries(args, path=self.path)

        self.assertEqual(migrated, 0)
        args.calendar_api.getClient.return_value.events.return_value.get.assert_not_called()

    def test_existing_event_end_is_not_overwritten(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {
                            "calendar_id": "primary",
                            "event_id": "e1",
                            "recorded_at": self._recent_iso(),
                            "event_end": "2020-01-01T00:00:00Z",
                        }
                    ],
                    "status": "created",
                }
            }
        )
        existing = {"id": "e1", "end": {"dateTime": "2026-09-22T16:00:00-04:00"}}
        args = self._args_with_client(existing)

        migrate_legacy_ledger_entries(args, path=self.path)

        ref = load_handled_mail_state(self.path)["msg-1"]["events"][0]
        self.assertEqual(ref["event_end"], "2020-01-01T00:00:00Z")

    def test_dry_run_writes_nothing_to_the_ledger(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "recorded_at": self._recent_iso()}
                    ],
                    "status": "created",
                    "generation": 0,
                }
            }
        )
        before = self.path.read_text(encoding="utf-8")
        existing = {"id": "e1", "end": {"dateTime": "2026-09-22T16:00:00-04:00"}}
        args = self._args_with_client(existing)

        migrated = migrate_legacy_ledger_entries(args, path=self.path, dry_run=True)

        self.assertEqual(migrated, 1)  # reports what WOULD happen
        after = self.path.read_text(encoding="utf-8")
        self.assertEqual(before, after)  # but writes nothing at all
        ref = load_handled_mail_state(self.path)["msg-1"]["events"][0]
        self.assertNotIn("migrated", ref)
        self.assertNotIn("event_end", ref)
        args.calendar_api.getClient.return_value.events.return_value.patch.assert_not_called()

    def test_dry_run_does_not_prevent_a_later_real_run_from_migrating_the_same_ref(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "recorded_at": self._recent_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        existing = {"id": "e1", "end": {"dateTime": "2026-09-22T16:00:00-04:00"}}

        dry_args = self._args_with_client(existing)
        migrate_legacy_ledger_entries(dry_args, path=self.path, dry_run=True)

        real_args = self._args_with_client(existing)
        migrated = migrate_legacy_ledger_entries(real_args, path=self.path, dry_run=False)

        self.assertEqual(migrated, 1)
        ref = load_handled_mail_state(self.path)["msg-1"]["events"][0]
        self.assertTrue(ref["migrated"])

    def test_real_pass_backs_up_the_ledger_file_first(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "recorded_at": self._recent_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        original_content = self.path.read_text(encoding="utf-8")
        existing = {"id": "e1", "end": {"dateTime": "2026-09-22T16:00:00-04:00"}}
        args = self._args_with_client(existing)
        backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.addCleanup(lambda: backup_path.unlink(missing_ok=True))

        migrate_legacy_ledger_entries(args, path=self.path, dry_run=False)

        self.assertTrue(backup_path.is_file())
        self.assertEqual(backup_path.read_text(encoding="utf-8"), original_content)

    def test_dry_run_never_creates_a_backup(self):
        self._write_state(
            {
                "msg-1": {
                    "events": [
                        {"calendar_id": "primary", "event_id": "e1", "recorded_at": self._recent_iso()}
                    ],
                    "status": "created",
                }
            }
        )
        existing = {"id": "e1", "end": {"dateTime": "2026-09-22T16:00:00-04:00"}}
        args = self._args_with_client(existing)
        backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.addCleanup(lambda: backup_path.unlink(missing_ok=True))

        migrate_legacy_ledger_entries(args, path=self.path, dry_run=True)

        self.assertFalse(backup_path.is_file())


if __name__ == "__main__":
    unittest.main()
