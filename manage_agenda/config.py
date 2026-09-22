"""
Centralized configuration management for manage-agenda.
"""

import datetime
import logging
import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = Path(os.getenv("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "manage-agenda"
DATA_DIR = Path.home() / ".local" / "share" / "manage-agenda"
RUN_START_TIME = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# Ensure directories exist
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


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
    LOG_FILE: str = os.getenv("LOG_FILE", str(DATA_DIR / "manage_agenda.log"))

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

    # Paths
    GOOGLE_CREDENTIALS_DIR: Path = CONFIG_DIR
    MSG_TXT_DIR: str = os.getenv("MSG_TXT_DIR", os.path.expanduser("~/Documents/txt/"))

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
