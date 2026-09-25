"""Catalog-wide checks - written once so every key added while converting the ~170 remaining
strings is validated automatically, instead of relying on per-string assertions."""

import re
import unittest
from pathlib import Path

from manage_agenda.i18n import SUPPORTED_LANGUAGES
from manage_agenda.messages import TRANSLATIONS

SOURCE_DIR = Path(__file__).parent.parent / "manage_agenda"
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_T_CALL_RE = re.compile(r"\bt\(\s*[\"']([^\"']+)[\"']")


class TestCatalogCompleteness(unittest.TestCase):
    def test_every_key_has_every_supported_language(self):
        missing = {
            key: sorted(set(SUPPORTED_LANGUAGES) - set(catalog))
            for key, catalog in TRANSLATIONS.items()
            if set(SUPPORTED_LANGUAGES) - set(catalog)
        }
        self.assertEqual(missing, {}, f"Keys missing a language: {missing}")

    def test_every_translation_uses_the_same_placeholders_as_english(self):
        mismatched = {}
        for key, catalog in TRANSLATIONS.items():
            english_fields = set(_PLACEHOLDER_RE.findall(catalog.get("en", "")))
            for language, text in catalog.items():
                if language == "en":
                    continue
                fields = set(_PLACEHOLDER_RE.findall(text))
                if fields != english_fields:
                    mismatched[(key, language)] = (english_fields, fields)
        self.assertEqual(mismatched, {}, f"Placeholder mismatch (english, other): {mismatched}")

    def test_no_key_is_an_empty_or_whitespace_string(self):
        blank = [
            (key, language)
            for key, catalog in TRANSLATIONS.items()
            for language, text in catalog.items()
            if not text or not text.strip()
        ]
        self.assertEqual(blank, [], f"Blank translations: {blank}")


class TestEveryTCallHasACatalogEntry(unittest.TestCase):
    """Grep-based, not import-based: catches a key used only on a rarely-exercised branch
    that a plain test run would never reach."""

    def test_every_t_call_key_in_the_source_tree_exists_in_translations(self):
        missing = {}
        for path in SOURCE_DIR.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in _T_CALL_RE.finditer(text):
                key = match.group(1)
                if key not in TRANSLATIONS:
                    missing.setdefault(key, []).append(str(path.relative_to(SOURCE_DIR.parent)))
        self.assertEqual(missing, {}, f"t() calls with no catalog entry: {missing}")


if __name__ == "__main__":
    unittest.main()
