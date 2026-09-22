import pytest

@pytest.fixture(autouse=True)
def isolated_log_file(monkeypatch, tmp_path):
    """
    Fixture to ensure that all tests use an isolated log file in a temporary directory.
    This prevents tests from failing due to environment-specific log file paths.
    """
    log_file_path = tmp_path / "test_manage_agenda.log"
    monkeypatch.setenv("LOG_FILE", str(log_file_path))


@pytest.fixture(autouse=True)
def pinned_english_language():
    """Most tests assert on hardcoded English strings. manage_agenda.i18n resolves the
    interface language from the host's LANG/LC_ALL (which may well be French, e.g. on a
    French-locale machine) and caches it for the process, so without this fixture the whole
    suite's results would depend on whoever's environment runs it. A test that specifically
    exercises translation (see tests/test_i18n.py) calls set_language()/reset_language_cache()
    itself, which overrides this for its own duration.
    """
    from manage_agenda.i18n import reset_language_cache, set_language

    set_language("en")
    yield
    reset_language_cache()
