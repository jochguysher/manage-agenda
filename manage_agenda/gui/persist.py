"""gui.ini, next to config.yaml: what the window remembers between sessions - its geometry,
the log panel, the home screen's last choices. Resolved through config_dir() on every call,
so a test's XDG_CONFIG_HOME redirection applies."""

from __future__ import annotations

from PySide6.QtCore import QSettings

from manage_agenda.config import config_dir

WINDOW_STATE_FILE = "gui.ini"


def gui_settings():
    config_dir().mkdir(parents=True, exist_ok=True)
    return QSettings(str(config_dir() / WINDOW_STATE_FILE), QSettings.Format.IniFormat)
