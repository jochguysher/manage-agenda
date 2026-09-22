"""Add: the `add` command - source, model, calendars and options on one form; the run's
questions (an old message, a failed extraction, the event review, the label removal) come
up as dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from manage_agenda.gui.screens.base import Screen
from manage_agenda.gui.widgets import AccountPicker, CalendarPicker, fetch_calendars, load_rules
from manage_agenda.i18n import t
from manage_agenda.sources import Args, add_events_cli, get_add_sources
from manage_agenda.ui import label_for
from manage_agenda.user_config import load_user_config, saved_calendar_ids

PROVIDERS = ("", "ollama", "gemini", "mistral")
OUTPUTS = ("calendar", "file")
RULES = ("", "auto", "review")


class AddScreen(Screen):
    nav_key = "gui.nav.add"

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        self.rules = None
        self.sources = []
        layout = QVBoxLayout(self)

        source_box = QGroupBox(t("gui.add.source"), self)
        source_form = QFormLayout(source_box)
        self.source = QComboBox(self)
        self.urls = QLineEdit(self)
        self.urls.setPlaceholderText(t("gui.add.urls_placeholder"))
        self.files = QLineEdit(self)
        self.files.setPlaceholderText(t("gui.add.files_placeholder"))
        source_form.addRow(t("gui.add.source"), self.source)
        source_form.addRow(t("gui.add.urls"), self.urls)
        source_form.addRow(t("gui.add.files"), self.files)
        layout.addWidget(source_box)

        model_box = QGroupBox(t("gui.add.model_box"), self)
        model_form = QFormLayout(model_box)
        self.provider = QComboBox(self)
        self.provider.addItem(t("gui.add.saved_or_default"), "")
        for provider in PROVIDERS[1:]:
            self.provider.addItem(provider, provider)
        self.model = QLineEdit(self)
        self.model.setPlaceholderText(t("gui.add.saved_or_default"))
        model_form.addRow(t("gui.add.provider"), self.provider)
        model_form.addRow(t("gui.add.model"), self.model)
        layout.addWidget(model_box)

        calendar_box = QGroupBox(t("gui.add.calendars"), self)
        calendar_layout = QVBoxLayout(calendar_box)
        account_row = QHBoxLayout()
        self.account = AccountPicker(["gcalendar"], self)
        self.load_calendars_button = self.register_run_button(
            QPushButton(t("gui.add.load_calendars"), self)
        )
        account_row.addWidget(QLabel(t("gui.add.account"), self))
        account_row.addWidget(self.account, 1)
        account_row.addWidget(self.load_calendars_button)
        calendar_layout.addLayout(account_row)
        self.calendars = CalendarPicker(self)
        self.calendars.setMaximumHeight(120)
        calendar_layout.addWidget(self.calendars)
        calendar_layout.addWidget(QLabel(t("gui.add.calendars_note"), self))
        layout.addWidget(calendar_box)

        options_box = QGroupBox(t("gui.add.options"), self)
        options_form = QFormLayout(options_box)
        self.output = QComboBox(self)
        self.output.addItems(OUTPUTS)
        self.rule = QComboBox(self)
        self.rule.addItem(t("gui.add.rule_default"), "")
        for rule in RULES[1:]:
            self.rule.addItem(rule, rule)
        self.force_refresh = QCheckBox(t("cli.add.force_refresh_help"), self)
        self.dry_run_ledger = QCheckBox(t("gui.add.dry_run_ledger"), self)
        self.debug_log = QCheckBox(t("gui.add.debug_log"), self)
        self.retention = QSpinBox(self)
        self.retention.setRange(1, 365)
        self.retention.setValue(7)
        options_form.addRow(t("gui.add.output"), self.output)
        options_form.addRow(t("gui.add.rule_mode"), self.rule)
        options_form.addRow("", self.force_refresh)
        options_form.addRow("", self.dry_run_ledger)
        options_form.addRow("", self.debug_log)
        options_form.addRow(t("gui.add.retention_days"), self.retention)
        layout.addWidget(options_box)

        row = QHBoxLayout()
        self.run_button = self.register_run_button(QPushButton(t("gui.add.run"), self))
        row.addWidget(self.run_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.message = QLabel("", self)
        layout.addWidget(self.message)
        layout.addStretch(1)

        self.source.currentIndexChanged.connect(self._on_source_changed)
        self.load_calendars_button.clicked.connect(self.load_calendars)
        self.run_button.clicked.connect(self.run)
        self._on_source_changed(0)

    # --- data ---

    def refresh(self):
        try:
            self.rules = load_rules()
            self.last_error = ""
        except Exception as error:  # noqa: BLE001
            self.rules = None
            self.last_error = f"{type(error).__name__}: {error}"
            self.message.setText(self.last_error)
            return
        mail_sources, more_options = get_add_sources(rules=self.rules)
        self.sources = list(mail_sources) + list(more_options)
        current = self.selected_source()
        self.source.clear()
        for item in self.sources:
            self.source.addItem(label_for(item))
        if current in self.sources:
            self.source.setCurrentIndex(self.sources.index(current))
        self.account.refresh(self.rules)
        saved = load_user_config()
        account = saved.get("calendar_account")
        account = tuple(account) if isinstance(account, list) else account
        if account in self.account.keys:
            self.account.setCurrentIndex(self.account.keys.index(account))
        self._saved_calendar_ids = saved_calendar_ids(saved)
        self._on_source_changed(self.source.currentIndex())

    def selected_source(self):
        index = self.source.currentIndex()
        return self.sources[index] if 0 <= index < len(self.sources) else None

    @staticmethod
    def _kind(selected):
        text = str(selected)
        if "web" in text or "http" in text:
            return "web"
        if "text" in text:
            return "text"
        return "email"

    def _on_source_changed(self, _index):
        kind = self._kind(self.selected_source()) if self.selected_source() else "email"
        self.urls.setEnabled(kind == "web")
        self.files.setEnabled(kind == "text")

    def load_calendars(self):
        key = self.account.current_key()
        if self.rules is None or key is None:
            self.message.setText(t("gui.add.no_calendar_account"))
            return
        self.submit(
            t("gui.add.job_calendars"),
            fetch_calendars,
            self.rules,
            key,
            on_done=lambda result: self.calendars.fill(
                result[0], result[1], getattr(self, "_saved_calendar_ids", ())
            ),
        )

    # --- the run ---

    def build_args(self):
        """The Args `manage-agenda add -i` would build from this form."""
        args = Args(
            interactive=True,
            ai=self.provider.currentData() or None,
            model=self.model.text().strip() or None,
            output=self.output.currentText(),
            force_refresh=self.force_refresh.isChecked(),
            rule=self.rule.currentData() or None,
            dry_run_ledger=self.dry_run_ledger.isChecked(),
            debug_log_extractions=self.debug_log.isChecked(),
            debug_log_retention_days=self.retention.value(),
        )
        checked = self.calendars.checked_ids()
        if checked and self.calendars.api is not None and args.output == "calendar":
            # What prepare_calendar()/_selected_calendar() would otherwise ask for.
            args.calendar_api = self.calendars.api
            args.calendar_ids = checked
            args.calendar_id = checked[0]
        return args

    def selection_for_run(self):
        """The `selected` value add_events_cli() gets: the mail account key, or the URLs /
        file names typed (which run_add_source() splits on spaces), or the pseudo-source."""
        selected = self.selected_source()
        kind = self._kind(selected)
        if kind == "web" and self.urls.text().strip():
            return self.urls.text().strip()
        if kind == "text" and self.files.text().strip():
            return self.files.text().strip()
        return selected

    def run(self):
        selected = self.selection_for_run()
        if self.rules is None or selected is None:
            self.message.setText(t("gui.add.no_source"))
            return
        self.message.setText("")
        self.submit(t("gui.add.job"), add_events_cli, self.build_args(), self.rules, selected)
