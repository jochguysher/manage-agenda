import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock

from manage_agenda.sources import (
    Args,
    build_imap_from_search,
    mail_identity,
    parse_from_list,
    remember_handled_mail,
    unseen_messages,
    _get_emails_from_folder,
    _imap_rule_mode,
    _mark_imap_seen,
)


class TestImapSearch(unittest.TestCase):
    def test_empty_sender_list_matches_nothing(self):
        self.assertIsNone(build_imap_from_search([]))
        self.assertEqual(parse_from_list("  ,  "), [])

    def test_one_sender(self):
        self.assertEqual(
            build_imap_from_search(["@acme.example"]),
            '(HEADER FROM "@acme.example")',
        )

    def test_several_senders_are_or_combined(self):
        self.assertEqual(
            build_imap_from_search(["@a.example", "marie@b.example", "@c.example"]),
            '(OR HEADER FROM "@a.example" OR HEADER FROM "marie@b.example" HEADER FROM "@c.example")',
        )

    def test_quotes_are_removed_from_the_address(self):
        self.assertEqual(
            parse_from_list('a"b@example.com'),
            [{"name": None, "address": "ab@example.com"}],
        )

    def test_display_name_alone(self):
        rules = parse_from_list('name:"Jane Doe"')
        self.assertEqual(rules, [{"name": "Jane Doe", "address": None}])
        self.assertEqual(
            build_imap_from_search(rules),
            '(HEADER FROM "Jane Doe")',
        )

    def test_display_name_with_domain_or_address(self):
        combined = parse_from_list(
            'name:"Jane Doe" @outlook.com, '
            'name:"Jane Doe" jane.doe@example.org'
        )
        self.assertEqual(
            combined,
            [
                {"name": "Jane Doe", "address": "@outlook.com"},
                {
                    "name": "Jane Doe",
                    "address": "jane.doe@example.org",
                },
            ],
        )
        self.assertEqual(
            build_imap_from_search(combined),
            '(OR (HEADER FROM "Jane Doe" HEADER FROM "@outlook.com") '
            '(HEADER FROM "Jane Doe" HEADER FROM "jane.doe@example.org"))',
        )


class TestImapFolderRead(unittest.TestCase):
    def test_empty_rules_do_not_search(self):
        api = MagicMock()
        api.service = "imap"
        posts = _get_emails_from_folder(
            Args(),
            api,
            source_details={"channel": "INBOX", "from": ""},
        )
        self.assertIsNone(posts)
        api.getClient.assert_not_called()
        api.getLabels.assert_not_called()

    def test_search_uses_inbox_and_does_not_load_every_message(self):
        message = EmailMessage()
        message["Message-ID"] = "<one@acme.example>"
        message["Subject"] = "Rendez-vous"
        api = MagicMock()
        api.service = "imap"
        client = api.getClient.return_value
        client.select.return_value = ("OK", [b"1"])
        client.search.return_value = ("OK", [b"9"])

        def fetch(sequence, query):
            return ("OK", [(sequence.encode(), message.as_bytes())])

        client.fetch.side_effect = fetch

        posts = _get_emails_from_folder(
            Args(),
            api,
            source_details={"folder": "INBOX", "from": "@acme.example"},
        )

        client.select.assert_called_with("INBOX")
        client.search.assert_called_once_with(None, '(HEADER FROM "@acme.example")')
        api.getPosts.assert_not_called()
        api.setPosts.assert_not_called()
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][0], "9")

    def test_already_read_mail_is_still_fetched(self):
        """A \\Seen flag is not proof that an event was created."""
        seen = EmailMessage()
        seen["Message-ID"] = "<read@acme.example>"
        seen["Subject"] = "Deja lu"
        api = MagicMock()
        client = api.getClient.return_value
        client.select.return_value = ("OK", [b"1"])
        client.search.return_value = ("OK", [b"7"])
        client.fetch.side_effect = lambda sequence, query: (
            "OK",
            [(sequence.encode(), seen.as_bytes())],
        )

        posts = _get_emails_from_folder(
            Args(),
            api,
            source_details={"folder": "INBOX", "from": "@acme.example"},
        )

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1]["Message-ID"], "<read@acme.example>")

    def test_previously_handled_mail_is_not_fetched_again(self):
        done = EmailMessage()
        done["Message-ID"] = "<done@acme.example>"
        fresh = EmailMessage()
        fresh["Message-ID"] = "<fresh@acme.example>"
        bodies = {"1": done, "2": fresh}
        api = MagicMock()
        client = api.getClient.return_value
        client.select.return_value = ("OK", [b"1"])
        client.search.return_value = ("OK", [b"1 2"])

        def fetch(sequence, query):
            return ("OK", [(sequence.encode(), bodies[sequence].as_bytes())])

        client.fetch.side_effect = fetch
        from manage_agenda.sources import _fetch_imap_matches

        posts = _fetch_imap_matches(
            api,
            "INBOX",
            '(HEADER FROM "@acme.example")',
            handled={"done@acme.example"},
        )
        self.assertEqual([post[0] for post in posts], ["2"])
        body_calls = [
            call.args[0]
            for call in client.fetch.call_args_list
            if "BODY.PEEK[]" in call.args[1]
        ]
        self.assertEqual(body_calls, ["2"])

    def test_matches_are_returned_highest_sequence_number_first(self):
        """A safety invariant folder-mode marking depends on (see
        _imap_move_to_folder_safely): messages must be handed back highest-sequence-number
        first, and in order, so that expunging one (which only renumbers HIGHER-numbered
        messages) can never invalidate a not-yet-processed message's sequence number."""
        one = EmailMessage()
        one["Message-ID"] = "<one@acme.example>"
        two = EmailMessage()
        two["Message-ID"] = "<two@acme.example>"
        three = EmailMessage()
        three["Message-ID"] = "<three@acme.example>"
        bodies = {"1": one, "2": two, "3": three}
        api = MagicMock()
        client = api.getClient.return_value
        client.select.return_value = ("OK", [b"1"])
        client.search.return_value = ("OK", [b"1 2 3"])

        def fetch(sequence, query):
            return ("OK", [(sequence.encode(), bodies[sequence].as_bytes())])

        client.fetch.side_effect = fetch
        from manage_agenda.sources import _fetch_imap_matches

        posts = _fetch_imap_matches(api, "INBOX", "ALL")

        self.assertEqual([post[0] for post in posts], ["3", "2", "1"])

    def test_mark_seen_does_not_move_the_message(self):
        api = MagicMock()
        api.getClient.return_value.store.return_value = ("OK", [b""])
        self.assertTrue(_mark_imap_seen(api, "INBOX", "4"))
        api.getClient.return_value.select.assert_called_once_with("INBOX")
        api.getClient.return_value.store.assert_called_once_with("4", "+FLAGS", "\\Seen")
        api.deletePostId.assert_not_called()


class TestHandledMail(unittest.TestCase):
    def test_same_message_id_is_skipped_the_second_time(self):
        path = Path(self.id().replace(".", "_") + ".json")
        # Keep the ledger out of the home directory.
        path = Path("/tmp") / path.name
        first = EmailMessage()
        first["Message-ID"] = "<same@acme.example>"
        second = EmailMessage()
        second["Message-ID"] = "<same@acme.example>"
        other = EmailMessage()
        other["Message-ID"] = "<other@acme.example>"

        fresh, skipped = unseen_messages([(1, first), (2, second), (3, other)], handled=set(), path=path)
        self.assertEqual(skipped, 1)
        self.assertEqual([item[0] for item in fresh], [1, 3])

        remember_handled_mail(mail_identity((1, first)), path=path)
        fresh, skipped = unseen_messages([(1, first), (3, other)], path=path)
        self.assertEqual(skipped, 1)
        self.assertEqual([item[0] for item in fresh], [3])
        path.unlink(missing_ok=True)

    def test_rule_mode_defaults(self):
        self.assertEqual(_imap_rule_mode(Args(source="imap", interactive=False)), "auto")
        self.assertEqual(_imap_rule_mode(Args(source="imap", interactive=True)), "review")
        self.assertEqual(_imap_rule_mode(Args(source="imap", interactive=True, rule="auto")), "auto")
        self.assertIsNone(_imap_rule_mode(Args(source="web", interactive=True)))
