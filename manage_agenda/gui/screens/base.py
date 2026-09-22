"""Screen: the base of every page of the main window."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from manage_agenda.i18n import t


class Screen(QWidget):
    """A page. Subclasses set `nav_key` (the t() key of their name in the sidebar), build
    their widgets, register their Run buttons so they are disabled while a job runs, and
    never call core code on the GUI thread: they submit() it to the job runner."""

    nav_key = "gui.nav.unknown"

    def __init__(self, runner, parent=None):
        super().__init__(parent)
        self.runner = runner
        self._run_buttons = []
        self.last_error = ""
        runner.started.connect(self._on_started)
        runner.finished.connect(self._on_ended)
        runner.failed.connect(self._on_ended)
        runner.cancelled.connect(self._on_ended)

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
