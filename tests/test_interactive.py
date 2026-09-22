import unittest
from unittest.mock import patch

from manage_agenda.interactive import select_many, select_one


class TestSelectOne(unittest.TestCase):
    def test_empty_options_returns_none_without_calling_anything(self):
        with patch("manage_agenda.interactive.questionary") as mock_questionary:
            self.assertIsNone(select_one([]))
            mock_questionary.select.assert_not_called()

    @patch("manage_agenda.interactive._has_tty", return_value=True)
    @patch("manage_agenda.interactive.questionary")
    def test_uses_questionary_when_available_and_a_tty(self, mock_questionary, mock_has_tty):
        mock_questionary.select.return_value.ask.return_value = "gemini"

        result = select_one(["ollama", "gemini", "mistral"], title="Select model provider")

        self.assertEqual(result, "gemini")
        mock_questionary.select.assert_called_once()

    @patch("manage_agenda.interactive._has_tty", return_value=True)
    @patch("manage_agenda.interactive.questionary")
    def test_resolves_dict_options_by_identifier(self, mock_questionary, mock_has_tty):
        options = [{"summary": "Personal", "id": "p1"}, {"summary": "Work", "id": "w1"}]
        mock_questionary.select.return_value.ask.return_value = "Work"

        result = select_one(options, identifier="summary")

        self.assertEqual(result, options[1])

    @patch("manage_agenda.interactive._has_tty", return_value=False)
    @patch("manage_agenda.interactive.select_from_list")
    @patch("manage_agenda.interactive.questionary")
    def test_falls_back_to_select_from_list_without_a_tty(
        self, mock_questionary, mock_select_from_list, mock_has_tty
    ):
        mock_select_from_list.return_value = (1, "gemini")

        result = select_one(["ollama", "gemini", "mistral"])

        self.assertEqual(result, "gemini")
        mock_questionary.select.assert_not_called()
        mock_select_from_list.assert_called_once()

    @patch("manage_agenda.interactive._has_tty", return_value=True)
    @patch("manage_agenda.interactive.select_from_list")
    def test_falls_back_when_questionary_is_not_installed(self, mock_select_from_list, mock_has_tty):
        mock_select_from_list.return_value = (0, "ollama")

        with patch("manage_agenda.interactive.questionary", None):
            result = select_one(["ollama", "gemini"])

        self.assertEqual(result, "ollama")
        mock_select_from_list.assert_called_once()

    @patch("manage_agenda.interactive._has_tty", return_value=True)
    @patch("manage_agenda.interactive.select_from_list")
    @patch("manage_agenda.interactive.questionary")
    def test_falls_back_when_questionary_is_cancelled(
        self, mock_questionary, mock_select_from_list, mock_has_tty
    ):
        mock_questionary.select.return_value.ask.return_value = None
        mock_select_from_list.return_value = (0, "ollama")

        result = select_one(["ollama", "gemini"])

        self.assertEqual(result, "ollama")
        mock_select_from_list.assert_called_once()

    @patch("manage_agenda.interactive._has_tty", return_value=False)
    @patch("manage_agenda.interactive.select_from_list", return_value=(-1, ""))
    def test_nothing_chosen_in_the_fallback_returns_none(self, mock_select_from_list, mock_has_tty):
        self.assertIsNone(select_one(["ollama", "gemini"]))


class TestSelectMany(unittest.TestCase):
    def test_empty_options_returns_an_empty_list_without_calling_anything(self):
        with patch("manage_agenda.interactive.questionary") as mock_questionary:
            self.assertEqual(select_many([]), [])
            mock_questionary.checkbox.assert_not_called()

    @patch("manage_agenda.interactive._has_tty", return_value=True)
    @patch("manage_agenda.interactive.questionary")
    def test_uses_questionary_checkbox_and_can_pick_several(self, mock_questionary, mock_has_tty):
        options = [{"summary": "Personal", "id": "p1"}, {"summary": "Work", "id": "w1"}]
        mock_questionary.checkbox.return_value.ask.return_value = ["Personal", "Work"]

        result = select_many(options, identifier="summary")

        self.assertEqual(result, options)
        mock_questionary.checkbox.assert_called_once()

    @patch("manage_agenda.interactive._has_tty", return_value=True)
    @patch("manage_agenda.interactive.questionary")
    def test_questionary_checkbox_can_pick_none(self, mock_questionary, mock_has_tty):
        mock_questionary.checkbox.return_value.ask.return_value = []

        result = select_many(["ollama", "gemini"])

        self.assertEqual(result, [])

    @patch("manage_agenda.interactive._has_tty", return_value=False)
    @patch("manage_agenda.interactive.click")
    @patch("manage_agenda.interactive.questionary")
    def test_falls_back_to_a_comma_separated_numbered_prompt_without_a_tty(
        self, mock_questionary, mock_click, mock_has_tty
    ):
        mock_click.prompt.return_value = "0, 2"

        result = select_many(["cal-a", "cal-b", "cal-c"], title="Select calendar(s)")

        self.assertEqual(result, ["cal-a", "cal-c"])
        mock_questionary.checkbox.assert_not_called()

    @patch("manage_agenda.interactive._has_tty", return_value=False)
    @patch("manage_agenda.interactive.click")
    def test_fallback_ignores_out_of_range_and_non_numeric_entries(self, mock_click, mock_has_tty):
        mock_click.prompt.return_value = "1, 99, abc"

        with patch("manage_agenda.interactive.questionary", None):
            result = select_many(["cal-a", "cal-b"])

        self.assertEqual(result, ["cal-b"])

    @patch("manage_agenda.interactive._has_tty", return_value=False)
    @patch("manage_agenda.interactive.click")
    def test_fallback_with_nothing_entered_returns_an_empty_list(self, mock_click, mock_has_tty):
        mock_click.prompt.return_value = ""

        with patch("manage_agenda.interactive.questionary", None):
            result = select_many(["cal-a", "cal-b"])

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
