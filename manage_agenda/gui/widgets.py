"""Widgets shared by several screens: account and calendar pickers."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QListWidget, QListWidgetItem

from manage_agenda.connections import _eligible_calendars, missing_calendar_message
from manage_agenda.exceptions import CalendarError
from manage_agenda.ui import label_for


def load_rules():
    """socialModules' configured accounts (~/.mySocial/config/.rssBlogs), re-read each time -
    the same call every CLI command makes first."""
    from socialModules.moduleRules import moduleRules

    return moduleRules.from_config()


def rule_keys(rules, services):
    """The configured rule keys of `services`, in socialModules' order."""
    keys = []
    for service in services:
        keys.extend(rules.selectRule(service, "") or [])
    return keys


class AccountPicker(QComboBox):
    """The configured accounts of one or more services (e.g. ["gmail", "imap"])."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = list(services)
        self.keys = []

    def refresh(self, rules):
        current = self.current_key()
        self.keys = rule_keys(rules, self.services)
        self.clear()
        for key in self.keys:
            self.addItem(label_for(key))
        if current in self.keys:
            self.setCurrentIndex(self.keys.index(current))

    def current_key(self):
        index = self.currentIndex()
        return self.keys[index] if 0 <= index < len(self.keys) else None


def fetch_calendars(rules, key):
    """Connect the calendar account `key` and list its writable calendars: (api, calendars).
    Runs in the job runner (it may open the OAuth flow or hit the network)."""
    api = rules.readConfigSrc("", key, rules.more.get(key))
    if api is None or api.getClient() is None:
        raise CalendarError(missing_calendar_message(api))
    return api, _eligible_calendars(api)


class CalendarPicker(QListWidget):
    """Checkable list of an account's writable calendars, filled by fetch_calendars()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.api = None
        self.calendars = []

    def fill(self, api, calendars, checked_ids=()):
        self.api = api
        self.calendars = list(calendars)
        self.clear()
        for calendar in self.calendars:
            item = QListWidgetItem(label_for(calendar, "summary"))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = calendar.get("id") in checked_ids
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.addItem(item)

    def checked_ids(self):
        return [
            self.calendars[row]["id"]
            for row in range(self.count())
            if self.item(row).checkState() == Qt.CheckState.Checked
        ]
