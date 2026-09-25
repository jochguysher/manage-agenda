"""Install: the Playwright browser `manage-agenda install` downloads; its output streams to
the log panel."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton

from manage_agenda.base import BROWSERS, install_playwright_browser
from manage_agenda.gui.screens.base import Screen
from manage_agenda.gui.widgets import form_layout, hint_label, primary
from manage_agenda.i18n import t


class InstallScreen(Screen):
    nav_key = "gui.nav.install"
    subtitle_key = "gui.install.subtitle"

    def __init__(self, runner, parent=None):
        super().__init__(runner, parent)
        layout = self.content
        form = form_layout()
        self.browser = QComboBox(self)
        self.browser.addItems(BROWSERS)
        form.addRow(t("gui.install.browser"), self.browser)
        layout.addLayout(form)
        layout.addWidget(hint_label(t("gui.install.note"), self))
        row = QHBoxLayout()
        self.run_button = self.register_run_button(primary(QPushButton(t("gui.install.run"), self)))
        row.addWidget(self.run_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.run_button.clicked.connect(self.run)

    def run(self):
        self.submit(t("gui.install.job"), install_playwright_browser, self.browser.currentText())
