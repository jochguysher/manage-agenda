"""ConsoleUI reproduces the terminal prompts the library used to make inline: same input()
calls, same parsing of the answers. Every test patches builtins.input, as the tests of the
old inline code did."""

import datetime
import unittest
from unittest.mock import MagicMock, patch

from manage_agenda.events import _parse_event_times
from manage_agenda.ui.console import ConsoleUI


class TestSimplePrompts(unittest.TestCase):
    def setUp(self):
        self.ui = ConsoleUI()

    def test_confirm_is_y_or_nothing(self):
        for answer, expected in [("y", True), ("Y", True), ("yes", False), ("n", False), ("", False)]:
            with patch("builtins.input", return_value=answer) as mock_input:
                self.assertEqual(self.ui.confirm("Sure? "), expected, answer)
            mock_input.assert_called_once_with("Sure? ")

    def test_ask_text_returns_the_raw_line(self):
        with patch("builtins.input", return_value="  a b  "):
            self.assertEqual(self.ui.ask_text("Files: "), "  a b  ")

    def test_choose_action_returns_the_raw_line(self):
        with patch("builtins.input", return_value="R") as mock_input:
            self.assertEqual(self.ui.choose_action([("r", "Retry")], "(r)etry? "), "R")
        mock_input.assert_called_once_with("(r)etry? ")

    def test_ask_multiline_reads_until_eof(self):
        with patch("builtins.input", side_effect=["line 1", "line 2", EOFError()]), patch(
            "builtins.print"
        ) as mock_print:
            self.assertEqual(self.ui.ask_multiline("Paste:"), "line 1\nline 2")
        mock_print.assert_called_once_with("Paste:")

    def test_ask_multiline_with_nothing_is_empty(self):
        with patch("builtins.input", side_effect=EOFError()):
            self.assertEqual(self.ui.ask_multiline("Paste:"), "")

    def test_echo_is_print(self):
        with patch("builtins.print") as mock_print:
            self.ui.echo("a", "b", sep="-", end="", flush=True)
        mock_print.assert_called_once_with("a", "b", sep="-", end="", flush=True)

    @patch("manage_agenda.ui.console.select_many", return_value=["x"])
    @patch("manage_agenda.ui.console.select_one", return_value="x")
    def test_choose_one_and_many_delegate_to_interactive(self, mock_one, mock_many):
        self.assertEqual(self.ui.choose_one(["x", "y"], title="T", identifier="i", default="x"), "x")
        mock_one.assert_called_once_with(["x", "y"], title="T", identifier="i", default="x")
        self.assertEqual(self.ui.choose_many(["x", "y"], title="T", identifier="i"), ["x"])
        mock_many.assert_called_once_with(["x", "y"], title="T", identifier="i")


class TestSelectEvents(unittest.TestCase):
    def setUp(self):
        self.ui = ConsoleUI()
        self.events = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        self.labels = ["Team meeting", "Dentist", "Meeting with Bob"]

    def _select(self, answer):
        render = MagicMock()
        with patch("builtins.input", return_value=answer) as mock_input, patch("builtins.print"):
            result = self.ui.select_events(
                self.events, self.labels, title="Pick", prompt_text="Which? ", render=render
            )
        mock_input.assert_called_once_with("Which? ")
        render.assert_called_once_with()
        return result

    def test_numbers(self):
        self.assertEqual(self._select("0, 2"), [self.events[0], self.events[2]])

    def test_all_word_or_the_index_past_the_end(self):
        self.assertEqual(self._select("all"), self.events)
        self.assertEqual(self._select("ALL"), self.events)
        self.assertEqual(self._select("3"), self.events)

    def test_a_number_out_of_range_turns_the_whole_answer_into_text_matching(self):
        self.assertEqual(self._select("0, 9"), [])

    def test_text_matches_labels_case_insensitively_without_duplicates(self):
        self.assertEqual(self._select("MEETING"), [self.events[0], self.events[2]])
        self.assertEqual(self._select("meeting, bob"), [self.events[0], self.events[2]])

    def test_prints_title_and_the_all_option(self):
        with patch("builtins.input", return_value=""), patch("builtins.print") as mock_print:
            self.ui.select_events(self.events, self.labels, title="Pick", prompt_text="? ")
        printed = [call.args[0] for call in mock_print.call_args_list]
        self.assertEqual(printed[0], "Pick")
        self.assertIn("3", printed[1])


class TestReviewEvent(unittest.TestCase):
    """The s/r/y/m/d/h/i/f menu that used to be events._validate_event_dates_interactive."""

    def setUp(self):
        self.ui = ConsoleUI()

    def _event(self):
        return {
            "start": {"dateTime": "2024-01-15T10:00:00+00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2024-01-15T11:00:00+00:00", "timeZone": "UTC"},
        }

    def test_s_or_enter_accepts(self):
        for answer in ("s", "", "S"):
            with patch("builtins.input", return_value=answer):
                event, decision = self.ui.review_event(self._event(), label="[x] ")
            self.assertEqual(decision, "accept")
            self.assertEqual(event, self._event())

    def test_r_asks_for_a_retry(self):
        with patch("builtins.input", return_value="r") as mock_input:
            _event, decision = self.ui.review_event(self._event(), label="[x] ")
        self.assertEqual(decision, "retry")
        self.assertTrue(mock_input.call_args.args[0].startswith("[x] "))

    def test_component_edit_then_accept(self):
        # "y": edit the year of start and end (asked one after the other), then accept.
        with patch("builtins.input", side_effect=["y", "2030", "2030", "s"]), patch("builtins.print"):
            event, decision = self.ui.review_event(self._event())
        self.assertEqual(decision, "accept")
        start, end = _parse_event_times(event)
        self.assertEqual((start.year, end.year), (2030, 2030))
        self.assertEqual(end - start, datetime.timedelta(hours=1))

    def test_empty_component_answer_keeps_the_value(self):
        with patch("builtins.input", side_effect=["h", "", "", ""]), patch("builtins.print"):
            event, _decision = self.ui.review_event(self._event())
        self.assertEqual(_parse_event_times(event), _parse_event_times(self._event()))

    def test_full_datetime_with_the_default_end(self):
        answers = ["f", "2030-06-01 10:00:00", "n", ""]
        with patch("builtins.input", side_effect=answers), patch("builtins.print"):
            event, decision = self.ui.review_event(self._event())
        self.assertEqual(decision, "accept")
        start, end = _parse_event_times(event)
        self.assertEqual(end - start, datetime.timedelta(minutes=45))
        self.assertEqual((start.month, start.day), (6, 1))

    def test_unknown_letter_just_re_asks(self):
        with patch("builtins.input", side_effect=["x", "s"]) as mock_input, patch("builtins.print"):
            _event, decision = self.ui.review_event(self._event())
        self.assertEqual(decision, "accept")
        self.assertEqual(mock_input.call_count, 2)


if __name__ == "__main__":
    unittest.main()
