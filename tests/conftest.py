import os
import socket as _socket_module
from pathlib import Path

import pytest

# Set BEFORE manage_agenda.config is ever imported (this module is - pytest imports every
# conftest.py in a directory before collecting any test file inside it, and nothing above
# this point imports manage_agenda). manage_agenda.config.Config's DEFAULT_TIMEZONE/LOG_LEVEL/
# DEFAULT_EMAIL_TAG/ON_USER_DELETE/GEMINI_API_KEY/MISTRAL_API_KEY/OLLAMA_HOST/
# OLLAMA_DEFAULT_MODEL are all `os.getenv(...)` calls evaluated ONCE, at Config's class-body
# execution time - unlike data_dir()/config_dir()/msg_txt_dir()/log_file_path() (see
# config.py), these were deliberately left as plain class attributes (not converted to
# functions) since nothing needs them to change mid-process. That means isolated_paths'
# per-test monkeypatch.setenv() below, and any config.py `.env` file, are BOTH too late to
# affect them for a test that doesn't override them itself - as happened in practice:
# events.py's default-timezone localization read the real .env's DEFAULT_TIMEZONE=
# America/Toronto (UTC-5 in January) for the whole session, three test_events.py failures
# were wrongly reported as "pre-existing and unrelated" across several rounds before this was
# found (see docs/investigation-limite1.md §10/§11), and only the affected tests were patched
# individually rather than the root cause (isolation covered writes, not this class of read).
#
# Setting these here, unconditionally (not os.environ.setdefault - a real exported shell env
# var must not leak into tests either), before Config's class body ever executes, makes every
# test's baseline deterministic regardless of what .env or the host shell sets. A test that
# needs a specific value (e.g. test_config.py's validate() tests) still overrides it locally
# with unittest.mock.patch.object(Config, ...), which takes precedence within its own scope
# and does not need to change.
_KNOWN_TEST_CONFIG_ENV = {
    "DEFAULT_TIMEZONE": "Europe/Berlin",  # matches Config's own built-in fallback
    "LOG_LEVEL": "INFO",
    "DEFAULT_EMAIL_TAG": "zAgenda",
    "ON_USER_DELETE": "ignore",  # the user-validated default (see config.py) - not overridden
    "OLLAMA_HOST": "http://localhost:11434",
    "OLLAMA_DEFAULT_MODEL": "llama3.1",
}
for _key, _value in _KNOWN_TEST_CONFIG_ENV.items():
    os.environ[_key] = _value

# GEMINI_API_KEY/MISTRAL_API_KEY are `str | None` (os.getenv() with no default) - removed
# rather than set to "", so the known value is really None, not an empty string with
# different truthiness/type semantics from what the type hint promises. A real key exported
# in the host shell (not just .env, which doesn't set these) must not leak into tests either.
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("MISTRAL_API_KEY", None)

# Computed once, at collection time, independent of any per-test monkeypatching below - the
# real, unredirected locations the test suite must never write to. See
# docs/investigation-limite1.md §9/§10: real user data was found polluted by this suite (a
# real Outlook Message-ID in a real handled_mail_ids.json) before these fixtures existed.
_REAL_HOME = Path(os.path.expanduser("~"))
_REAL_DATA_DIR = _REAL_HOME / ".local" / "share" / "manage-agenda"
_REAL_MSG_TXT_DIR = _REAL_HOME / "Documents" / "txt"
_REAL_CONFIG_DIR = _REAL_HOME / ".config" / "manage-agenda"
_REAL_MYSOCIAL_DIR = _REAL_HOME / ".mySocial"
_WATCHED_REAL_DIRECTORIES = (
    _REAL_DATA_DIR,
    _REAL_MSG_TXT_DIR,
    _REAL_CONFIG_DIR,
    _REAL_MYSOCIAL_DIR,
)


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    """Redirects every manage-agenda data/config/log/txt path to a per-test tmp_path.

    manage_agenda.config.data_dir()/config_dir()/msg_txt_dir()/log_file_path() (see that
    module) are all resolved fresh on EVERY call, reading $XDG_DATA_HOME/$XDG_CONFIG_HOME/
    $MSG_TXT_DIR/$LOG_FILE/$HOME - there is no module-level constant baked at import time
    left anywhere in this codebase (that pattern was the actual bug behind real pollution -
    see docs/investigation-limite1.md §10 - and has been removed, not just patched around).
    Setting these env vars is therefore now sufficient and correct on its own, including when
    set after manage_agenda.config was already imported (proven by
    test_isolated_paths_take_effect_after_config_module_import in test_conftest_isolation.py).

    MSG_TXT_DIR and LOG_FILE must be set HERE explicitly, not left to follow from HOME alone:
    the repo's own .env pins both to real absolute paths via os.environ.setdefault() at
    manage_agenda.config's import time (config.py's own _load_dotenv), so they do not derive
    from $HOME/$XDG_DATA_HOME the way data_dir()/config_dir() do. monkeypatch.setenv()
    overrides that unconditionally regardless of setdefault, which is exactly why both are
    listed below rather than relying on the HOME/XDG redirection to cover them.

    HOME itself is also redirected, as defense-in-depth for anything that resolves a
    real-user path lazily via Path.home()/os.path.expanduser("~") without going through
    manage_agenda.config at all - e.g. socialModules' own ~/.mySocial/config lookup.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(fake_home / ".local" / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_home / ".config"))
    monkeypatch.setenv("MSG_TXT_DIR", str(fake_home / "Documents" / "txt"))
    # Same reasoning as MSG_TXT_DIR: a real OUTPUT_DIR exported in the shell or added to .env
    # later would otherwise send `-o file` output from tests to the real location.
    monkeypatch.setenv("OUTPUT_DIR", str(fake_home / "Documents" / "txt" / "output"))
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "test_manage_agenda.log"))


def _snapshot(directory):
    """(existed, {path: (mtime_ns, size)}) for `directory` - existed is False and the dict is
    {} if it doesn't exist (most test machines won't even have it, which is fine, that's still
    a valid "unchanged" baseline). Both mtime and size, not mtime alone: a same-size-window
    rewrite can land within the same mtime tick on some filesystems (confirmed empirically - a
    content change with no size change was missed by mtime alone), and size is nearly free to
    also capture from the same stat() call.

    existed is tracked separately from the (possibly empty) file dict because a test that
    merely CREATES a real, previously-absent, still-empty directory - e.g. by calling
    data_dir()/config_dir(), which used to mkdir() as a side effect of just resolving the path
    - produced no file-dict difference at all and would otherwise pass this guard silently.
    See docs/investigation-limite1.md §10: that mkdir-on-every-call behavior was removed from
    data_dir()/config_dir() for exactly this reason, and this check is the regression test for
    it coming back.

    Plain os.walk/os.stat, not Path.rglob - one stat() per file instead of two (rglob's
    is_file() check plus a separate .stat() call), since this runs twice per test.
    """
    existed = directory.is_dir()
    if not existed:
        return False, {}
    snapshot = {}
    for root, _dirs, files in os.walk(directory):
        for name in files:
            full_path = os.path.join(root, name)
            try:
                info = os.stat(full_path)
                snapshot[full_path] = (info.st_mtime_ns, info.st_size)
            except OSError:
                continue
    return True, snapshot


@pytest.fixture(autouse=True)
def guard_real_data_directories_untouched():
    """Fails the test loudly if anything under any REAL (unredirected)
    manage-agenda-relevant directory changed during it: ~/.local/share/manage-agenda/,
    ~/Documents/txt/, ~/.config/manage-agenda/, and ~/.mySocial/ (socialModules' own account
    config/cache - nothing points at it from this codebase, but nothing prevents a future test
    from calling code that does, so it is watched too).

    A safety net behind isolated_paths, for any code path that manages to bypass it - a
    future function that reads a path some other way, a dependency that reads $HOME via the C
    library instead of os.environ, etc. Uses paths computed once at collection time, above,
    independent of whatever isolated_paths does to the environment during the test, so this
    catches a leak regardless of fixture ordering.
    """
    before = {directory: _snapshot(directory) for directory in _WATCHED_REAL_DIRECTORIES}
    yield
    for directory in _WATCHED_REAL_DIRECTORIES:
        existed_before, files_before = before[directory]
        existed_after, files_after = _snapshot(directory)
        assert existed_after == existed_before, (
            f"Test created or removed the REAL {directory} itself - this must never happen "
            f"(existed before: {existed_before}, after: {existed_after})."
        )
        assert files_after == files_before, (
            f"Test wrote to the REAL {directory} - this must never happen. "
            f"Changed entries: {set(files_after.items()) ^ set(files_before.items())}"
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
