import datetime
import unittest
from pathlib import Path

from manage_agenda.scheduling import (
    Availability,
    availability_for,
    combine_imap_search,
    imap_age_criteria,
    message_age_limit_days,
    plan_room_visits,
    prompt_template_for,
    propose_visit,
)

TODAY = datetime.date(2026, 9, 21)


class TestMessageAge(unittest.TestCase):
    def test_max_age_excludes_older_mail(self):
        criteria = imap_age_criteria({"max_age_days": "30", "include_older": "no"}, today=TODAY)
        self.assertEqual(criteria, "SINCE 22-Aug-2026")

    def test_include_older_drops_the_automatic_limit(self):
        criteria = imap_age_criteria({"max_age_days": "30", "include_older": "yes"}, today=TODAY)
        self.assertEqual(criteria, "")

    def test_explicit_window(self):
        criteria = imap_age_criteria(
            {"since": "2026-09-01", "before": "2026-10-01", "include_older": "yes"},
            today=TODAY,
        )
        self.assertEqual(criteria, "SINCE 01-Sep-2026 BEFORE 01-Oct-2026")

    def test_age_limit_for_the_second_check(self):
        self.assertEqual(message_age_limit_days({}), 7)
        self.assertEqual(message_age_limit_days({"max_age_days": "30"}), 30)
        self.assertEqual(message_age_limit_days({"include_older": "yes"}), -1)

    def test_sender_search_keeps_the_date(self):
        combined = combine_imap_search('(HEADER FROM "Jane Doe")', "SINCE 22-Aug-2026")
        self.assertEqual(
            combined,
            '((HEADER FROM "Jane Doe") SINCE 22-Aug-2026)',
        )


class TestVisitBeforeOccupation(unittest.TestCase):
    def constraints(self):
        return Availability(
            days={1, 3},
            hours=[(datetime.time(10, 0), datetime.time(12, 0))],
            slot_minutes=60,
            timezone="America/Toronto",
            label="ACME",
        )

    def test_earliest_open_slot_before_the_next_occupation(self):
        choice = propose_visit(
            "Salle A",
            [datetime.date(2026, 9, 24)],
            self.constraints(),
            today=TODAY,
        )
        self.assertEqual(choice["start"].date(), datetime.date(2026, 9, 22))
        self.assertEqual(choice["start"].hour, 10)
        self.assertEqual(choice["before"], datetime.date(2026, 9, 24))

    def test_busy_slot_is_skipped(self):
        import pytz

        zone = pytz.timezone("America/Toronto")
        busy = [
            (
                zone.localize(datetime.datetime(2026, 9, 22, 10, 0)),
                zone.localize(datetime.datetime(2026, 9, 22, 11, 0)),
            )
        ]
        choice = propose_visit(
            "Salle A",
            [datetime.date(2026, 9, 24)],
            self.constraints(),
            busy=busy,
            today=TODAY,
        )
        self.assertEqual(choice["start"].hour, 11)

    def test_no_slot_when_the_room_is_occupied_first(self):
        choice = propose_visit(
            "Salle A",
            [datetime.date(2026, 9, 22)],
            self.constraints(),
            today=TODAY,
        )
        self.assertIsNone(choice)

    def test_plan_builds_a_calendar_event(self):
        visits = plan_room_visits(
            {"kind": "room_occupancy", "rooms": [{"room": "Salle A", "occupied": ["2026-09-24"]}]},
            self.constraints(),
            today=TODAY,
            sender="Jane Doe",
        )
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0]["summary"], "ACME - Salle A")
        self.assertNotIn("Christine", visits[0]["summary"])
        self.assertNotIn("@", visits[0]["summary"])
        self.assertEqual(visits[0]["start"]["dateTime"][:10], "2026-09-22")
        self.assertNotEqual(visits[0]["start"]["dateTime"][:10], "2026-09-24")
        self.assertIn("2026-09-24", visits[0]["description"])

    def test_different_rooms_get_different_times(self):
        visits = plan_room_visits(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {"room": "Salle 1", "occupied": ["2026-09-26"]},
                    {"room": "Salle 2", "occupied": ["2026-09-26"]},
                ],
            },
            self.constraints(),
            today=TODAY,
            sender="Jane Doe <jane.doe@example.org>",
        )
        self.assertEqual(len(visits), 2)
        self.assertEqual(visits[0]["summary"], "ACME - Salle 1")
        self.assertEqual(visits[1]["summary"], "ACME - Salle 2")
        self.assertNotEqual(visits[0]["start"]["dateTime"], visits[1]["start"]["dateTime"])
        self.assertNotIn("Christine", visits[0]["summary"])
        self.assertTrue(all(visit["start"]["dateTime"][:10] != "2026-09-26" for visit in visits))

    def test_dates_copied_by_the_model_become_occupations(self):
        from manage_agenda.scheduling import as_occupancy

        payload = as_occupancy(
            [
                {
                    "summary": "Jane Doe — Location",
                    "location": "Salle 4",
                    "start": {"dateTime": "2026-09-26 08:00:00"},
                    "end": {"dateTime": "2026-09-26 12:30:00"},
                },
                {
                    "summary": "Nettoyage Salle 4",
                    "start": {"dateTime": "2026-09-26 08:00:00"},
                    "end": {"dateTime": "2026-09-26 12:30:00"},
                },
            ]
        )
        visits = plan_room_visits(payload, self.constraints(), today=TODAY)
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0]["summary"], "ACME - Salle 4")
        self.assertNotEqual(visits[0]["start"]["dateTime"][:10], "2026-09-26")


class TestSenderPrompt(unittest.TestCase):
    def test_specific_prompt_beats_the_generic_one(self):
        directory = Path("/tmp/manage-agenda-prompts-test")
        prompt_dir = directory / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / "christine.txt").write_text("PROMPT SALLES {content_text}", encoding="utf-8")
        (directory / "prompts.ini").write_text(
            '[christine]\nmatch = name:"Jane Doe"\nprompt = christine.txt\n'
            "availability = christine\n",
            encoding="utf-8",
        )
        (directory / "availability.ini").write_text(
            "[christine]\ndays = tue,thu\nhours = 10:00-12:00\nslot_minutes = 60\n"
            "timezone = America/Toronto\n",
            encoding="utf-8",
        )
        header = "Jane Doe <outlook_3CCC9EB0579E28EF@outlook.com>"
        self.assertIn("PROMPT SALLES", prompt_template_for(header, directory))
        self.assertIsNone(prompt_template_for("autre@example.com", directory))
        constraints = availability_for(header, directory)
        self.assertEqual(constraints.days, {1, 3})
        self.assertEqual(constraints.hours, [(datetime.time(10, 0), datetime.time(12, 0))])
