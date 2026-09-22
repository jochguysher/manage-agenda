"""Tests for scripts/list_scan_window.py - loaded by path like scripts/diagnose_ledger.py."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from manage_agenda.scheduling import combine_imap_search, imap_age_criteria
from manage_agenda.sources import (
    IMAP_MATCH_LIMIT,
    _combine_with_marker_exclusion,
    build_imap_from_search,
    handled_mail_file,
    parse_from_list,
)

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "list_scan_window.py"
_spec = importlib.util.spec_from_file_location("list_scan_window", _SCRIPT_PATH)
list_scan_window = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(list_scan_window)

REVIEW_DETAILS = {
    "folder": "INBOX",
    "from": 'name:"Jane Doe"',
    "mark": "seen",
    "max_age_days": "5",
    "include_older": "no",
}

_MUTATING = ("store", "copy", "expunge", "append", "create", "delete", "rename", "subscribe")


def _header(message_id, subject="Visite", sender="Jane Doe <c@example.com>", date="Mon, 21 Sep 2026 10:00:00 -0400"):
    lines = []
    if message_id is not None:
        lines.append(f"Message-ID: <{message_id}>")
    lines += [f"From: {sender}", f"Date: {date}", f"Subject: {subject}", "", ""]
    return "\r\n".join(lines).encode()


def _client(messages, seen=()):
    """A fake imaplib client: `messages` maps sequence (str) -> header bytes; `seen` lists
    the sequences carrying \\Seen. SEARCH answers with every sequence, ascending."""
    client = MagicMock()
    client.select.return_value = ("OK", [b"3"])
    client.search.return_value = ("OK", [" ".join(sorted(messages, key=int)).encode()])

    def fetch(sequence, items):
        flags = b"\\Seen" if sequence in seen else b""
        return "OK", [(f"{sequence} (FLAGS ({flags.decode()}) BODY[HEADER.FIELDS (MESSAGE-ID FROM DATE SUBJECT)] {{0}}".encode(), messages[sequence]), b")"]

    client.fetch.side_effect = fetch
    return client


class TestScanCriteria:
    def test_is_exactly_what_get_emails_from_folder_builds(self):
        expected = _combine_with_marker_exclusion(
            combine_imap_search(
                build_imap_from_search(parse_from_list(REVIEW_DETAILS["from"])), imap_age_criteria(REVIEW_DETAILS)
            ),
            REVIEW_DETAILS,
        )
        assert list_scan_window.scan_criteria(REVIEW_DETAILS) == expected
        assert "SINCE" in expected and "Jane Doe" in expected

    def test_an_empty_sender_filter_means_no_criteria_like_the_scan(self):
        assert list_scan_window.scan_criteria({"folder": "INBOX", "from": "", "mark": "seen"}) is None


class TestRowsForAccount:
    def test_reads_only_selects_readonly_and_peeks(self):
        client = _client({"1": _header("a@x"), "2": _header("b@x")})

        rows = list_scan_window.rows_for_account(client, "acct", "INBOX", "(FROM x)", {})

        client.select.assert_called_once_with("INBOX", readonly=True)
        client.search.assert_called_once_with(None, "(FROM x)")
        assert all("PEEK" in call.args[1] for call in client.fetch.call_args_list)
        for name in _MUTATING:
            assert not getattr(client, name).called, name
        assert not any(call.args and call.args[0] in ("MOVE", "STORE", "EXPUNGE", "COPY") for call in client.uid.call_args_list)
        assert [row["sequence"] for row in rows] == ["2", "1"]  # newest first, as the scan

    def test_ledger_membership_seen_flag_and_hash_fallback(self):
        ledger = {"a@x": {"status": "created"}}
        client = _client({"1": _header("a@x"), "2": _header(None, subject="No id"), "3": _header("c@x")}, seen=("1", "2"))
        # The no-Message-ID message's identity is mail_identity()'s hash fallback.
        import email

        from manage_agenda.sources import mail_identity

        fallback = mail_identity(("2", email.message_from_bytes(_header(None, subject="No id"))))
        ledger[fallback] = {"status": "no_event"}

        rows = {row["sequence"]: row for row in list_scan_window.rows_for_account(client, "acct", "INBOX", "(FROM x)", ledger)}

        assert rows["1"]["in_ledger"] is True and rows["1"]["ledger_status"] == "created" and rows["1"]["seen"] is True
        assert rows["1"]["message_id"] == "a@x" and rows["1"]["from"].startswith("Jane Doe")
        assert rows["2"]["identity"] == fallback and rows["2"]["in_ledger"] is True and rows["2"]["message_id"] == ""
        assert rows["3"]["in_ledger"] is False and rows["3"]["seen"] is False and rows["3"]["would_process"] is True
        assert rows["1"]["would_process"] is False  # already in the ledger

    def test_would_process_caps_at_the_scan_match_limit_and_skips_ledger_hits(self):
        total = IMAP_MATCH_LIMIT + 5
        messages = {str(i): _header(f"m{i}@x") for i in range(1, total + 1)}
        ledger = {f"m{total}@x": {"status": "created"}}  # the newest one is already handled
        client = _client(messages)

        rows = list_scan_window.rows_for_account(client, "acct", "INBOX", "(FROM x)", ledger)

        assert sum(row["would_process"] for row in rows) == IMAP_MATCH_LIMIT
        assert rows[0]["sequence"] == str(total) and rows[0]["would_process"] is False
        assert all(row["in_scan_window"] for row in rows)

    def test_a_second_copy_of_the_same_message_id_is_not_counted_twice(self):
        """_fetch_imap_matches adds each identity to `known` as it goes, so a duplicate
        Message-ID inside one batch is skipped - the preview must count it the same way."""
        client = _client({"1": _header("same@x"), "2": _header("same@x"), "3": _header("other@x")})

        rows = list_scan_window.rows_for_account(client, "acct", "INBOX", "(FROM x)", {})

        assert [(row["sequence"], row["would_process"]) for row in rows] == [("3", True), ("2", True), ("1", False)]

    def test_beyond_the_scan_window_is_listed_but_never_processed(self):
        messages = {str(i): _header(f"m{i}@x") for i in range(1, 6)}
        client = _client(messages)

        rows = list_scan_window.rows_for_account(client, "acct", "INBOX", "(FROM x)", {}, scan_window=3, match_limit=10)

        assert [row["in_scan_window"] for row in rows] == [True, True, True, False, False]
        assert [row["would_process"] for row in rows] == [True, True, True, False, False]

    def test_no_criteria_means_no_search_at_all(self, capsys):
        client = _client({"1": _header("a@x")})

        assert list_scan_window.rows_for_account(client, "acme-auto", "INBOX", None, {}) == []

        client.select.assert_not_called()
        client.search.assert_not_called()
        assert "criteria: none" in capsys.readouterr().err


class TestMain:
    def _rules(self, accounts):
        rules = MagicMock()
        rules.more = dict(accounts)
        return rules

    def test_writes_the_csv_with_o_and_skips_the_label_scan_account(self, tmp_path, monkeypatch, capsys):
        review_src = ("imap", "set", "acme-review", "posts")
        gmail_src = ("gmail", "set", "me@example.com", "posts")
        client = _client({"1": _header("a@x")})
        api = MagicMock()
        api.getClient.return_value = client
        rules = self._rules(
            [
                (review_src, dict(REVIEW_DETAILS, section_name="acme-review")),
                (("imap", "set", "tagged", "posts"), {"section_name": "tagged", "mark": "seen"}),  # label path
                (gmail_src, {"service": "gmail", "section_name": "gmail"}),
            ]
        )
        rules.readConfigSrc.return_value = api
        monkeypatch.setattr("socialModules.moduleRules.moduleRules.from_config", classmethod(lambda cls: rules))
        ledger = handled_mail_file()
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps({"messages": {"a@x": {"events": [], "status": "created", "recorded_at": "2026-09-01T00:00:00Z"}}}), encoding="utf-8")
        before = ledger.read_bytes()
        report = tmp_path / "scan.csv"
        monkeypatch.setattr(sys, "argv", ["list_scan_window.py", "-o", str(report)])

        list_scan_window.main()

        lines = report.read_text(encoding="utf-8").splitlines()
        assert lines[0] == ",".join(list_scan_window.FIELDS)
        assert lines[1].startswith("acme-review,INBOX,1,") and ",a@x,True,created," in lines[1]
        assert rules.readConfigSrc.call_args.args[1] == review_src  # only the criteria account was connected
        client.logout.assert_called_once()
        assert ledger.read_bytes() == before
        captured = capsys.readouterr()
        assert "tagged: skipped - label scan" in captured.err
        assert "acme-review" not in captured.out and "identity" not in captured.out

    def test_account_filter_limits_the_run(self, monkeypatch, capsys):
        client = _client({"1": _header("a@x")})
        api = MagicMock()
        api.getClient.return_value = client
        rules = self._rules(
            [
                (("imap", "set", "acme-auto", "posts"), dict(REVIEW_DETAILS, section_name="acme-auto")),
                (("imap", "set", "acme-review", "posts"), dict(REVIEW_DETAILS, section_name="acme-review")),
            ]
        )
        rules.readConfigSrc.return_value = api
        monkeypatch.setattr("socialModules.moduleRules.moduleRules.from_config", classmethod(lambda cls: rules))
        monkeypatch.setattr(sys, "argv", ["list_scan_window.py", "--account", "acme-review"])

        list_scan_window.main()

        assert rules.readConfigSrc.call_count == 1
        assert rules.readConfigSrc.call_args.args[1] == ("imap", "set", "acme-review", "posts")
        assert "acme-review,INBOX,1," in capsys.readouterr().out


@pytest.mark.parametrize("value,expected", [("=?utf-8?q?Visite_propos=C3=A9e?=", "Visite proposée"), (None, ""), ("plain", "plain")])
def test_header_decoding(value, expected):
    assert list_scan_window._decode_header(value) == expected
