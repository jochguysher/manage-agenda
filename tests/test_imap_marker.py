import unittest
from unittest.mock import MagicMock

from manage_agenda.sources import (
    ImapCapabilities,
    _combine_with_marker_exclusion,
    _imap_exclusion_criterion,
    _imap_marker_mode,
    _imap_move_to_folder_safely,
    _imap_store_keyword,
    _imap_uid_for_sequence,
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

        result = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        client.uid.assert_any_call("MOVE", "777", "Archive")
        self.assertFalse(any(call.args[0] == "EXPUNGE" for call in client.uid.call_args_list))
        client.expunge.assert_not_called()

    def test_copy_then_uid_expunge_when_uidplus_present_and_no_move(self):
        api_src, client = _client_with_uid()
        capabilities = ImapCapabilities(
            raw=["UIDPLUS"], has_uidplus=True, has_move=False, has_special_use=False
        )

        result = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        client.uid.assert_any_call("COPY", "777", "Archive")
        client.uid.assert_any_call("EXPUNGE", "777")
        client.expunge.assert_not_called()

    def test_never_a_bare_expunge_without_uidplus(self):
        """The critical assertion: without UIDPLUS, no EXPUNGE of any kind is issued - the
        original is left flagged \\Deleted and excluded from future scans by the UNDELETED
        search criterion instead (see _imap_exclusion_criterion)."""
        api_src, client = _client_with_uid()
        capabilities = ImapCapabilities(
            raw=[], has_uidplus=False, has_move=False, has_special_use=False
        )

        result = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertTrue(result)
        client.uid.assert_any_call("COPY", "777", "Archive")
        client.uid.assert_any_call("STORE", "777", "+FLAGS", "(\\Deleted)")
        client.expunge.assert_not_called()
        self.assertFalse(
            any(call.args and call.args[0] == "EXPUNGE" for call in client.uid.call_args_list),
            "no UID EXPUNGE, and no bare EXPUNGE, without UIDPLUS",
        )

    def test_never_a_bare_expunge_with_no_capabilities_known(self):
        """capabilities=None (detection failed or was never run) must fail safe exactly like
        has_uidplus=False - never assume UIDPLUS is present."""
        api_src, client = _client_with_uid()

        result = _imap_move_to_folder_safely(api_src, None, "INBOX", "1", "Archive")

        self.assertTrue(result)
        client.expunge.assert_not_called()
        self.assertFalse(any(call.args and call.args[0] == "EXPUNGE" for call in client.uid.call_args_list))

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

        result = _imap_move_to_folder_safely(api_src, capabilities, "INBOX", "1", "Archive")

        self.assertFalse(result)
        client.uid.assert_not_called()


if __name__ == "__main__":
    unittest.main()
