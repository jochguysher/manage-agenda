"""
Centralized configuration management for manage-agenda.
"""

import datetime
import logging
import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent.parent
RUN_START_TIME = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def data_dir() -> Path:
    """Where manage-agenda stores its own state (ledger, Calendar sync tokens, IMAP marker
    history, log file) - resolved fresh on EVERY call from $XDG_DATA_HOME/$HOME, never cached
    as a module-level constant. A pure path resolver - it does NOT create the directory:
    every actual writer (_save_state, save_user_config, _save_sync_tokens, ...) already does
    its own `path.parent.mkdir(parents=True, exist_ok=True)` right before writing, so doing
    it here too would be redundant for them and a real side effect for a read-only caller
    (e.g. scripts/diagnose_ledger.py, whose entire contract is zero writes - see
    docs/investigation-limite1.md).

    This function (and config_dir()/msg_txt_dir()/log_file_path() below) exists specifically
    because a baked-at-import constant was a real, repeatedly-rediscovered bug class here: a
    module-level `DATA_DIR = Path.home() / ...` (the previous design) freezes whatever HOME
    was at the moment manage_agenda.config first got imported, so a later change to HOME or
    XDG_DATA_HOME - a test's monkeypatch, or a real environment change - has no effect on any
    code that already imported the old value. See docs/investigation-limite1.md §10: this is
    exactly how real user data ended up mixed with test-injected entries for as long as it did
    (each individual fix in §8/§9 patched one more baked constant, rather than removing the
    pattern that keeps producing them).
    """
    base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "manage-agenda"


def config_dir() -> Path:
    """Where manage-agenda's own persistent config (config.yaml) lives, and where OAuth
    credentials are expected - resolved fresh on every call. Also a pure path resolver, for
    the same reason as data_dir() above: every writer creates its own parent directory."""
    base = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "manage-agenda"


def msg_txt_dir() -> str:
    """Where extracted-message logs and txt-source files live - resolved fresh on every call.
    See data_dir()'s docstring for why this is a function, not a constant."""
    return os.getenv("MSG_TXT_DIR", os.path.expanduser("~/Documents/txt/"))


def log_file_path() -> str:
    """Where the application log file is written - resolved fresh on every call. See
    data_dir()'s docstring for why this is a function, not a constant."""
    return os.getenv("LOG_FILE", str(data_dir() / "manage_agenda.log"))


def output_dir() -> str:
    """Where `-o file` mode writes its actual result (extraction.py's
    _process_event_with_llm_and_calendar) - resolved fresh on every call, its own dedicated
    directory, deliberately separate from msg_txt_dir()/log/ (which purge_expired_log_files()
    sweeps by age - see base.py). That file used to live under msg_txt_dir()/log/ itself,
    indistinguishable by path from a debug artifact of the same name shape; moving it here
    is what makes that sweep safe to apply uniformly, with no per-filename exception."""
    return os.getenv("OUTPUT_DIR", os.path.join(msg_txt_dir(), "output"))


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file without overriding the environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


class Config:
    """Application configuration with environment variable support."""

    # Default timezone
    DEFAULT_TIMEZONE: str = os.getenv("DEFAULT_TIMEZONE", "Europe/Berlin")

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    # LOG_FILE is intentionally NOT a class attribute here - use log_file_path() above,
    # called fresh wherever the value is needed. See data_dir()'s docstring.

    # Email
    DEFAULT_EMAIL_TAG: str = os.getenv("DEFAULT_EMAIL_TAG", "zAgenda")

    # What to do when a user manually deletes an event manage-agenda created: "ignore" (the
    # message stays marked processed, the deletion stands - default, since there is no way to
    # tell an accidental deletion from a deliberate one) or "requeue" (bump the identity's
    # generation and un-mark its source message so the next scan recreates the event under a
    # fresh id). See docs/investigation-limite1.md - this default was explicitly validated by
    # the user, not chosen unilaterally.
    ON_USER_DELETE: str = os.getenv("ON_USER_DELETE", "ignore")

    # API Keys
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    MISTRAL_API_KEY: str | None = os.getenv("MISTRAL_API_KEY")

    # Ollama
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_DEFAULT_MODEL: str = os.getenv("OLLAMA_DEFAULT_MODEL", "llama3.1")

    # GOOGLE_CREDENTIALS_DIR and MSG_TXT_DIR are intentionally NOT class attributes here -
    # use config_dir()/msg_txt_dir() above, called fresh wherever the value is needed.
    # (GOOGLE_CREDENTIALS_DIR was never actually read anywhere in this codebase besides its
    # own declaration - confirmed by grep - so it is simply not replaced with an equivalent
    # function; config_dir() already covers the same directory for config.yaml.)

    @classmethod
    def validate(cls) -> bool:
        """Validate critical configuration values."""
        issues = []

        # Check timezone validity
        try:
            import pytz

            pytz.timezone(cls.DEFAULT_TIMEZONE)
        except Exception as e:
            issues.append(f"Invalid timezone '{cls.DEFAULT_TIMEZONE}': {e}")

        # Log level validation
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if cls.LOG_LEVEL.upper() not in valid_levels:
            issues.append(f"Invalid LOG_LEVEL '{cls.LOG_LEVEL}'. Must be one of {valid_levels}")

        valid_on_user_delete = ["ignore", "requeue"]
        if cls.ON_USER_DELETE not in valid_on_user_delete:
            issues.append(
                f"Invalid ON_USER_DELETE '{cls.ON_USER_DELETE}'. Must be one of {valid_on_user_delete}"
            )

        if issues:
            for issue in issues:
                logging.warning(f"Configuration issue: {issue}")
            return False

        return True

    @classmethod
    def get_api_key(cls, service: str) -> str | None:
        """Get API key for a specific service with validation."""
        key_map = {
            "gemini": cls.GEMINI_API_KEY,
            "mistral": cls.MISTRAL_API_KEY,
        }

        key = key_map.get(service.lower())
        if not key:
            logging.warning(f"No API key configured for {service}")
        return key


# Singleton instance
config = Config()
