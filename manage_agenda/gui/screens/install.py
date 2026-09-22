"""Install: the Playwright browser `manage-agenda install` downloads; its output streams to
the log panel."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from manage_agenda.base import BROWSERS, install_playwright_browser
from manage_agenda.gui.screens.base import Screen
from manage_agenda.i18n import t


class InstallScreen(Screen):
    nav_key = "gui.nav.install"

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.browser = QComboBox(self)
        self.browser.addItems(BROWSERS)
        form.addRow(t("gui.install.browser"), self.browser)
        layout.addLayout(form)
        layout.addWidget(QLabel(t("gui.install.note"), self))
        row = QHBoxLayout()
        self.run_button = self.register_run_button(QPushButton(t("gui.install.run"), self))
        row.addWidget(self.run_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.run_button.clicked.connect(self.run)

    def run(self):
        self.submit(t("gui.install.job"), install_playwright_browser, self.browser.currentText())
