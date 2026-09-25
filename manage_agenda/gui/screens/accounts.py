"""Accounts: the sections of socialModules' .rssBlogs (and the IMAP credentials in .rssImap)
that the other screens' account pickers list - a table, and a dialog to add, edit or remove
one. The edits are plain local file writes (manage_agenda.accounts), so they run on the GUI
thread like Settings' Save does; the other screens re-read the file when they are shown."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
)

from manage_agenda import accounts
from manage_agenda.accounts import (
    GOOGLE_SERVICE_NAMES,
    IMAP_KEYS,
    IMAP_MODES,
    SERVICES,
    Account,
    AccountError,
)
from manage_agenda.compat import IMAP_DEFAULT_PORT
from manage_agenda.gui.screens.base import Screen
from manage_agenda.gui.widgets import cell, fit_columns, form_layout, hint_label, primary, set_role
from manage_agenda.i18n import t

DEFAULT_FOLDER = "INBOX"
DEFAULT_MAX_AGE_DAYS = 7


def _flag(value):
    return str(value or "").strip().lower() in {"yes", "true", "1", "include"}


class AccountDialog(QDialog):
    """Add or edit one account. `save(account, password)` runs on Save; an AccountError it
    raises is shown and the dialog stays open."""

    def __init__(self, save, account=None, credentials=None, directory=None, parent=None):
        super().__init__(parent)
        self.save = save
        self.original = account
        self.directory = directory
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setWindowTitle(
            t("gui.accounts.dialog_edit_title" if account else "gui.accounts.dialog_add_title")
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Wrapped hints go in box layouts, never in a form row: QFormLayout does not follow a
        # wrapped label's height and would clip or overlap it.
        form = form_layout()
        self.name = QLineEdit(self)
        self.service = QComboBox(self)
        for service in SERVICES:
            self.service.addItem(service, service)
        self.address = QLineEdit(self)
        self.address.setPlaceholderText(t("gui.accounts.address_hint"))
        form.addRow(t("gui.accounts.name"), self.name)
        form.addRow(t("gui.accounts.service"), self.service)
        form.addRow(t("gui.accounts.address"), self.address)
        layout.addLayout(form)
        layout.addWidget(hint_label(t("gui.accounts.name_hint"), self))

        self.imap_box = QGroupBox(t("gui.accounts.imap_box"), self)
        imap_layout = QVBoxLayout(self.imap_box)
        imap_form = form_layout()
        self.server = QLineEdit(self)
        self.port = QSpinBox(self)
        self.port.setRange(1, 65535)
        self.port.setValue(IMAP_DEFAULT_PORT)
        self.login = QLineEdit(self)
        self.password = QLineEdit(self)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.folder = QLineEdit(DEFAULT_FOLDER, self)
        self.mode = QComboBox(self)
        for mode in IMAP_MODES:
            self.mode.addItem(mode, mode)
        self.mark_seen = QCheckBox(t("gui.accounts.mark_seen"), self)
        self.mark_seen.setChecked(True)
        self.max_age = QSpinBox(self)
        self.max_age.setRange(1, 3650)
        self.max_age.setValue(DEFAULT_MAX_AGE_DAYS)
        self.include_older = QCheckBox(t("gui.accounts.include_older"), self)
        self.senders = QLineEdit(self)
        imap_form.addRow(t("gui.accounts.server"), self.server)
        imap_form.addRow(t("gui.accounts.port"), self.port)
        imap_form.addRow(t("gui.accounts.login"), self.login)
        imap_form.addRow(t("gui.accounts.password"), self.password)
        imap_form.addRow(t("gui.accounts.folder"), self.folder)
        imap_form.addRow(t("gui.accounts.mode"), self.mode)
        imap_form.addRow("", self.mark_seen)
        imap_form.addRow(t("gui.accounts.max_age"), self.max_age)
        imap_form.addRow("", self.include_older)
        imap_form.addRow(t("gui.accounts.senders"), self.senders)
        imap_layout.addLayout(imap_form)
        imap_layout.addWidget(hint_label(t("gui.accounts.mode_hint"), self))
        imap_layout.addWidget(hint_label(t("gui.accounts.senders_hint"), self))
        layout.addWidget(self.imap_box)

        self.google_box = QGroupBox(t("gui.accounts.google_box"), self)
        google_layout = QVBoxLayout(self.google_box)
        google_layout.addWidget(hint_label(t("gui.accounts.google_hint"), self))
        self.client_status = QLabel("", self)
        self.client_status.setWordWrap(True)
        google_layout.addWidget(self.client_status)
        self.import_button = QPushButton(t("gui.accounts.import_client"), self)
        import_row = QHBoxLayout()
        import_row.addWidget(self.import_button)
        import_row.addStretch(1)
        google_layout.addLayout(import_row)
        layout.addWidget(self.google_box)

        self.error = QLabel("", self)
        self.error.setWordWrap(True)
        set_role(self.error, "error")
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton(t("gui.dialog.cancel"), self)
        self.save_button = primary(QPushButton(t("gui.accounts.save"), self))
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save)
        self.save_button.setDefault(True)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.service.currentTextChanged.connect(self._on_service_changed)
        self.address.textChanged.connect(self._refresh_client_status)
        self.import_button.clicked.connect(self.import_client)
        if account is not None:
            self.load(account, credentials or {})
        self._on_service_changed(self.service.currentText())

    def load(self, account, credentials):
        """Show `account` (and its .rssImap `credentials`, never the password) in the form."""
        self.name.setText(account.name)
        self.service.setCurrentIndex(max(self.service.findData(account.service), 0))
        self.address.setText(account.address)
        options = account.options
        self.server.setText(credentials.get("server", ""))
        port = str(credentials.get("port") or "").strip()
        self.port.setValue(int(port) if port.isdigit() and 0 < int(port) < 65536 else IMAP_DEFAULT_PORT)
        self.login.setText(credentials.get("user", ""))
        if credentials.get("has_password"):
            self.password.setPlaceholderText(t("gui.accounts.password_unchanged"))
        self.folder.setText(options.get("folder") or DEFAULT_FOLDER)
        self.mode.setCurrentIndex(max(self.mode.findData(options.get("mode")), 0))
        self.mark_seen.setChecked(options.get("mark") == "seen")
        max_age = str(options.get("max_age_days") or "").strip()
        if max_age.isdigit() and int(max_age) > 0:
            self.max_age.setValue(int(max_age))
        self.include_older.setChecked(_flag(options.get("include_older")))
        self.senders.setText(options.get("from", ""))

    def account(self):
        """The Account this form describes; the keys it does not edit are kept."""
        options = dict(self.original.options) if self.original is not None else {}
        service = self.service.currentData()
        if service == "imap":
            options["server"] = self.server.text().strip()
            options["port"] = str(self.port.value())
            options["user"] = self.login.text().strip()
            options["folder"] = self.folder.text().strip() or DEFAULT_FOLDER
            options["mode"] = self.mode.currentData()
            if self.mark_seen.isChecked():
                options["mark"] = "seen"
            else:
                options.pop("mark", None)
            options["max_age_days"] = str(self.max_age.value())
            options["include_older"] = "yes" if self.include_older.isChecked() else "no"
            options["from"] = self.senders.text().strip()
        else:
            for key in IMAP_KEYS + ("server", "user"):
                options.pop(key, None)
        return Account(self.name.text().strip(), service, self.address.text().strip(), options)

    def password_value(self):
        """The password typed, or None to keep the stored one."""
        return self.password.text() or None

    def _save(self):
        try:
            self.save(self.account(), self.password_value())
        except AccountError as error:
            self.error.setText(str(error))
            return
        self.accept()

    def _on_service_changed(self, service):
        self.imap_box.setVisible(service == "imap")
        self.google_box.setVisible(service in GOOGLE_SERVICE_NAMES)
        self._refresh_client_status()
        self.adjustSize()

    def _refresh_client_status(self):
        path = self.account().google_client_file(self.directory)
        if path is None:
            self.client_status.setText(t("accounts.error_google_address"))
            set_role(self.client_status, "hint")
        elif path.is_file():
            self.client_status.setText(t("gui.accounts.client_found"))
            set_role(self.client_status, "ok")
        else:
            self.client_status.setText(t("gui.accounts.client_missing", file=path))
            set_role(self.client_status, "error")

    def import_client(self):
        source, _filter = QFileDialog.getOpenFileName(
            self, t("gui.accounts.import_client_title"), "", "JSON (*.json)"
        )
        if not source:
            return
        try:
            target = accounts.import_google_client(self.account(), source, self.directory)
        except AccountError as error:
            self.error.setText(str(error))
            return
        self.error.setText("")
        self.client_status.setText(t("gui.accounts.client_imported", file=target))
        set_role(self.client_status, "ok")


class AccountsScreen(Screen):
    nav_key = "gui.nav.accounts"
    subtitle_key = "gui.accounts.subtitle"

    def __init__(self, runner, parent=None, directory=None):
        super().__init__(runner, parent)
        # None: the real ~/.mySocial/config; tests give a temporary directory.
        self.directory = directory
        self.accounts = []
        layout = self.content

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            [
                t("gui.accounts.column_name"),
                t("gui.accounts.column_service"),
                t("gui.accounts.column_address"),
                t("gui.accounts.column_details"),
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.add_button = self.register_run_button(primary(QPushButton(t("gui.accounts.add"), self)))
        self.edit_button = self.register_run_button(QPushButton(t("gui.accounts.edit"), self))
        self.remove_button = self.register_run_button(QPushButton(t("gui.accounts.remove"), self))
        self.reload_button = QPushButton(t("gui.accounts.reload"), self)
        row.addWidget(self.add_button)
        row.addWidget(self.edit_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        row.addWidget(self.reload_button)
        layout.addLayout(row)
        self.message = QLabel("", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.add_button.clicked.connect(self.add)
        self.edit_button.clicked.connect(self.edit)
        self.remove_button.clicked.connect(self.remove)
        self.reload_button.clicked.connect(self.refresh)
        self.table.itemDoubleClicked.connect(lambda _item: self.edit())

    # --- data ---

    def refresh(self):
        current = self.selected_account()
        try:
            self.accounts = accounts.load_accounts(self.directory)
            self.last_error = ""
        except Exception as error:  # noqa: BLE001 - shown, the screen stays usable
            self.accounts = []
            self.last_error = f"{type(error).__name__}: {error}"
        self.table.setRowCount(len(self.accounts))
        for row, account in enumerate(self.accounts):
            cells = (account.name, account.service, account.address, self._details(account))
            for column, text in enumerate(cells):
                self.table.setItem(row, column, cell(text))
            if current is not None and account.name == current.name:
                self.table.selectRow(row)
        fit_columns(self.table)
        if self.last_error:
            self.message.setText(self.last_error)
        elif not self.accounts:
            self.message.setText(t("gui.accounts.empty", file=accounts.accounts_file(self.directory)))
        else:
            self.message.setText("")

    def _details(self, account):
        if account.service == "imap":
            credentials = accounts.imap_credentials(account.name, self.directory)
            return t(
                "gui.accounts.details_imap",
                server=credentials["server"],
                folder=account.options.get("folder") or DEFAULT_FOLDER,
                mode=account.options.get("mode", ""),
                senders=account.options.get("from") or t("gui.accounts.senders_none"),
            )
        path = account.google_client_file(self.directory)
        if path is None:
            return ""
        if path.is_file():
            return t("gui.accounts.client_found")
        return t("gui.accounts.client_missing", file=path)

    def selected_account(self):
        row = self.table.currentRow()
        return self.accounts[row] if 0 <= row < len(self.accounts) else None

    # --- the operations ---

    def save_account(self, account, password=None, previous_name=None):
        """What the dialog's Save runs; raises AccountError."""
        saved = accounts.save_account(account, password, previous_name, self.directory)
        self.refresh()
        self.message.setText(t("gui.accounts.saved", name=saved.name))
        return saved

    def add(self):
        self._open(AccountDialog(self.save_account, directory=self.directory, parent=self))

    def edit(self):
        account = self.selected_account()
        if account is None:
            self.message.setText(t("gui.accounts.select_one"))
            return
        credentials = {}
        if account.service == "imap":
            credentials = accounts.imap_credentials(account.name, self.directory)
        self._open(
            AccountDialog(
                lambda new, password: self.save_account(new, password, previous_name=account.name),
                account=account,
                credentials=credentials,
                directory=self.directory,
                parent=self,
            )
        )

    def _open(self, dialog):
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def confirm_remove(self, account):
        answer = QMessageBox.question(
            self,
            self.title(),
            t("gui.accounts.remove_confirm", name=account.name, file=accounts.accounts_file(self.directory)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def remove(self):
        account = self.selected_account()
        if account is None:
            self.message.setText(t("gui.accounts.select_one"))
            return
        if not self.confirm_remove(account):
            return
        accounts.remove_account(account.name, self.directory)
        self.refresh()
        self.message.setText(t("gui.accounts.removed", name=account.name))
