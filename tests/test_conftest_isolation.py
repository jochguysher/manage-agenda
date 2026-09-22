"""Proves the claim made in conftest.py's isolated_paths docstring: redirecting
HOME/XDG_DATA_HOME/XDG_CONFIG_HOME/MSG_TXT_DIR/LOG_FILE works even when done AFTER
manage_agenda.config was already imported - which it always is by the time any test runs,
since conftest.py and every other test module import it well before this test's body executes.

This is the direct regression test for the bug class described in
docs/investigation-limite1.md §10: a module-level constant computed once at import time
(the old `DATA_DIR = Path.home() / ...` design) would NOT have been affected by a
monkeypatch.setenv() applied here, because the value was already baked before this test
started. data_dir()/config_dir()/msg_txt_dir()/log_file_path() are functions precisely so
this scenario - the only one that actually matters for test isolation - works.
"""

from pathlib import Path

import manage_agenda.config as config_module


def test_isolated_paths_take_effect_after_config_module_import(monkeypatch, tmp_path):
    # manage_agenda.config is already imported (see module docstring above) - this is the
    # exact "redirect after import" scenario the bug class in §10 broke.
    assert "manage_agenda.config" in __import__("sys").modules

    second_home = tmp_path / "second-home"
    second_home.mkdir()
    monkeypatch.setenv("HOME", str(second_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(second_home / ".local" / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(second_home / ".config"))
    monkeypatch.setenv("MSG_TXT_DIR", str(second_home / "Documents" / "txt") + "/")
    monkeypatch.setenv("LOG_FILE", str(second_home / "manage_agenda.log"))

    assert config_module.data_dir() == second_home / ".local" / "share" / "manage-agenda"
    assert config_module.config_dir() == second_home / ".config" / "manage-agenda"
    assert config_module.msg_txt_dir() == str(second_home / "Documents" / "txt") + "/"
    assert config_module.log_file_path() == str(second_home / "manage_agenda.log")

    # And redirecting again, to a third location, takes effect immediately too - not just
    # once relative to the original import.
    third_home = tmp_path / "third-home"
    third_home.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(third_home / ".local" / "share"))
    assert config_module.data_dir() == third_home / ".local" / "share" / "manage-agenda"


def test_data_dir_and_config_dir_without_xdg_env_fall_back_to_home(monkeypatch, tmp_path):
    fake_home = tmp_path / "no-xdg-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    assert config_module.data_dir() == fake_home / ".local" / "share" / "manage-agenda"
    assert config_module.config_dir() == fake_home / ".config" / "manage-agenda"


def test_log_file_path_without_log_file_env_falls_back_under_data_dir(monkeypatch, tmp_path):
    fake_home = tmp_path / "no-logfile-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(fake_home / ".local" / "share"))
    monkeypatch.delenv("LOG_FILE", raising=False)

    assert config_module.log_file_path() == str(
        Path(fake_home / ".local" / "share" / "manage-agenda" / "manage_agenda.log")
    )
