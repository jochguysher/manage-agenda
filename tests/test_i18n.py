import unittest
from pathlib import Path
from unittest.mock import patch

from manage_agenda.i18n import (
    _language_from_locale_string,
    _resolve_language,
    detect_system_language,
    get_language,
    reset_language_cache,
    set_language,
    t,
)
from manage_agenda.user_config import save_user_config


class TestLocaleParsing(unittest.TestCase):
    def test_plain_language_code(self):
        self.assertEqual(_language_from_locale_string("fr"), "fr")

    def test_territory_and_encoding_are_stripped(self):
        self.assertEqual(_language_from_locale_string("fr_FR.UTF-8"), "fr")

    def test_modifier_is_stripped(self):
        self.assertEqual(_language_from_locale_string("fr_FR.UTF-8@euro"), "fr")

    def test_hyphen_separated_form(self):
        self.assertEqual(_language_from_locale_string("fr-FR"), "fr")

    def test_language_priority_list_uses_the_first_entry(self):
        self.assertEqual(_language_from_locale_string("fr:en"), "fr")

    def test_c_and_posix_carry_no_language_signal(self):
        self.assertIsNone(_language_from_locale_string("C"))
        self.assertIsNone(_language_from_locale_string("POSIX"))

    def test_empty_or_none_is_none(self):
        self.assertIsNone(_language_from_locale_string(""))
        self.assertIsNone(_language_from_locale_string(None))


class TestDetectSystemLanguage(unittest.TestCase):
    def test_lc_all_wins_over_lang(self):
        with patch.dict("os.environ", {"LC_ALL": "fr_FR.UTF-8", "LANG": "en_US.UTF-8"}):
            self.assertEqual(detect_system_language(), "fr")

    def test_falls_back_to_lang_when_lc_all_is_unset(self):
        with patch.dict("os.environ", {"LANG": "fr_CA.UTF-8"}, clear=False):
            with patch.dict("os.environ", {}, clear=False):
                import os

                os.environ.pop("LC_ALL", None)
                self.assertEqual(detect_system_language(), "fr")

    def test_nothing_set_is_none(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(detect_system_language())


class TestResolveLanguage(unittest.TestCase):
    def setUp(self):
        self.config_path = Path("/tmp") / (self.id().replace(".", "_") + "_config.yaml")
        self.config_path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.config_path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.config_path) + ".tmp").unlink(missing_ok=True))

    def test_saved_config_overrides_system_detection(self):
        save_user_config({"language": "fr"}, self.config_path)
        with patch.dict("os.environ", {"LANG": "en_US.UTF-8"}):
            self.assertEqual(_resolve_language(self.config_path), "fr")

    def test_falls_back_to_system_detection_when_nothing_saved(self):
        with patch.dict("os.environ", {"LANG": "fr_FR.UTF-8"}):
            self.assertEqual(_resolve_language(self.config_path), "fr")

    def test_falls_back_to_english_when_nothing_is_known(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_resolve_language(self.config_path), "en")


class TestGetSetLanguage(unittest.TestCase):
    def tearDown(self):
        reset_language_cache()

    def test_set_language_is_cached_and_returned(self):
        set_language("fr")
        self.assertEqual(get_language(), "fr")

    def test_unsupported_language_falls_back_to_english(self):
        set_language("klingon")
        self.assertEqual(get_language(), "en")

    def test_reset_forces_re_resolution(self):
        set_language("fr")
        reset_language_cache()
        with patch("manage_agenda.i18n._resolve_language", return_value="en"):
            self.assertEqual(get_language(), "en")


class TestTranslate(unittest.TestCase):
    def tearDown(self):
        reset_language_cache()

    def test_translates_into_the_active_language(self):
        set_language("fr")
        self.assertNotEqual(t("llm.selected_ai", ai="ollama"), "")
        self.assertIn("ollama", t("llm.selected_ai", ai="ollama"))

    def test_same_key_differs_between_languages(self):
        set_language("en")
        english = t("llm.selected_ai", ai="ollama")
        set_language("fr")
        french = t("llm.selected_ai", ai="ollama")
        self.assertNotEqual(english, french)

    def test_missing_key_returns_the_key_itself_instead_of_crashing(self):
        set_language("en")
        self.assertEqual(t("this.key.does.not.exist"), "this.key.does.not.exist")

    def test_missing_french_translation_falls_back_to_english(self):
        with patch(
            "manage_agenda.messages.TRANSLATIONS",
            {"only.english": {"en": "Only in English"}},
        ):
            set_language("fr")
            self.assertEqual(t("only.english"), "Only in English")

    def test_bad_format_kwargs_does_not_crash(self):
        with patch(
            "manage_agenda.messages.TRANSLATIONS",
            {"needs.name": {"en": "Hello {name}", "fr": "Bonjour {name}"}},
        ):
            set_language("en")
            self.assertEqual(t("needs.name"), "Hello {name}")


if __name__ == "__main__":
    unittest.main()
