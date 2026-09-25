"""Install: the Playwright browser `manage-agenda install` downloads, as a small dialog
opened from Tools › Install the browser…; the download's output streams to the log panel."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from manage_agenda.base import BROWSERS, install_playwright_browser
from manage_agenda.gui.widgets import AutoNamed, form_layout, hint_label, primary, set_role
from manage_agenda.i18n import t


class InstallDialog(AutoNamed, QDialog):
    """Pick the browser engine and start its download in the job runner; the dialog closes
    once the job is submitted (the status bar and the log show its progress)."""

    def __init__(self, runner, parent=None):
        super().__init__(parent)
        self.runner = runner
        self.setModal(True)
        self.setWindowTitle(t("gui.tools.install_title"))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        form = form_layout()
        self.browser = QComboBox(self)
        self.browser.addItems(BROWSERS)
        form.addRow(t("gui.install.browser"), self.browser)
        layout.addLayout(form)
        layout.addWidget(hint_label(t("gui.install.note"), self))
        self.message = QLabel("", self)
        self.message.setWordWrap(True)
        set_role(self.message, "error")
        layout.addWidget(self.message)
        row = QHBoxLayout()
        self.cancel_button = QPushButton(t("gui.dialog.cancel"), self)
        self.run_button = primary(QPushButton(t("gui.install.run"), self))
        self.run_button.setDefault(True)
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        row.addWidget(self.run_button)
        layout.addLayout(row)
        self.cancel_button.clicked.connect(self.reject)
        self.run_button.clicked.connect(self.run)

    def name_prefix(self):
        return "install"

    def run(self):
        """Submit the download; False (and a message) when a job is already running."""
        submitted = self.runner.submit(
            t("gui.install.job"), install_playwright_browser, self.browser.currentText()
        )
        if submitted:
            self.accept()
        else:
            self.message.setText(t("gui.install.busy"))
        return submitted
