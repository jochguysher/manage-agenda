import datetime
import unittest
from pathlib import Path

import pytz

from manage_agenda.scheduling import (
    Availability,
    availability_for,
    combine_imap_search,
    imap_age_criteria,
    message_age_limit_days,
    plan_cleanings,
    prompt_template_for,
    room_occupations,
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

    def _plan_one(self, start, end, deadline=None, busy=None, today=TODAY, room="Salle A"):
        occupation = {"start": start, "end": end, "clean": True}
        if deadline:
            occupation["clean_before"] = deadline
        payload = {"kind": "room_occupancy", "rooms": [{"room": room, "occupations": [occupation]}]}
        return plan_cleanings(payload, self.constraints(), busy=busy, today=today)

    def test_first_open_slot_after_the_occupation_ends(self):
        # Occupied Thursday the 24th until 21:30; the constraints allow Tuesdays and Thursdays
        # 10-12: the cleaning lands on the next allowed day, Tuesday the 29th at 10:00.
        events = self._plan_one("2026-09-24T08:00", "2026-09-24T21:30")
        self.assertEqual(events[0]["start"]["dateTime"], "2026-09-29 10:00:00")
        self.assertNotIn("hors des jours", events[0]["description"])

    def test_a_slot_the_same_day_must_start_after_the_end(self):
        # Occupied Tuesday the 22nd until 10:30: the 10:00 slot is gone, 11:00 fits.
        events = self._plan_one("2026-09-22T08:00", "2026-09-22T10:30")
        self.assertEqual(events[0]["start"]["dateTime"], "2026-09-22 11:00:00")

    def test_an_occupation_already_over_is_cleaned_from_tomorrow(self):
        events = self._plan_one("2026-09-15T08:00", "2026-09-15T12:00")
        self.assertEqual(events[0]["start"]["dateTime"][:10], "2026-09-22")

    def test_busy_slot_is_skipped(self):
        zone = pytz.timezone("America/Toronto")
        busy = [(zone.localize(datetime.datetime(2026, 9, 29, 10, 0)), zone.localize(datetime.datetime(2026, 9, 29, 11, 0)))]
        events = self._plan_one("2026-09-24T08:00", "2026-09-24T21:30", busy=busy)
        self.assertEqual(events[0]["start"]["dateTime"], "2026-09-29 11:00:00")

    def test_a_deadline_forces_a_slot_outside_the_configured_hours(self):
        # "Samedi 30 mai, salle 1, location de 14 h à 2 h du matin. SVP nettoyer avant le dimanche
        # 31 mai 8 h": no Tuesday/Thursday slot fits, so the last hour before the deadline is
        # proposed anyway, and said to be forced.
        events = self._plan_one("2026-05-30T14:00", "2026-05-31T02:00", deadline="2026-05-31T08:00", today=datetime.date(2026, 5, 28), room="Salle 1")
        self.assertEqual((events[0]["start"]["dateTime"], events[0]["end"]["dateTime"]), ("2026-05-31 07:00:00", "2026-05-31 08:00:00"))
        self.assertIn("hors des jours et heures configurés", events[0]["description"])

    def test_a_deadline_that_leaves_room_keeps_the_earliest_configured_slot(self):
        # A deadline lets a cleaning wait for company, it does not make it wait alone.
        events = self._plan_one("2026-09-24T08:00", "2026-09-24T21:30", deadline="2026-10-08T12:00", room="Salle 1")
        self.assertEqual(events[0]["start"]["dateTime"], "2026-09-29 10:00:00")
        self.assertNotIn("hors des jours", events[0]["description"])

    def test_nothing_when_the_deadline_is_already_past_the_occupation(self):
        self.assertEqual(self._plan_one("2026-09-24T08:00", "2026-09-24T21:30", deadline="2026-09-24T20:00", room="Salle 1"), [])

    def test_a_deadline_lets_a_cleaning_join_a_later_trip(self):
        # Monday's room may wait until Thursday afternoon; Wednesday's room is cleaned on
        # Thursday: one trip on Thursday, Monday's room first.
        events = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {"room": "Salle 1", "occupations": [{"start": "2026-09-21T08:00", "end": "2026-09-21T12:00", "clean": True, "clean_before": "2026-09-24T14:00"}]},
                    {"room": "Salle 2", "occupations": [{"start": "2026-09-23T08:00", "end": "2026-09-23T12:00", "clean": True}]},
                ],
            },
            self.constraints(),
            today=TODAY,
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["summary"], "ACME - Salle 1, 2")
        self.assertEqual((events[0]["start"]["dateTime"], events[0]["end"]["dateTime"]), ("2026-09-24 10:00:00", "2026-09-24 12:00:00"))
        self.assertTrue(events[0]["description"].index("Salle 1") < events[0]["description"].index("Salle 2"))
        self.assertIn("en un seul passage dans cet ordre", events[0]["description"])

    def test_a_short_deadline_keeps_the_trips_apart(self):
        # Monday's room must be done before Tuesday afternoon: Tuesday for it, Thursday for
        # Wednesday's room.
        events = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {"room": "Salle 1", "occupations": [{"start": "2026-09-21T08:00", "end": "2026-09-21T12:00", "clean": True, "clean_before": "2026-09-22T14:00"}]},
                    {"room": "Salle 2", "occupations": [{"start": "2026-09-23T08:00", "end": "2026-09-23T12:00", "clean": True}]},
                ],
            },
            self.constraints(),
            today=TODAY,
        )
        self.assertEqual([(e["summary"], e["start"]["dateTime"]) for e in events], [("ACME - Salle 1", "2026-09-22 10:00:00"), ("ACME - Salle 2", "2026-09-24 10:00:00")])

    def test_without_a_deadline_a_cleaning_does_not_wait_for_company(self):
        events = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {"room": "Salle 1", "occupations": [{"start": "2026-09-21T08:00", "end": "2026-09-21T12:00", "clean": True}]},
                    {"room": "Salle 2", "occupations": [{"start": "2026-09-23T08:00", "end": "2026-09-23T12:00", "clean": True}]},
                ],
            },
            self.constraints(),
            today=TODAY,
        )
        self.assertEqual([e["start"]["dateTime"][:10] for e in events], ["2026-09-22", "2026-09-24"])

    def test_plan_builds_a_calendar_event_with_the_occupation_it_answers(self):
        cleanings = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {
                        "room": "Salle A",
                        "occupations": [{"start": "2026-09-24T08:00", "end": "2026-09-24T21:30", "clean": True}],
                    }
                ],
            },
            self.constraints(),
            today=TODAY,
            sender="Jane Doe",
        )
        self.assertEqual(len(cleanings), 1)
        self.assertEqual(cleanings[0]["summary"], "ACME - Salle A")
        self.assertNotIn("@", cleanings[0]["summary"])
        self.assertEqual(cleanings[0]["start"]["dateTime"], "2026-09-29 10:00:00")
        self.assertIn("après l'occupation de Salle A le 2026-09-24 de 08:00 à 21:30", cleanings[0]["description"])
        self.assertEqual(
            cleanings[0]["extendedProperties"]["private"],
            {"kind": "cleaning", "room": "Salle A", "occupied_from": "2026-09-24 08:00", "occupied_to": "2026-09-24 21:30"},
        )

    def test_lines_without_an_instruction_or_saying_not_to_clean_give_nothing(self):
        # The church, cleaned monthly under its own contract, never gets a cleaning from
        # these messages; "ne pas nettoyer" neither.
        cleanings = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {"room": "Église", "occupations": [{"start": "2026-09-27T10:00", "end": "2026-09-27T11:30"}]},
                    {"room": "Église", "occupations": [{"start": "2026-09-27T13:30", "end": "2026-09-27T15:30", "clean": False}]},
                    {"room": "salle 1 et 2", "occupations": [{"start": "2026-09-27T08:00", "end": "2026-09-28T00:00", "clean": False}]},
                ],
            },
            self.constraints(),
            today=TODAY,
        )
        self.assertEqual(cleanings, [])

    def test_the_users_message(self):
        # "Dimanche 27 septembre, salle 1 et 2, location de 8 h à minuit, ne pas nettoyer les salles.
        # Lundi 28 septembre, salle 1 et 2, location minuit à 21 h 30, SVP nettoyer les salles."
        cleanings = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {
                        "room": "salle 1 et 2",
                        "occupations": [
                            {"start": "2026-09-27T08:00", "end": "2026-09-28T00:00", "clean": False},
                            {"start": "2026-09-28T00:00", "end": "2026-09-28T21:30", "clean": True},
                        ],
                    }
                ],
            },
            self.constraints(),
            today=datetime.date(2026, 9, 24),
        )
        self.assertEqual([c["start"]["dateTime"] for c in cleanings], ["2026-09-29 10:00:00"])
        self.assertIn("le 2026-09-28 de 00:00 à 21:30", cleanings[0]["description"])

    def test_a_deadline_is_kept_on_the_event(self):
        cleanings = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {
                        "room": "Salle 1",
                        "occupations": [
                            {"start": "2026-05-30T14:00", "end": "2026-05-31T02:00", "clean": True, "clean_before": "2026-05-31T08:00"}
                        ],
                    }
                ],
            },
            self.constraints(),
            today=datetime.date(2026, 5, 28),
        )
        self.assertEqual(cleanings[0]["start"]["dateTime"], "2026-05-31 07:00:00")
        self.assertEqual(cleanings[0]["extendedProperties"]["private"]["clean_before"], "2026-05-31 08:00")
        self.assertIn("à faire avant le 2026-05-31 08:00", cleanings[0]["description"])
        self.assertIn("hors des jours et heures configurés", cleanings[0]["description"])

    def test_an_end_before_its_start_is_the_next_day(self):
        occupations = room_occupations(
            {"occupations": [{"start": "2026-05-30T14:00", "end": "2026-05-30T02:00", "clean": "oui"}]},
            self.constraints(),
        )
        self.assertEqual(occupations[0]["end"].date(), datetime.date(2026, 5, 31))
        self.assertTrue(occupations[0]["clean"])
        whole = room_occupations({"occupations": [{"start": "2026-09-27", "end": "2026-10-03", "clean": True}]}, self.constraints())
        self.assertEqual((whole[0]["start"].strftime("%Y-%m-%d %H:%M"), whole[0]["end"].strftime("%Y-%m-%d %H:%M")), ("2026-09-27 00:00", "2026-10-04 00:00"))

    def test_a_cleaning_overtaken_by_the_next_occupation_is_dropped(self):
        # Saturday and Sunday both ask for a cleaning, nothing fits between them: one cleaning,
        # after the second occupation.
        cleanings = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {
                        "room": "Salle 1",
                        "occupations": [
                            {"start": "2026-09-26T14:00", "end": "2026-09-26T23:00", "clean": True},
                            {"start": "2026-09-27T09:00", "end": "2026-09-27T17:00", "clean": True},
                        ],
                    }
                ],
            },
            self.constraints(),
            today=datetime.date(2026, 9, 24),
        )
        self.assertEqual(len(cleanings), 1)
        self.assertIn("le 2026-09-27 de 09:00 à 17:00", cleanings[0]["description"])

    def test_adjacent_cleanings_of_two_rooms_make_one_event(self):
        # "Samedi 3 octobre : salle 4, location de 8 h à 10 h 30, SVP nettoyer ; salle 1,
        # location de 11 h à 18 h, SVP nettoyer": both land on the next allowed day, one after
        # the other, so the calendar gets one event naming both rooms over the whole slot.
        cleanings = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {"room": "Salle 4", "occupations": [{"start": "2026-10-03T08:00", "end": "2026-10-03T10:30", "clean": True}]},
                    {"room": "Salle 1", "occupations": [{"start": "2026-10-03T11:00", "end": "2026-10-03T18:00", "clean": True}]},
                ],
            },
            self.constraints(),
            today=datetime.date(2026, 9, 24),
            sender="Jane Doe <jane.doe@example.org>",
        )
        self.assertEqual(len(cleanings), 1)
        self.assertEqual(cleanings[0]["summary"], "ACME - Salle 4, 1")
        self.assertEqual(cleanings[0]["location"], "Salle 4, Salle 1")
        self.assertEqual((cleanings[0]["start"]["dateTime"], cleanings[0]["end"]["dateTime"]), ("2026-10-06 10:00:00", "2026-10-06 12:00:00"))
        self.assertIn("Salle 4 le 2026-10-03 de 08:00 à 10:30 ; Salle 1 le 2026-10-03 de 11:00 à 18:00", cleanings[0]["description"])
        self.assertIn("en un seul passage dans cet ordre", cleanings[0]["description"])
        private = cleanings[0]["extendedProperties"]["private"]
        self.assertEqual((private["room"], private["occupied_from"], private["occupied_to"]), ("Salle 4, Salle 1", "2026-10-03 08:00", "2026-10-03 18:00"))

    def test_cleanings_on_different_days_stay_separate(self):
        cleanings = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {"room": "Salle 1", "occupations": [{"start": "2026-09-22T08:00", "end": "2026-09-22T10:30", "clean": True}]},
                    {"room": "Salle 2", "occupations": [{"start": "2026-09-24T08:00", "end": "2026-09-24T12:00", "clean": True}]},
                ],
            },
            self.constraints(),
            today=TODAY,
        )
        self.assertEqual([c["summary"] for c in cleanings], ["ACME - Salle 1", "ACME - Salle 2"])
        self.assertEqual([c["start"]["dateTime"][:10] for c in cleanings], ["2026-09-22", "2026-09-29"])

    def test_a_deadline_the_merged_slot_would_pass_keeps_the_events_apart(self):
        # Salle 1 must be done before 11:00 on the 29th; merging it with Salle 2's 11:00-12:00
        # slot would carry the event past that limit, so they stay two events.
        cleanings = plan_cleanings(
            {
                "kind": "room_occupancy",
                "rooms": [
                    {"room": "Salle 1", "occupations": [{"start": "2026-09-24T08:00", "end": "2026-09-24T21:30", "clean": True, "clean_before": "2026-09-29T11:00"}]},
                    {"room": "Salle 2", "occupations": [{"start": "2026-09-24T08:00", "end": "2026-09-24T21:30", "clean": True}]},
                ],
            },
            self.constraints(),
            today=TODAY,
        )
        self.assertEqual([c["summary"] for c in cleanings], ["ACME - Salle 1", "ACME - Salle 2"])
        self.assertEqual([c["start"]["dateTime"] for c in cleanings], ["2026-09-29 10:00:00", "2026-09-29 11:00:00"])
        self.assertEqual(cleanings[0]["extendedProperties"]["private"]["clean_before"], "2026-09-29 11:00")

    def test_legacy_days_count_as_whole_days_to_clean_after(self):
        cleanings = plan_cleanings(
            {"kind": "room_occupancy", "rooms": [{"room": "Salle A", "occupied": ["2026-09-24"]}]},
            self.constraints(),
            today=TODAY,
        )
        self.assertEqual(cleanings[0]["start"]["dateTime"][:10], "2026-09-29")
        self.assertIn("le 2026-09-24", cleanings[0]["description"])

    def test_dates_copied_by_the_model_become_occupations(self):
        from manage_agenda.scheduling import as_occupancy

        payload = as_occupancy(
            [
                {"summary": "Jane Doe — Location", "location": "Salle 4", "start": {"dateTime": "2026-09-26 08:00:00"}, "end": {"dateTime": "2026-09-26 12:30:00"}},
                {"summary": "Nettoyage Salle 4", "start": {"dateTime": "2026-09-26 08:00:00"}, "end": {"dateTime": "2026-09-26 12:30:00"}},
            ]
        )
        cleanings = plan_cleanings(payload, self.constraints(), today=TODAY)
        self.assertEqual(len(cleanings), 1)
        self.assertEqual(cleanings[0]["summary"], "ACME - Salle 4")
        self.assertEqual(cleanings[0]["start"]["dateTime"][:10], "2026-09-29")


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


class TestOccupationRanges(unittest.TestCase):
    """A week announced as one period counts for each of its days, whatever the model wrote
    (legacy `occupied` lists)."""

    def constraints(self):
        return Availability(days={0, 1, 2, 3, 4}, hours=[(datetime.time(9, 0), datetime.time(16, 0))], label="NDU")

    def test_ranges_expand_to_every_day(self):
        from manage_agenda.scheduling import _occupied_dates

        week = [datetime.date(2026, 9, 27) + datetime.timedelta(days=i) for i in range(7)]
        for value in ("2026-09-27/2026-10-03", "2026-09-27..2026-10-03", "2026-09-27 - 2026-10-03", "2026-09-27 au 2026-10-03", {"from": "2026-09-27", "to": "2026-10-03"}):
            self.assertEqual(_occupied_dates({"occupied": [value]}), week, value)
        self.assertEqual(_occupied_dates({"occupied": ["2026-09-27", "junk", "2026-10-03T08:00"]}), [datetime.date(2026, 9, 27), datetime.date(2026, 10, 3)])
        self.assertEqual(_occupied_dates({"occupied": ["2026-10-03/2026-09-27"]}), [datetime.date(2026, 10, 3)])

    def test_the_week_of_the_27th_is_cleaned_on_monday_the_5th(self):
        # "Entretien ménager semaine du 27 septembre au 3 octobre 2026", scanned on the 24th,
        # availability Monday to Friday: the cleaning follows the week.
        for payload in (
            {"kind": "room_occupancy", "rooms": [{"room": "salle 1 et 2", "occupied": ["2026-09-27/2026-10-03"]}]},
            {"kind": "room_occupancy", "rooms": [{"room": "salle 1 et 2", "occupations": [{"start": "2026-09-27", "end": "2026-10-03", "clean": True}]}]},
        ):
            cleanings = plan_cleanings(payload, self.constraints(), today=datetime.date(2026, 9, 24))
            self.assertEqual(len(cleanings), 1)
            self.assertEqual(cleanings[0]["start"]["dateTime"], "2026-10-05 09:00:00")
            self.assertIn("du 2026-09-27 au 2026-10-03", cleanings[0]["description"])
            self.assertEqual(cleanings[0]["extendedProperties"]["private"]["occupied_to"], "2026-10-04 00:00")

    def test_a_week_long_event_copied_by_the_model_is_a_week_of_occupation(self):
        from manage_agenda.scheduling import as_occupancy

        payload = as_occupancy([{"summary": "Entretien ménager", "location": "Salle 1", "start": {"date": "2026-09-27"}, "end": {"date": "2026-10-03"}}])
        self.assertEqual(payload["rooms"], [{"room": "Salle 1", "occupied": [f"2026-09-{d}" for d in range(27, 31)] + ["2026-10-01", "2026-10-02", "2026-10-03"]}])
