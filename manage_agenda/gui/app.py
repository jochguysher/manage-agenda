"""Entry points: `manage-agenda gui` (cli.py) and the `manage-agenda-gui` script."""

from __future__ import annotations

import logging
import sys

from manage_agenda.base import PACKAGE_LOGGER_NAME, setup_logging
from manage_agenda.gui.log_panel import QtLogHandler
from manage_agenda.gui.main_window import MainWindow
from manage_agenda.i18n import t
from manage_agenda.ui import set_ui


class GuiThreadUI:
    """The UI port installed on the GUI thread while no job runs: a prompt from there would
    mean core code was called outside the job runner, which would have read stdin - it
    fails loudly instead. Output still reaches the log panel."""

    def __init__(self, window: MainWindow):
        self.window = window

    def _refuse(self, *_args, **_kwargs):
        raise RuntimeError(t("gui.port_called_outside_job"))

    choose_one = choose_many = choose_action = confirm = _refuse
    ask_text = ask_multiline = review_event = select_events = _refuse

    def echo(self, *parts, sep=" ", end="\n", flush=False):
        self.window.log_line(sep.join(str(part) for part in parts))


def create_window(verbose=False):
    """The main window with the log handler attached and the GUI-thread UI installed.
    Separate from run() so tests can build it without an event loop."""
    window = MainWindow(verbose=verbose)
    handler = QtLogHandler(window.bridge, level=logging.DEBUG if verbose else logging.INFO)
    logging.getLogger(PACKAGE_LOGGER_NAME).addHandler(handler)
    window.log_handler = handler
    set_ui(GuiThreadUI(window))
    return window


def release_window(window):
    """Undo create_window()'s process-global installs."""
    logging.getLogger(PACKAGE_LOGGER_NAME).removeHandler(window.log_handler)
    set_ui(None)


def run(verbose=False):
    """Open the window and run the application; the process exit code."""
    from PySide6.QtWidgets import QApplication

    from manage_agenda.gui.persist import saved_theme
    from manage_agenda.gui.theme import apply_theme

    app = QApplication.instance() or QApplication(sys.argv[:1])
    apply_theme(app, saved_theme())
    window = create_window(verbose=verbose)
    window.show()
    try:
        return app.exec()
    finally:
        release_window(window)


def main(argv=None):
    """The `manage-agenda-gui` script: like `manage-agenda [-v] gui`."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in arguments or "--verbose" in arguments
    setup_logging(verbose)
    return run(verbose=verbose)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
