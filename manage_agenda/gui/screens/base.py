"""Screen: the base of every page of the main window."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from manage_agenda.gui.widgets import hint_label
from manage_agenda.i18n import t


class Screen(QWidget):
    """A page. Subclasses set `nav_key` (the t() key of their name in the sidebar) and
    `subtitle_key` (the one-line description under it), build their widgets into
    `self.content`, register their Run buttons so they are disabled while a job runs, and
    never call core code on the GUI thread: they submit() it to the job runner."""

    nav_key = "gui.nav.unknown"
    subtitle_key = ""

    def __init__(self, runner, parent=None):
        super().__init__(parent)
        self.runner = runner
        self._run_buttons = []
        self.last_error = ""
        runner.started.connect(self._on_started)
        runner.finished.connect(self._on_ended)
        runner.failed.connect(self._on_ended)
        runner.cancelled.connect(self._on_ended)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 12)
        outer.setSpacing(4)
        self.title_label = QLabel(self.title(), self)
        self.title_label.setObjectName("screenTitle")
        outer.addWidget(self.title_label)
        if self.subtitle_key:
            self.subtitle_label = hint_label(t(self.subtitle_key), self)
            outer.addWidget(self.subtitle_label)
        outer.addSpacing(10)
        # Where a subclass builds its widgets.
        self.content = QVBoxLayout()
        self.content.setSpacing(10)
        outer.addLayout(self.content, 1)

    def title(self):
        return t(self.nav_key)

    def register_run_button(self, button):
        self._run_buttons.append(button)
        return button

    def submit(self, name, func, *args, on_done=None, **kwargs):
        """Run `func` in the job runner; False when a job is already running."""
        return self.runner.submit(name, func, *args, on_done=on_done, **kwargs)

    def refresh(self):
        """Re-read configuration; called when the screen is shown."""

    def _on_started(self, _name):
        self.set_running(True)

    def _on_ended(self, *_ignored):
        self.set_running(False)

    def set_running(self, running):
        for button in self._run_buttons:
            button.setEnabled(not running)
