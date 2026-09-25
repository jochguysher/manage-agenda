"""Lists: what `manage-agenda gmail` / `gcalendar` show, in a table."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from manage_agenda.gui.screens.base import Screen
from manage_agenda.gui.widgets import AccountPicker, form_layout, load_rules, primary
from manage_agenda.i18n import t
from manage_agenda.sources import Args, _get_emails_from_folder, _get_events_from_calendar

SERVICES = ("gmail", "imap", "gcalendar")


def fetch_listing(rules, key, service, args):
    """Connect account `key` and list its folder / calendar as (title, date) rows - what
    sources.list_folder() prints through display_posts(). Runs in the job runner."""
    api = rules.readConfigSrc("", key, rules.more.get(key))
    if api is None:
        return []
    if service == "gcalendar":
        posts = _get_events_from_calendar(args, api)
    else:
        posts = _get_emails_from_folder(args, api)
    return [(str(api.getPostTitle(post) or ""), str(api.getPostDate(post) or "")) for post in posts or []]


class ListsScreen(Screen):
    nav_key = "gui.nav.lists"
    subtitle_key = "gui.lists.subtitle"

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        self.rules = None
        layout = self.content
        form = form_layout()
        self.service = QComboBox(self)
        self.service.addItems(SERVICES)
        self.account = AccountPicker([SERVICES[0]], self)
        form.addRow(t("gui.lists.service"), self.service)
        form.addRow(t("gui.lists.account"), self.account)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.run_button = self.register_run_button(primary(QPushButton(t("gui.lists.refresh"), self)))
        row.addWidget(self.run_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels([t("gui.lists.column_title"), t("gui.lists.column_date")])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.empty = QLabel("", self)
        layout.addWidget(self.empty)

        self.service.currentTextChanged.connect(self._on_service_changed)
        self.run_button.clicked.connect(self.run)

    def refresh(self):
        try:
            self.rules = load_rules()
            self.last_error = ""
        except Exception as error:  # noqa: BLE001 - shown, the screen stays usable
            self.rules = None
            self.last_error = f"{type(error).__name__}: {error}"
            self.empty.setText(self.last_error)
            return
        self.account.refresh(self.rules)

    def _on_service_changed(self, service):
        self.account.services = [service]
        if self.rules is not None:
            self.account.refresh(self.rules)

    def build_args(self):
        return Args(interactive=False)

    def run(self):
        key = self.account.current_key()
        if self.rules is None or key is None:
            self.empty.setText(t("gui.lists.no_account"))
            return
        self.table.setRowCount(0)
        self.empty.setText("")
        self.submit(
            t("gui.lists.job"),
            fetch_listing,
            self.rules,
            key,
            self.service.currentText(),
            self.build_args(),
            on_done=self.fill,
        )

    def fill(self, rows):
        self.table.setRowCount(len(rows))
        for index, (title, date) in enumerate(rows):
            self.table.setItem(index, 0, QTableWidgetItem(title))
            self.table.setItem(index, 1, QTableWidgetItem(date))
        self.empty.setText("" if rows else t("gui.lists.empty"))
