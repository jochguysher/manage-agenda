import unittest
from unittest.mock import patch

from manage_agenda.interactive import select_one


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


if __name__ == "__main__":
    unittest.main()
