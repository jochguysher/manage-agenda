"""Persistent user configuration: LLM provider, model, and calendar account/id.

Saved automatically after the first interactive selection and reused on later runs (see
select_llm() in llm.py and prepare_calendar() in connections.py), instead of asking again
every time. Location follows the XDG base directory spec, matching config_dir().

Every reader/writer here takes an optional `path` so callers - and tests - never have to touch
the real file: binding the path once at import time would mean a test that sets XDG_CONFIG_HOME
has no effect (the module is already imported), and would make production and test runs read
and write the same file whenever no override is passed.
"""

import logging
from pathlib import Path

import yaml

from manage_agenda.config import config_dir

logger = logging.getLogger(__name__)


def user_config_file():
    """Where the saved configuration lives. Resolved fresh on each call, not cached at import -
    config_dir() itself reads $XDG_CONFIG_HOME/$HOME fresh on every call (see its docstring),
    so this claim is now actually true rather than aspirational (an earlier version of this
    function imported the CONFIG_DIR *value* at module level, which had exactly the staleness
    problem this docstring warns against - see docs/investigation-limite1.md §10)."""
    return config_dir() / "config.yaml"


def load_user_config(path=None):
    """The saved configuration as a dict, or {} if there is none yet or it can't be read."""
    path = Path(path) if path else user_config_file()
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        logger.warning(f"Could not read {path}: {error}")
        return {}
    return data if isinstance(data, dict) else {}


def save_user_config(data, path=None):
    path = Path(path) if path else user_config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    temporary.replace(path)


def update_user_config(updates, path=None):
    """Merge `updates` into the saved configuration and persist it. Returns the merged dict."""
    path = Path(path) if path else user_config_file()
    current = load_user_config(path)
    current.update(updates)
    save_user_config(current, path)
    return current


def saved_calendar_ids(config_data):
    """The saved calendar choice as a list, whether stored as one id or several.

    This feature only ever writes a single id under "calendar", but reading a list too means
    a later multi-calendar feature can start writing one without a second migration of readers.
    """
    value = config_data.get("calendar")
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []
