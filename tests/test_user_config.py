import unittest
from pathlib import Path
from unittest.mock import patch

from manage_agenda.user_config import (
    load_user_config,
    save_user_config,
    saved_calendar_ids,
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


if __name__ == "__main__":
    unittest.main()
