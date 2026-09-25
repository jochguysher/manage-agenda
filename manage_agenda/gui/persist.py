"""gui.ini, next to config.yaml: what the window remembers between sessions - its geometry,
the log panel, the home screen's last choices. Resolved through config_dir() on every call,
so a test's XDG_CONFIG_HOME redirection applies."""

from __future__ import annotations

from PySide6.QtCore import QSettings

from manage_agenda.config import config_dir

WINDOW_STATE_FILE = "gui.ini"
SETTING_THEME = "appearance/theme"


def gui_settings():
    config_dir().mkdir(parents=True, exist_ok=True)
    return QSettings(str(config_dir() / WINDOW_STATE_FILE), QSettings.Format.IniFormat)


def saved_theme():
    """The theme chosen in View › Theme ("light", "dark" or "system"); the default when
    none, or an unknown one, is saved."""
    from manage_agenda.gui.theme import DEFAULT_THEME, THEMES

    value = str(gui_settings().value(SETTING_THEME, DEFAULT_THEME) or "").strip().lower()
    return value if value in THEMES else DEFAULT_THEME


def save_theme(mode):
    settings = gui_settings()
    settings.setValue(SETTING_THEME, mode)
    settings.sync()
