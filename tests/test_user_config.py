import unittest
from pathlib import Path
from unittest.mock import patch

from manage_agenda.user_config import (
    load_user_config,
    remember_calendar_names,
    save_user_config,
    saved_calendar_ids,
    saved_calendar_names,
    update_user_config,
    user_config_file,
)


class TestUserConfigFile(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".yaml")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(load_user_config(self.path), {})

    def test_save_then_load_roundtrips(self):
        save_user_config({"provider": "ollama", "model": "granite4:latest"}, self.path)
        self.assertEqual(
            load_user_config(self.path), {"provider": "ollama", "model": "granite4:latest"}
        )

    def test_update_merges_rather_than_replaces(self):
        save_user_config({"provider": "ollama"}, self.path)
        update_user_config({"model": "granite4:latest"}, self.path)
        self.assertEqual(
            load_user_config(self.path), {"provider": "ollama", "model": "granite4:latest"}
        )

    def test_update_overwrites_an_existing_key(self):
        save_user_config({"provider": "ollama"}, self.path)
        update_user_config({"provider": "gemini"}, self.path)
        self.assertEqual(load_user_config(self.path)["provider"], "gemini")

    def test_corrupt_yaml_reads_as_empty_instead_of_raising(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(": not valid yaml : [", encoding="utf-8")
        self.assertEqual(load_user_config(self.path), {})

    def test_a_yaml_list_at_top_level_reads_as_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("- one\n- two\n", encoding="utf-8")
        self.assertEqual(load_user_config(self.path), {})

    def test_user_config_file_is_under_config_dir(self):
        with patch(
            "manage_agenda.user_config.config_dir",
            return_value=Path("/tmp/xdg-test/manage-agenda"),
        ):
            self.assertEqual(
                user_config_file(), Path("/tmp/xdg-test/manage-agenda/config.yaml")
            )


class TestSavedCalendarIds(unittest.TestCase):
    def test_single_string_becomes_a_one_item_list(self):
        self.assertEqual(saved_calendar_ids({"calendar": "cal-1"}), ["cal-1"])

    def test_a_list_is_returned_as_is(self):
        self.assertEqual(saved_calendar_ids({"calendar": ["cal-1", "cal-2"]}), ["cal-1", "cal-2"])

    def test_missing_key_is_an_empty_list(self):
        self.assertEqual(saved_calendar_ids({}), [])

    def test_falsy_entries_in_a_list_are_dropped(self):
        self.assertEqual(saved_calendar_ids({"calendar": ["cal-1", "", None]}), ["cal-1"])


class TestCalendarNames(unittest.TestCase):
    """The names the tool learns for calendar ids, kept under "calendar_names"."""

    def setUp(self):
        self.path = Path("/tmp") / (self.id().replace(".", "_") + ".yaml")
        self.path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.path) + ".tmp").unlink(missing_ok=True))

    def test_saved_names_ignore_anything_but_a_mapping_of_strings(self):
        self.assertEqual(saved_calendar_names({}), {})
        self.assertEqual(saved_calendar_names({"calendar_names": ["x"]}), {})
        self.assertEqual(
            saved_calendar_names({"calendar_names": {"c1": "One", "": "no id", "c2": None}}),
            {"c1": "One"},
        )

    def test_remember_merges_with_what_is_known_and_keeps_the_rest_of_the_file(self):
        save_user_config({"calendar": ["c1"], "calendar_names": {"c1": "Old", "c9": "Nine"}}, self.path)
        merged = remember_calendar_names(
            [{"id": "c1", "summary": "One"}, {"id": "c2", "summary": "Two"}, {"id": "c3"}, "junk"],
            self.path,
        )
        self.assertEqual(merged, {"c1": "One", "c9": "Nine", "c2": "Two"})
        self.assertEqual(
            load_user_config(self.path),
            {"calendar": ["c1"], "calendar_names": {"c1": "One", "c9": "Nine", "c2": "Two"}},
        )

    def test_remember_writes_nothing_when_nothing_new_is_learnt(self):
        self.assertEqual(remember_calendar_names([], self.path), {})
        self.assertFalse(self.path.exists())
        save_user_config({"calendar_names": {"c1": "One"}}, self.path)
        before = self.path.stat().st_mtime_ns
        self.assertEqual(remember_calendar_names([{"id": "c1", "summary": "One"}], self.path), {"c1": "One"})
        self.assertEqual(self.path.stat().st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
