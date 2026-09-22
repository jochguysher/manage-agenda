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

import os
from pathlib import Path

import pytest

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


def test_output_dir_defaults_under_msg_txt_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
    monkeypatch.delenv("OUTPUT_DIR", raising=False)

    assert config_module.output_dir() == os.path.join(str(tmp_path) + "/", "output")


def test_output_dir_is_configurable_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "custom-output"))

    assert config_module.output_dir() == str(tmp_path / "custom-output")


def _read_env_file_raw(path):
    """A minimal, read-only re-parse of a .env file's KEY=VALUE lines - deliberately not
    reusing config._load_dotenv, which mutates os.environ via setdefault() as a side effect.
    Mirrors that function's own parsing rules (quote stripping, `export ` prefix, comments)
    closely enough to read back what it would have seen."""
    values = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def test_config_does_not_leak_the_real_env_files_values():
    """Regression test for docs/investigation-limite1.md §10/§11: manage_agenda.config.Config's
    DEFAULT_TIMEZONE/LOG_LEVEL/DEFAULT_EMAIL_TAG/ON_USER_DELETE/OLLAMA_HOST/
    OLLAMA_DEFAULT_MODEL are plain class attributes read via os.getenv(...) once, at class-body
    execution time - see conftest.py's _KNOWN_TEST_CONFIG_ENV, which seeds known values into
    the environment before manage_agenda.config is ever imported, specifically so the repo's
    real .env (which sets DEFAULT_TIMEZONE=America/Toronto, not the Europe/Berlin every test
    assumes) can never reach a test's Config attributes.

    This asserts the seeding actually worked, using the real .env file itself as the source
    of "what would have leaked" - not a value hardcoded here that could quietly drift from
    both .env and conftest.py without either failing.
    """
    from manage_agenda.config import BASE_DIR, Config

    env_file = BASE_DIR / ".env"
    if not env_file.is_file():
        # .env is git-ignored: on a fresh checkout (CI) there is nothing that could leak,
        # so the check is meaningless there - it only guards a developer's machine.
        pytest.skip("no real .env in this checkout - nothing to leak")
    real_env_values = _read_env_file_raw(env_file)
    assert "DEFAULT_TIMEZONE" in real_env_values, (
        "expected the repo's real .env to set DEFAULT_TIMEZONE for this to be a meaningful "
        "check - if it no longer does, this test should be re-pointed at whatever key still "
        "differs between .env and conftest.py's _KNOWN_TEST_CONFIG_ENV"
    )
    assert real_env_values["DEFAULT_TIMEZONE"] != Config.DEFAULT_TIMEZONE, (
        "the real .env's DEFAULT_TIMEZONE now matches the pinned test value by coincidence - "
        "this check can no longer detect a leak for this key; pick a different mismatched key"
    )
    assert Config.DEFAULT_TIMEZONE == "Europe/Berlin"


def test_no_root_file_log_handler_survives_conftest():
    """socialModules attaches a FileHandler on the REAL ~/usr/var/log/rssSocial.log to the
    root logger at import time; with propagation on, every test's log records were being
    appended to that real file. conftest.py strips it at import and before every test."""
    import logging

    import socialModules.configMod  # noqa: F401 - would (re)install the handler if it could

    root = logging.getLogger()
    assert not [h for h in root.handlers if isinstance(h, logging.FileHandler)], [
        getattr(h, "baseFilename", h) for h in root.handlers
    ]


def test_manage_agenda_records_reach_log_file_without_touching_root(tmp_path, monkeypatch):
    """The fix for the log file that was never written (§12): setup_logging() attaches its
    handler to the "manage_agenda" logger, so records arrive in LOG_FILE even though the
    root logger already had socialModules' handlers when logging.basicConfig() was a no-op."""
    import logging

    from manage_agenda.base import PACKAGE_LOGGER_NAME, setup_logging

    log_file = tmp_path / "manage_agenda.log"
    monkeypatch.setenv("LOG_FILE", str(log_file))
    root_before = list(logging.getLogger().handlers)
    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    try:
        setup_logging()
        logging.getLogger("manage_agenda.sources").info("hello from a module logger")
        for handler in package_logger.handlers:
            handler.flush()
        assert "hello from a module logger" in log_file.read_text(encoding="utf-8")
        assert logging.getLogger().handlers == root_before
    finally:
        for handler in list(package_logger.handlers):
            if getattr(handler, "manage_agenda_handler", False):
                package_logger.removeHandler(handler)
                handler.close()
