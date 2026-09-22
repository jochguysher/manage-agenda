import os
import socket as _socket_module
from pathlib import Path

import pytest

# Computed once, at collection time, independent of any per-test monkeypatching below - the
# real, unredirected locations the test suite must never write to. See
# docs/investigation-limite1.md §9: real user data was found polluted by this suite (a real
# Outlook Message-ID in a real handled_mail_ids.json) before these fixtures existed.
_REAL_HOME = Path(os.path.expanduser("~"))
_REAL_DATA_DIR = _REAL_HOME / ".local" / "share" / "manage-agenda"
_REAL_MSG_TXT_DIR = _REAL_HOME / "Documents" / "txt"


@pytest.fixture(autouse=True)
def isolated_log_file(monkeypatch, tmp_path):
    """
    Fixture to ensure that all tests use an isolated log file in a temporary directory.
    This prevents tests from failing due to environment-specific log file paths.
    """
    log_file_path = tmp_path / "test_manage_agenda.log"
    monkeypatch.setenv("LOG_FILE", str(log_file_path))


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path):
    """Redirects manage_agenda.config.DATA_DIR to a per-test tmp_path.

    handled_mail_file(), _imap_marker_history_file() and calendar_sync_state_file() all do a
    lazy `from manage_agenda.config import DATA_DIR` inside their own body (not at module
    import time), specifically so this monkeypatch is picked up. Tests that need a specific
    path still pass their own `path=`/`tmp_path`-based one explicitly, which this does not
    interfere with.
    """
    import manage_agenda.config as config_module

    monkeypatch.setattr(config_module, "DATA_DIR", tmp_path / "manage-agenda-data")


@pytest.fixture(autouse=True)
def isolated_msg_txt_dir(monkeypatch, tmp_path):
    """Redirects manage_agenda.base.DEFAULT_DATA_DIR (== config.MSG_TXT_DIR at import time) to
    a per-test tmp_path.

    Unlike DATA_DIR above, DEFAULT_DATA_DIR is a plain module-level constant computed ONCE
    when manage_agenda.base is first imported (`DEFAULT_DATA_DIR = config.MSG_TXT_DIR`), not
    re-read lazily - so redirecting HOME/XDG env vars alone, or even patching
    config.MSG_TXT_DIR itself, would NOT retroactively change it. write_file() reads
    DEFAULT_DATA_DIR as a plain global at call time, so patching the module attribute
    directly, every test, is what's actually needed. This was the real, previously-unpatched
    gap behind ~/Documents/txt/log/ filling up with test-run artifacts (161 entries found
    there from local test runs before this fixture existed).
    """
    import manage_agenda.base as base_module

    monkeypatch.setattr(base_module, "DEFAULT_DATA_DIR", str(tmp_path / "manage-agenda-txt"))


@pytest.fixture(autouse=True)
def isolated_config_dir(monkeypatch, tmp_path):
    """Redirects manage_agenda.config.CONFIG_DIR (used for the OAuth credentials directory and,
    via manage_agenda.user_config's own import of it, config.yaml) to a per-test tmp_path.

    Same "computed once at import" issue as DEFAULT_DATA_DIR above: CONFIG_DIR is a module-
    level constant, and manage_agenda.user_config does `from manage_agenda.config import
    CONFIG_DIR`, binding its OWN separate name to the same original value - patching
    manage_agenda.config.CONFIG_DIR alone would not affect that second binding, so both are
    patched here. No pollution was found here in practice (the real
    ~/.config/manage-agenda/ was empty with no recent writes), but the risk shape is the same
    one that did cause real pollution for DEFAULT_DATA_DIR, so it is closed proactively rather
    than only after finding evidence of it.
    """
    import manage_agenda.config as config_module
    import manage_agenda.user_config as user_config_module

    fake_config_dir = tmp_path / "manage-agenda-config"
    monkeypatch.setattr(config_module, "CONFIG_DIR", fake_config_dir)
    monkeypatch.setattr(user_config_module, "CONFIG_DIR", fake_config_dir)


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    """Redirects HOME and the XDG base-directory env vars to a per-test tmp_path, as requested
    defense-in-depth for anything that resolves a real-user path lazily at call time - e.g.
    socialModules' own config file lookups (~/.mySocial/config), or any future code that calls
    Path.home()/os.path.expanduser("~") directly rather than going through
    manage_agenda.config. Does NOT by itself fix config.DATA_DIR or base.DEFAULT_DATA_DIR,
    which are computed once at import time, well before any test-level monkeypatch can run -
    see isolated_data_dir/isolated_msg_txt_dir for those two specifically.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(fake_home / ".local" / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_home / ".config"))


def _snapshot(directory):
    """{path: (mtime_ns, size)} for every file under `directory` - {} if it doesn't exist
    (most test machines won't even have it, which is fine, that's still a valid "unchanged"
    baseline). Both mtime and size, not mtime alone: a same-size-window rewrite can land
    within the same mtime tick on some filesystems (confirmed empirically - a content change
    with no size change was missed by mtime alone), and size is nearly free to also capture
    from the same stat() call.

    Plain os.walk/os.stat, not Path.rglob - one stat() per file instead of two (rglob's
    is_file() check plus a separate .stat() call), since this runs twice per test.
    """
    if not directory.is_dir():
        return {}
    snapshot = {}
    for root, _dirs, files in os.walk(directory):
        for name in files:
            full_path = os.path.join(root, name)
            try:
                info = os.stat(full_path)
                snapshot[full_path] = (info.st_mtime_ns, info.st_size)
            except OSError:
                continue
    return snapshot


@pytest.fixture(autouse=True)
def guard_real_data_directories_untouched():
    """Fails the test loudly if anything under the REAL (unredirected)
    ~/.local/share/manage-agenda/ or ~/Documents/txt/ changed during it.

    A safety net behind isolated_data_dir/isolated_msg_txt_dir/isolated_home, for any code
    path those miss - a future function that doesn't follow the lazy-import pattern, a
    dependency that reads $HOME via the C library instead of os.environ, etc. Uses paths
    computed once at collection time (_REAL_DATA_DIR/_REAL_MSG_TXT_DIR above), independent of
    whatever isolated_home does to the environment during the test, so this catches a leak
    regardless of fixture ordering.
    """
    before_data = _snapshot(_REAL_DATA_DIR)
    before_txt = _snapshot(_REAL_MSG_TXT_DIR)
    yield
    after_data = _snapshot(_REAL_DATA_DIR)
    after_txt = _snapshot(_REAL_MSG_TXT_DIR)
    assert after_data == before_data, (
        f"Test wrote to the REAL {_REAL_DATA_DIR} - this must never happen. "
        f"Changed entries: {set(after_data.items()) ^ set(before_data.items())}"
    )
    assert after_txt == before_txt, (
        f"Test wrote to the REAL {_REAL_MSG_TXT_DIR} - this must never happen. "
        f"Changed entries: {set(after_txt.items()) ^ set(before_txt.items())}"
    )


_ORIGINAL_SOCKET_CONNECT = _socket_module.socket.connect
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if host not in _LOOPBACK_HOSTS:
        raise RuntimeError(
            f"Test attempted a real network connection to {address!r}. The test suite must "
            "never reach a real network endpoint (Calendar/IMAP/Gmail/LLM API) - mock the "
            "client instead. See docs/investigation-limite1.md §9."
        )
    return _ORIGINAL_SOCKET_CONNECT(self, address)


@pytest.fixture(autouse=True)
def guard_no_real_network_connections(monkeypatch):
    """Blocks any non-loopback socket connection attempt during a test, so a test that forgot
    to mock an API client fails immediately and loudly instead of silently reaching (or
    hanging trying to reach) a real Calendar/IMAP/Gmail/LLM endpoint. Loopback (127.0.0.1,
    ::1, localhost) stays allowed - needed by some test/coverage tooling and not a real
    network egress risk.
    """
    monkeypatch.setattr(_socket_module.socket, "connect", _guarded_connect)


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
