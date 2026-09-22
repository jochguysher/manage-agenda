"""Settings: the saved configuration (config.yaml) the CLI's wizard writes - provider,
model, calendar account and calendars, interface language."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from manage_agenda.gui.screens.base import Screen
from manage_agenda.gui.widgets import AccountPicker, CalendarPicker, fetch_calendars, load_rules
from manage_agenda.i18n import SUPPORTED_LANGUAGES, t
from manage_agenda.user_config import load_user_config, save_user_config, saved_calendar_ids

PROVIDERS = ("ollama", "gemini", "mistral")


class SettingsScreen(Screen):
    nav_key = "gui.nav.settings"

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        self.rules = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.provider = QComboBox(self)
        self.provider.addItem(t("gui.settings.unset"), "")
        for provider in PROVIDERS:
            self.provider.addItem(provider, provider)
        self.model = QLineEdit(self)
        self.account = AccountPicker(["gcalendar"], self)
        self.load_calendars_button = self.register_run_button(
            QPushButton(t("gui.add.load_calendars"), self)
        )
        account_row = QHBoxLayout()
        account_row.addWidget(self.account, 1)
        account_row.addWidget(self.load_calendars_button)
        self.calendars = CalendarPicker(self)
        self.calendars.setMaximumHeight(120)
        self.calendar_ids = QLineEdit(self)
        self.calendar_ids.setPlaceholderText(t("gui.settings.calendar_ids_placeholder"))
        self.language = QComboBox(self)
        self.language.addItem(t("gui.settings.language_auto"), "")
        for language in SUPPORTED_LANGUAGES:
            self.language.addItem(language, language)
        form.addRow(t("gui.settings.provider"), self.provider)
        form.addRow(t("gui.settings.model"), self.model)
        form.addRow(t("gui.settings.calendar_account"), account_row)
        form.addRow(t("gui.settings.calendars"), self.calendars)
        form.addRow(t("gui.settings.calendar_ids"), self.calendar_ids)
        form.addRow(t("gui.settings.language"), self.language)
        layout.addLayout(form)
        layout.addWidget(QLabel(t("gui.settings.restart_note"), self))

        row = QHBoxLayout()
        self.save_button = QPushButton(t("gui.settings.save"), self)
        self.reload_button = QPushButton(t("gui.settings.reload"), self)
        row.addWidget(self.save_button)
        row.addWidget(self.reload_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.message = QLabel("", self)
        layout.addWidget(self.message)
        layout.addStretch(1)

        self.load_calendars_button.clicked.connect(self.load_calendars)
        self.calendars.itemChanged.connect(self._sync_ids_from_picker)
        self.save_button.clicked.connect(self.save)
        self.reload_button.clicked.connect(self.refresh)

    def refresh(self):
        try:
            self.rules = load_rules()
            self.last_error = ""
            self.account.refresh(self.rules)
        except Exception as error:  # noqa: BLE001
            self.rules = None
            self.last_error = f"{type(error).__name__}: {error}"
        self.load(load_user_config())
        self.message.setText(self.last_error)

    def load(self, saved):
        """Show `saved` (a config.yaml dict) in the form."""
        provider = saved.get("provider") or ""
        self.provider.setCurrentIndex(max(self.provider.findData(provider), 0))
        self.model.setText(saved.get("model") or "")
        account = saved.get("calendar_account")
        account = tuple(account) if isinstance(account, list) else account
        if account in self.account.keys:
            self.account.setCurrentIndex(self.account.keys.index(account))
        self.calendar_ids.setText(", ".join(saved_calendar_ids(saved)))
        language = saved.get("language") or ""
        self.language.setCurrentIndex(max(self.language.findData(language), 0))

    def load_calendars(self):
        key = self.account.current_key()
        if self.rules is None or key is None:
            self.message.setText(t("gui.add.no_calendar_account"))
            return
        wanted = [item.strip() for item in self.calendar_ids.text().split(",") if item.strip()]
        self.submit(
            t("gui.add.job_calendars"),
            fetch_calendars,
            self.rules,
            key,
            on_done=lambda result: self.calendars.fill(result[0], result[1], wanted),
        )

    def _sync_ids_from_picker(self, _item):
        if self.calendars.calendars:
            self.calendar_ids.setText(", ".join(self.calendars.checked_ids()))

    def values(self):
        """The config.yaml dict this form describes (unset fields left out)."""
        data = {}
        if self.provider.currentData():
            data["provider"] = self.provider.currentData()
        if self.model.text().strip():
            data["model"] = self.model.text().strip()
        key = self.account.current_key()
        if key is not None:
            data["calendar_account"] = list(key)
        ids = [item.strip() for item in self.calendar_ids.text().split(",") if item.strip()]
        if ids:
            data["calendar"] = ids
        if self.language.currentData():
            data["language"] = self.language.currentData()
        return data

    def save(self):
        current = load_user_config()
        for key in ("provider", "model", "calendar_account", "calendar", "language"):
            current.pop(key, None)
        current.update(self.values())
        save_user_config(current)
        self.message.setText(t("gui.settings.saved"))
