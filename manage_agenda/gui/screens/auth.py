"""Auth: the `manage-agenda auth` check and the desktop OAuth consent."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from manage_agenda.connections import (
    complete_desktop_oauth,
    credential_path,
    describe_auth_failure,
)
from manage_agenda.gui.screens.base import Screen
from manage_agenda.gui.widgets import AccountPicker, load_rules
from manage_agenda.i18n import t
from manage_agenda.ui import echo

SERVICES = ("gcalendar", "gmail")


def _connect(rules, key):
    return rules.readConfigSrc("", key, rules.more.get(key))


def check_auth(rules, key):
    """(authorized, message): what `manage-agenda auth` prints for account `key`."""
    api = _connect(rules, key)
    if api is not None and api.getClient():
        return True, t("cli.auth.authorized_success")
    return False, describe_auth_failure(api)


def run_oauth(rules, key):
    """Run the browser consent for account `key`, as `manage-agenda auth` does when the
    OAuth client file exists: (authorized, message)."""
    api = _connect(rules, key)
    if api is not None and api.getClient():
        return True, t("cli.auth.authorized_success")
    if api is None or not os.path.isfile(credential_path(api)):
        return False, "\n".join(
            [describe_auth_failure(api), "", t("cli.auth.create_oauth_client_instructions")]
        )
    echo(t("cli.auth.opening_browser"))
    if complete_desktop_oauth(api):
        return True, t("cli.auth.authorized_success")
    return False, describe_auth_failure(api)


class AuthScreen(Screen):
    nav_key = "gui.nav.auth"

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        self.rules = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.service = QComboBox(self)
        self.service.addItems(SERVICES)
        self.account = AccountPicker([SERVICES[0]], self)
        form.addRow(t("gui.auth.service"), self.service)
        form.addRow(t("gui.auth.account"), self.account)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.check_button = self.register_run_button(QPushButton(t("gui.auth.check"), self))
        self.oauth_button = self.register_run_button(QPushButton(t("gui.auth.run_oauth"), self))
        row.addWidget(self.check_button)
        row.addWidget(self.oauth_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(QLabel(t("gui.auth.browser_note"), self))

        self.status = QPlainTextEdit(self)
        self.status.setReadOnly(True)
        layout.addWidget(self.status)

        self.service.currentTextChanged.connect(self._on_service_changed)
        self.check_button.clicked.connect(lambda: self._run(check_auth, t("gui.auth.job_check")))
        self.oauth_button.clicked.connect(lambda: self._run(run_oauth, t("gui.auth.job_oauth")))

    def refresh(self):
        try:
            self.rules = load_rules()
            self.last_error = ""
        except Exception as error:  # noqa: BLE001
            self.rules = None
            self.last_error = f"{type(error).__name__}: {error}"
            self.status.setPlainText(self.last_error)
            return
        self.account.refresh(self.rules)

    def _on_service_changed(self, service):
        self.account.services = [service]
        if self.rules is not None:
            self.account.refresh(self.rules)

    def _run(self, func, name):
        key = self.account.current_key()
        if self.rules is None or key is None:
            self.status.setPlainText(t("gui.auth.no_account"))
            return
        self.submit(name, func, self.rules, key, on_done=self.show_result)

    def show_result(self, result):
        authorized, message = result
        prefix = t("gui.auth.status_ok") if authorized else t("gui.auth.status_failed")
        self.status.setPlainText(f"{prefix}\n\n{message}")
