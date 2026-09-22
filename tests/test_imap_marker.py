import json
import unittest
from unittest.mock import MagicMock

from manage_agenda.sources import (
    ImapCapabilities,
    _combine_with_marker_exclusion,
    _imap_exclusion_criterion,
    _imap_marker_mode,
    _imap_move_to_folder_safely,
    _imap_since_bound,
    _imap_store_keyword,
    _imap_uid_for_sequence,
    _imap_unmark_folder_by_identity,
    _imap_unmark_keyword_by_identity,
    _looks_like_message_id,
    _requeue_pending_imap_messages,
    check_marker_mode_transition,
    forget_handled_mail,
    imap_marker_account_key,
    load_handled_mail_state,
    remember_handled_mail,
)


class TestImapCapabilitiesDetect(unittest.TestCase):
    def test_parses_uidplus_move_and_special_use(self):
        client = MagicMock()
        client.capability.return_value = ("OK", [b"IMAP4rev1 UIDPLUS MOVE SPECIAL-USE IDLE"])

        capabilities = ImapCapabilities.detect(client)

        self.assertTrue(capabilities.has_uidplus)
        self.assertTrue(capabilities.has_move)
        self.assertTrue(capabilities.has_special_use)
        self.assertIn("IDLE", capabilities.raw)

    def test_missing_extensions_are_false_not_assumed(self):
        client = MagicMock()
        client.capability.return_value = ("OK", [b"IMAP4rev1 IDLE"])

        capabilities = ImapCapabilities.detect(client)

        self.assertFalse(capabilities.has_uidplus)
        self.assertFalse(capabilities.has_move)
        self.assertFalse(capabilities.has_special_use)

    def test_failed_capability_call_yields_all_false_not_a_crash(self):
        client = MagicMock()
        client.capability.return_value = ("NO", None)

        capabilities = ImapCapabilities.detect(client)

        self.assertEqual(capabilities.raw, [])
        self.assertFalse(capabilities.has_uidplus)
        self.assertFalse(capabilities.has_move)


class TestImapMarkerMode(unittest.TestCase):
    def test_keyword_prefix(self):
        mode, value = _imap_marker_mode({"folder": "INBOX", "processed_marker": "keyword:$AgendaDone"})
        self.assertEqual((mode, value), ("keyword", "$AgendaDone"))

    def test_folder_prefix(self):
        mode, value = _imap_marker_mode({"folder": "INBOX", "processed_marker": "folder:Archive/Agenda"})
        self.assertEqual((mode, value), ("folder", "Archive/Agenda"))

    def test_flag_seen_explicit(self):
        mode, value = _imap_marker_mode({"folder": "INBOX", "processed_marker": "flag:seen"})
        self.assertEqual((mode, value), ("flag_seen", None))

    def test_mark_seen_backward_compat_with_no_explicit_processed_marker(self):
        """Pre-existing `mark: seen` accounts keep working identically, unconfigured for the
        new setting - see docs/investigation-limite1.md §6 migration."""
        mode, value = _imap_marker_mode({"folder": "INBOX", "mark": "seen"})
        self.assertEqual((mode, value), ("flag_seen", None))

    def test_unconfigured_is_none(self):
        self.assertEqual(_imap_marker_mode({"folder": "INBOX"}), (None, None))

    def test_marker_on_a_tag_based_account_is_ignored_and_warned(self):
        """No folder/channel/from means the tag-based scan path - there is no seam to add
        server-side exclusion to there, and a marker without it would grow the scanned set
        with the tool's whole history. Treated as a config mistake, not silently accepted."""
        with self.assertLogs(level="WARNING") as logs:
            mode, value = _imap_marker_mode({"processed_marker": "keyword:$AgendaDone"})
        self.assertEqual((mode, value), (None, None))
        self.assertTrue(any("processed_marker" in message for message in logs.output))


class TestImapExclusionCriterion(unittest.TestCase):
    def test_keyword_mode_adds_unkeyword(self):
        criterion = _imap_exclusion_criterion({"folder": "INBOX", "processed_marker": "keyword:$Done"})
        self.assertEqual(criterion, "UNKEYWORD $Done")

    def test_folder_mode_adds_undeleted_unconditionally(self):
        """Always UNDELETED for folder mode, not just when UIDPLUS is absent - simpler and
        still correct with UIDPLUS present (see docs/investigation-limite1.md §5)."""
        criterion = _imap_exclusion_criterion({"folder": "INBOX", "processed_marker": "folder:Archive"})
        self.assertEqual(criterion, "UNDELETED")

    def test_flag_seen_mode_adds_nothing(self):
        criterion = _imap_exclusion_criterion({"folder": "INBOX", "mark": "seen"})
        self.assertIsNone(criterion)

    def test_no_marker_adds_nothing(self):
        self.assertIsNone(_imap_exclusion_criterion({"folder": "INBOX"}))

    def test_combine_wraps_existing_criteria_with_an_and(self):
        combined = _combine_with_marker_exclusion(
            "HEADER FROM \"x\"", {"folder": "INBOX", "processed_marker": "keyword:$Done"}
        )
        self.assertEqual(combined, '(HEADER FROM "x" UNKEYWORD $Done)')

    def test_combine_with_no_existing_criteria(self):
        combined = _combine_with_marker_exclusion(
            None, {"folder": "INBOX", "processed_marker": "folder:Archive"}
        )
        self.assertEqual(combined, "(UNDELETED)")

    def test_combine_is_a_no_op_without_a_marker(self):
        combined = _combine_with_marker_exclusion('HEADER FROM "x"', {"folder": "INBOX"})
        self.assertEqual(combined, 'HEADER FROM "x"')


class TestImapStoreKeyword(unittest.TestCase):
    def test_stores_the_keyword_with_parens(self):
        client = MagicMock()
        client.store.return_value = ("OK", [b""])
        api_src = MagicMock()
        api_src.getClient.return_value = client

        result = _imap_store_keyword(api_src, "INBOX", "5", "$AgendaDone", add=True)

        self.assertTrue(result)
        client.select.assert_called_once_with("INBOX")
        client.store.assert_called_once_with("5", "+FLAGS", "($AgendaDone)")

    def test_removing_uses_minus_flags(self):
        client = MagicMock()
        client.store.return_value = ("OK", [b""])
        api_src = MagicMock()
        api_src.getClient.return_value = client

        _imap_store_keyword(api_src, "INBOX", "5", "$AgendaDone", add=False)

        client.store.assert_called_once_with("5", "-FLAGS", "($AgendaDone)")


class TestImapUidForSequence(unittest.TestCase):
    def test_parses_uid_out_of_the_fetch_response(self):
        client = MagicMock()
        client.fetch.return_value = ("OK", [b"1 (UID 4242)"])

        uid = _imap_uid_for_sequence(client, "1")

        self.assertEqual(uid, "4242")

    def test_returns_none_when_fetch_fails(self):
        client = MagicMock()
        client.fetch.return_value = ("NO", None)

        self.assertIsNone(_imap_uid_for_sequence(client, "1"))


def _client_with_uid(fetch_uid_response=b"1 (UID 777)"):
    client = MagicMock()
    client.select.return_value = ("OK", [b""])
    client.fetch.return_value = ("OK", [fetch_uid_response])
    client.create.return_value = ("OK", [b""])
    client.uid.return_value = ("OK", [b""])
    api_src = MagicMock()
    api_src.getClient.return_value = client
    return api_src, client


class TestImapMoveToFolderSafely(unittest.TestCase):
    """The never-bare-EXPUNGE rule is the one rule in this design whose violation destroys
    user data (a bare EXPUNGE purges every \\Deleted message in the folder, including ones a
    user deleted through their own client) - see docs/investigation-limite1.md §5."""

    def test_uses_uid_move_when_advertised(self):
        api_src, client = _client_with_uid()
        capabilities = ImapCapabilities(raw=["MOVE"], has_uidplus=False, has_move=True, has_special_use=False)

        result, locator = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        client.uid.assert_any_call("MOVE", "777", "Archive")
        self.assertFalse(any(call.args[0] == "EXPUNGE" for call in client.uid.call_args_list))
        client.expunge.assert_not_called()
        self.assertIsNone(locator, "no COPYUID in the response - nothing to record")

    def test_copy_then_uid_expunge_when_uidplus_present_and_no_move(self):
        api_src, client = _client_with_uid()
        capabilities = ImapCapabilities(
            raw=["UIDPLUS"], has_uidplus=True, has_move=False, has_special_use=False
        )

        result, locator = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        client.uid.assert_any_call("COPY", "777", "Archive")
        client.uid.assert_any_call("EXPUNGE", "777")
        client.expunge.assert_not_called()
        self.assertIsNone(locator)

    def test_never_a_bare_expunge_without_uidplus(self):
        """The critical assertion: without UIDPLUS, no EXPUNGE of any kind is issued - the
        original is left flagged \\Deleted and excluded from future scans by the UNDELETED
        search criterion instead (see _imap_exclusion_criterion)."""
        api_src, client = _client_with_uid()
        capabilities = ImapCapabilities(
            raw=[], has_uidplus=False, has_move=False, has_special_use=False
        )

        result, locator = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        client.uid.assert_any_call("COPY", "777", "Archive")
        client.uid.assert_any_call("STORE", "777", "+FLAGS", "(\\Deleted)")
        client.expunge.assert_not_called()
        self.assertFalse(
            any(call.args and call.args[0] == "EXPUNGE" for call in client.uid.call_args_list),
            "no UID EXPUNGE, and no bare EXPUNGE, without UIDPLUS",
        )
        self.assertIsNone(locator)

    def test_never_a_bare_expunge_with_no_capabilities_known(self):
        """capabilities=None (detection failed or was never run) must fail safe exactly like
        has_uidplus=False - never assume UIDPLUS is present."""
        api_src, client = _client_with_uid()

        result, locator = _imap_move_to_folder_safely(api_src, None, "INBOX", "1", "Archive")

        self.assertTrue(result)
        client.expunge.assert_not_called()
        self.assertFalse(any(call.args and call.args[0] == "EXPUNGE" for call in client.uid.call_args_list))
        self.assertIsNone(locator)

    def test_captures_the_copyuid_locator_when_the_server_provides_one(self):
        api_src, client = _client_with_uid()
        client.uid.return_value = ("OK", [b"OK [COPYUID 42 777 999] Completed"])
        capabilities = ImapCapabilities(
            raw=["MOVE", "UIDPLUS"], has_uidplus=True, has_move=True, has_special_use=False
        )

        result, locator = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        self.assertEqual(locator, {"folder": "Archive", "uidvalidity": "42", "uid": "999"})

    def _client_whose_move_answers_with_an_untagged_copyuid(self, before=None):
        """A server following RFC 6851: `* OK [COPYUID 42 777 999]` BEFORE the tagged OK,
        which imaplib keeps out of the command's data and files, brackets and name stripped,
        under untagged_responses["COPYUID"]. `before` seeds a stale code from an earlier
        command on the same connection (imaplib only flushes them on select())."""
        api_src, client = _client_with_uid()
        client.untagged_responses = {"COPYUID": [before]} if before else {}

        def uid(command, *args):
            if command == "MOVE":
                client.untagged_responses.setdefault("COPYUID", []).append(b"42 777 999")
                return "OK", [None]  # the tagged data carries no COPYUID
            return "OK", [b""]

        client.uid.side_effect = uid
        return api_src, client

    def test_captures_the_copyuid_a_move_sends_untagged_per_rfc_6851(self):
        api_src, client = self._client_whose_move_answers_with_an_untagged_copyuid()
        capabilities = ImapCapabilities(
            raw=["MOVE", "UIDPLUS"], has_uidplus=True, has_move=True, has_special_use=False
        )

        result, locator = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        self.assertEqual(locator, {"folder": "Archive", "uidvalidity": "42", "uid": "999"})
        # Consumed: the next command on this connection must not see this code again.
        self.assertNotIn("COPYUID", client.untagged_responses)

    def test_a_stale_untagged_copyuid_from_an_earlier_command_is_not_attributed_to_this_move(self):
        api_src, client = _client_with_uid()
        client.untagged_responses = {"COPYUID": [b"7 1 2"]}  # left over from an earlier COPY
        client.uid.return_value = ("OK", [None])  # this MOVE answers with no COPYUID at all
        capabilities = ImapCapabilities(
            raw=["MOVE", "UIDPLUS"], has_uidplus=True, has_move=True, has_special_use=False
        )

        result, locator = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        self.assertIsNone(locator)

    def test_the_untagged_copyuid_is_read_for_a_copy_too(self):
        api_src, client = _client_with_uid()
        client.untagged_responses = {}

        def uid(command, *args):
            if command == "COPY":
                client.untagged_responses["COPYUID"] = [b"42 777 999"]
                return "OK", [None]
            return "OK", [b""]

        client.uid.side_effect = uid
        capabilities = ImapCapabilities(raw=["UIDPLUS"], has_uidplus=True, has_move=False, has_special_use=False)

        result, locator = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        self.assertEqual(locator, {"folder": "Archive", "uidvalidity": "42", "uid": "999"})

    def test_reselects_source_folder_after_a_move(self):
        """The scan loop expects to still be working against source_folder afterward, not
        whatever this move last SELECTed."""
        api_src, client = _client_with_uid()
        capabilities = ImapCapabilities(raw=["MOVE"], has_uidplus=False, has_move=True, has_special_use=False)

        _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertEqual(client.select.call_args_list[0].args[0], "INBOX")
        self.assertEqual(client.select.call_args_list[-1].args[0], "INBOX")

    def test_returns_false_when_uid_lookup_fails(self):
        api_src, client = _client_with_uid()
        client.fetch.return_value = ("NO", None)
        capabilities = ImapCapabilities(raw=["MOVE"], has_uidplus=False, has_move=True, has_special_use=False)

        result, locator = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertFalse(result)
        self.assertIsNone(locator)
        client.uid.assert_not_called()


class TestLooksLikeMessageId(unittest.TestCase):
    def test_a_real_message_id_contains_at(self):
        self.assertTrue(_looks_like_message_id("abc123@mail.example.com"))

    def test_a_hash_fallback_does_not(self):
        self.assertFalse(_looks_like_message_id("a" * 32))


class TestImapSinceBound(unittest.TestCase):
    def test_bounds_by_recorded_at_minus_margin(self):
        since = _imap_since_bound("2026-06-15T00:00:00Z", margin_days=10)
        self.assertEqual(since, "SINCE 05-Jun-2026")

    def test_none_when_recorded_at_is_unavailable(self):
        self.assertIsNone(_imap_since_bound(None))


def _client_for_unmark(search_uids=b"55", uidvalidity=None):
    client = MagicMock()
    client.select.return_value = ("OK", [b""])
    client.uid.side_effect = None
    client.uid.return_value = ("OK", [search_uids] if search_uids is not None else [None])
    client.untagged_responses = {"UIDVALIDITY": [str(uidvalidity).encode()]} if uidvalidity else {}
    client.create.return_value = ("OK", [b""])
    api_src = MagicMock()
    api_src.getClient.return_value = client
    return api_src, client


class TestImapUnmarkKeywordByIdentity(unittest.TestCase):
    def test_finds_and_removes_the_keyword(self):
        api_src, client = _client_for_unmark(search_uids=b"55")

        def uid_side_effect(cmd, *args):
            if cmd == "SEARCH":
                return "OK", [b"55"]
            return "OK", [b""]

        client.uid.side_effect = uid_side_effect

        result = _imap_unmark_keyword_by_identity(
            api_src, "INBOX", "gone@example.com", "$AgendaDone", {"recorded_at": None}
        )

        self.assertTrue(result)
        client.uid.assert_any_call("SEARCH", None, 'HEADER Message-ID "gone@example.com"')
        client.uid.assert_any_call("STORE", "55", "-FLAGS", "($AgendaDone)")

    def test_hash_fallback_identity_cannot_be_searched_for(self):
        api_src, client = _client_for_unmark()

        result = _imap_unmark_keyword_by_identity(
            api_src, "INBOX", "a" * 32, "$AgendaDone", {"recorded_at": None}
        )

        self.assertFalse(result)
        client.uid.assert_not_called()

    def test_zero_matches_leaves_it_pending(self):
        api_src, client = _client_for_unmark()
        client.uid.return_value = ("OK", [b""])

        result = _imap_unmark_keyword_by_identity(
            api_src, "INBOX", "gone@example.com", "$AgendaDone", {"recorded_at": None}
        )

        self.assertFalse(result)

    def test_multiple_matches_leaves_it_pending_rather_than_guessing(self):
        api_src, client = _client_for_unmark()
        client.uid.return_value = ("OK", [b"55 56"])

        with self.assertLogs(level="WARNING"):
            result = _imap_unmark_keyword_by_identity(
                api_src, "INBOX", "gone@example.com", "$AgendaDone", {"recorded_at": None}
            )

        self.assertFalse(result)


class TestImapUnmarkFolderByIdentity(unittest.TestCase):
    def test_uses_the_stored_locator_when_uidvalidity_still_matches(self):
        api_src, client = _client_for_unmark(uidvalidity=42)
        client.uid.side_effect = lambda cmd, *args: ("OK", [b""])
        entry = {
            "recorded_at": None,
            "imap_locator": {"folder": "Archive", "uidvalidity": "42", "uid": "999"},
        }
        capabilities = ImapCapabilities(raw=["MOVE"], has_uidplus=False, has_move=True, has_special_use=False)

        result = _imap_unmark_folder_by_identity(
            api_src, capabilities, "INBOX", "Archive", "gone@example.com", entry
        )

        self.assertTrue(result)
        client.uid.assert_any_call("MOVE", "999", "INBOX")

    def test_falls_back_to_search_when_uidvalidity_has_changed(self):
        api_src, client = _client_for_unmark(uidvalidity=99)

        def uid_side_effect(cmd, *args):
            if cmd == "SEARCH":
                return "OK", [b"77"]
            return "OK", [b""]

        client.uid.side_effect = uid_side_effect
        entry = {
            "recorded_at": None,
            "imap_locator": {"folder": "Archive", "uidvalidity": "42", "uid": "999"},
        }
        capabilities = ImapCapabilities(raw=["MOVE"], has_uidplus=False, has_move=True, has_special_use=False)

        result = _imap_unmark_folder_by_identity(
            api_src, capabilities, "INBOX", "Archive", "gone@example.com", entry
        )

        self.assertTrue(result)
        client.uid.assert_any_call("SEARCH", None, 'HEADER Message-ID "gone@example.com"')
        client.uid.assert_any_call("MOVE", "77", "INBOX")

    def test_falls_back_to_search_when_no_locator_was_ever_recorded(self):
        api_src, client = _client_for_unmark()

        def uid_side_effect(cmd, *args):
            if cmd == "SEARCH":
                return "OK", [b"77"]
            return "OK", [b""]

        client.uid.side_effect = uid_side_effect
        entry = {"recorded_at": None}
        capabilities = ImapCapabilities(raw=["MOVE"], has_uidplus=False, has_move=True, has_special_use=False)

        result = _imap_unmark_folder_by_identity(
            api_src, capabilities, "INBOX", "Archive", "gone@example.com", entry
        )

        self.assertTrue(result)
        client.uid.assert_any_call("MOVE", "77", "INBOX")


class TestRequeuePendingImapMessages(unittest.TestCase):
    def setUp(self):
        from pathlib import Path

        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_successfully_unmarked_identity_is_forgotten(self):
        remember_handled_mail("gone@example.com", path=self.path)
        state = load_handled_mail_state(self.path)
        state["gone@example.com"]["status"] = "pending_requeue"
        from manage_agenda.sources import _save_state

        _save_state(self.path, state)
        handled_state = load_handled_mail_state(self.path)

        api_src, client = _client_for_unmark(search_uids=b"55")

        def uid_side_effect(cmd, *args):
            if cmd == "SEARCH":
                return "OK", [b"55"]
            return "OK", [b""]

        client.uid.side_effect = uid_side_effect

        _requeue_pending_imap_messages(
            api_src,
            {"folder": "INBOX"},
            True,
            "keyword",
            "$AgendaDone",
            None,
            handled_state,
            path=self.path,
        )

        self.assertNotIn("gone@example.com", load_handled_mail_state(self.path))

    def test_a_miss_leaves_the_entry_pending_for_another_account(self):
        remember_handled_mail("gone@example.com", path=self.path)
        state = load_handled_mail_state(self.path)
        state["gone@example.com"]["status"] = "pending_requeue"
        from manage_agenda.sources import _save_state

        _save_state(self.path, state)
        handled_state = load_handled_mail_state(self.path)

        api_src, client = _client_for_unmark()
        client.uid.return_value = ("OK", [b""])

        _requeue_pending_imap_messages(
            api_src, {"folder": "INBOX"}, True, "keyword", "$AgendaDone", None, handled_state, path=self.path
        )

        self.assertIn("gone@example.com", load_handled_mail_state(self.path))

    def test_flag_seen_mode_does_nothing_here_by_design(self):
        """No physical un-mark needed - reconcile already excludes the identity from
        still_handled, and flag_seen's exclusion is ledger-only."""
        remember_handled_mail("gone@example.com", path=self.path)
        state = load_handled_mail_state(self.path)
        state["gone@example.com"]["status"] = "pending_requeue"
        from manage_agenda.sources import _save_state

        _save_state(self.path, state)
        handled_state = load_handled_mail_state(self.path)

        api_src = MagicMock()

        _requeue_pending_imap_messages(
            api_src, {"folder": "INBOX"}, True, "flag_seen", None, None, handled_state, path=self.path
        )

        api_src.getClient.assert_not_called()
        self.assertIn("gone@example.com", load_handled_mail_state(self.path))


class TestForgetHandledMail(unittest.TestCase):
    def setUp(self):
        from pathlib import Path

        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_removes_the_identity(self):
        remember_handled_mail("msg-1", path=self.path)
        self.assertIn("msg-1", load_handled_mail_state(self.path))

        forget_handled_mail("msg-1", path=self.path)

        self.assertNotIn("msg-1", load_handled_mail_state(self.path))

    def test_is_a_no_op_for_an_unknown_identity(self):
        forget_handled_mail("never-there", path=self.path)  # must not raise
        self.assertEqual(load_handled_mail_state(self.path), {})


class TestRememberHandledMailImapLocator(unittest.TestCase):
    def setUp(self):
        from pathlib import Path

        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_locator_is_persisted_alongside_events(self):
        remember_handled_mail(
            "msg-1",
            path=self.path,
            events=[{"calendar_id": "primary", "event_id": "e1"}],
            imap_locator={"folder": "Archive", "uidvalidity": "42", "uid": "999"},
        )

        entry = load_handled_mail_state(self.path)["msg-1"]

        self.assertEqual(entry["imap_locator"], {"folder": "Archive", "uidvalidity": "42", "uid": "999"})
        self.assertEqual(entry["events"], [{"calendar_id": "primary", "event_id": "e1"}])

    def test_a_second_call_with_a_new_locator_and_no_events_still_persists_it(self):
        """The exact pitfall the docstring warns about: a locator passed in a call with no
        events, for an identity already recorded, must not be silently dropped by the
        "nothing changed" early return."""
        remember_handled_mail("msg-1", path=self.path)

        remember_handled_mail(
            "msg-1", path=self.path, imap_locator={"folder": "Archive", "uidvalidity": "1", "uid": "5"}
        )

        entry = load_handled_mail_state(self.path)["msg-1"]
        self.assertEqual(entry["imap_locator"], {"folder": "Archive", "uidvalidity": "1", "uid": "5"})


class TestImapMarkerAccountKey(unittest.TestCase):
    def test_uses_the_selected_source_name_when_given(self):
        self.assertEqual(imap_marker_account_key("mail-account", {"folder": "INBOX"}), "mail-account")

    def test_falls_back_to_folder_when_no_selected_source(self):
        self.assertEqual(imap_marker_account_key(None, {"folder": "INBOX"}), "folder:INBOX")

    def test_falls_back_to_channel_then_inbox(self):
        self.assertEqual(imap_marker_account_key(None, {"channel": "Archive"}), "folder:Archive")
        self.assertEqual(imap_marker_account_key(None, {}), "folder:INBOX")


class TestCheckMarkerModeTransition(unittest.TestCase):
    def setUp(self):
        from pathlib import Path

        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".json")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_first_time_seen_records_and_allows(self):
        allowed = check_marker_mode_transition("acct-1", "flag_seen", path=self.path)

        self.assertTrue(allowed)
        self.assertEqual(json.loads(self.path.read_text())["accounts"]["acct-1"], "flag_seen")

    def test_unchanged_mode_is_allowed(self):
        check_marker_mode_transition("acct-1", "flag_seen", path=self.path)

        allowed = check_marker_mode_transition("acct-1", "flag_seen", path=self.path)

        self.assertTrue(allowed)

    def test_flag_seen_to_keyword_is_refused(self):
        check_marker_mode_transition("acct-1", "flag_seen", path=self.path)

        allowed = check_marker_mode_transition("acct-1", "keyword", path=self.path)

        self.assertFalse(allowed)
        # Refusal must not silently record the new mode - a retry after the config is
        # reverted (or after a real migration) must see the same refusal, not a fait accompli.
        self.assertEqual(json.loads(self.path.read_text())["accounts"]["acct-1"], "flag_seen")

    def test_flag_seen_to_folder_is_refused(self):
        check_marker_mode_transition("acct-1", "flag_seen", path=self.path)

        allowed = check_marker_mode_transition("acct-1", "folder", path=self.path)

        self.assertFalse(allowed)

    def test_none_to_keyword_is_allowed(self):
        """Unconfigured (no marker at all, the _delete_email default) never shares flag_seen's
        "message never moves" property, so switching away from it is not blocked."""
        check_marker_mode_transition("acct-1", None, path=self.path)

        allowed = check_marker_mode_transition("acct-1", "keyword", path=self.path)

        self.assertTrue(allowed)

    def test_keyword_to_folder_is_allowed(self):
        check_marker_mode_transition("acct-1", "keyword", path=self.path)

        allowed = check_marker_mode_transition("acct-1", "folder", path=self.path)

        self.assertTrue(allowed)

    def test_different_accounts_are_tracked_independently(self):
        check_marker_mode_transition("acct-1", "flag_seen", path=self.path)

        allowed = check_marker_mode_transition("acct-2", "keyword", path=self.path)

        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
