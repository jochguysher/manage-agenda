"""The window builds offscreen, with every screen, and create_window() installs exactly what
run() needs: the log handler (surviving setup_logging) and the GUI-thread UI."""

import logging

import pytest

from manage_agenda.base import PACKAGE_LOGGER_NAME, setup_logging
from manage_agenda.config import config_dir
from manage_agenda.gui import app as gui_app
from manage_agenda.gui.log_panel import QtLogHandler
from manage_agenda.gui.main_window import SCREEN_CLASSES, MainWindow
from manage_agenda.ui import echo, get_ui


def test_main_window_has_every_screen(qapp):
    window = MainWindow()
    assert [type(screen) for screen in window.screens] == list(SCREEN_CLASSES)
    assert window.nav.count() == len(SCREEN_CLASSES)
    assert window.stack.count() == len(SCREEN_CLASSES)
    assert all(screen.title() for screen in window.screens)
    assert not window.cancel_button.isEnabled()
    window.close()


def test_log_panel_toggles_and_its_state_survives_a_restart(qapp):
    window = MainWindow()
    window.show()
    assert window.log_dock.isVisible() and window.log_action.isChecked()
    window.log_action.trigger()
    assert not window.log_dock.isVisible()
    assert window.close()
    assert (config_dir() / "gui.ini").is_file()

    reopened = MainWindow()
    assert reopened.log_dock.isHidden() and not reopened.log_action.isChecked()
    reopened.log_action.trigger()
    assert not reopened.log_dock.isHidden()
    reopened.close()


def test_create_window_installs_the_log_handler_and_the_gui_thread_ui(qapp, pump, monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "gui.log"))
    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    window = gui_app.create_window(verbose=False)
    try:
        handlers = [h for h in package_logger.handlers if isinstance(h, QtLogHandler)]
        assert handlers == [window.log_handler]
        assert not getattr(window.log_handler, "manage_agenda_handler", False)

        # setup_logging() replaces its own handlers, not this one.
        setup_logging(False)
        assert window.log_handler in package_logger.handlers

        logging.getLogger("manage_agenda.sources").warning("hello panel")
        assert pump(lambda: any("hello panel" in line for line in window.log_panel.lines()))

        # On the GUI thread, output reaches the panel and prompts are refused.
        echo("outside a job")
        assert "outside a job" in window.log_panel.lines()
        with pytest.raises(RuntimeError):
            get_ui().confirm("?")
    finally:
        gui_app.release_window(window)
        for handler in list(package_logger.handlers):
            if getattr(handler, "manage_agenda_handler", False):
                package_logger.removeHandler(handler)
                handler.close()
    assert window.log_handler not in package_logger.handlers
    assert type(get_ui()).__name__ == "ConsoleUI"


def test_job_lifecycle_updates_the_status_bar_and_cancel_button(qapp, pump):
    window = MainWindow()
    assert window.runner.submit("demo", lambda: 0)
    assert pump(lambda: not window.runner.is_busy())
    assert not window.cancel_button.isEnabled()
    assert window.status_label.text()
    assert "=== demo ===" in window.log_panel.lines()

    assert window.runner.submit("code", lambda: 3)
    assert pump(lambda: not window.runner.is_busy())
    assert "3" in window.status_label.text()
    window.close()


def test_a_failing_job_reports_in_the_status_bar_and_log(qapp, pump):
    window = MainWindow()

    def boom():
        raise RuntimeError("kaboom")

    window.runner.submit("bad", boom)
    assert pump(lambda: not window.runner.is_busy())
    assert "RuntimeError: kaboom" in window.status_label.text()
    assert any("RuntimeError: kaboom" in line for line in window.log_panel.lines())
    for widget in qapp.topLevelWidgets():
        if widget is not window:
            widget.close()
    window.close()


def test_closing_while_a_job_is_stuck_in_a_call_is_refused(qapp, pump):
    """Destroying the window would destroy a live QThread (fatal in Qt): the close is
    refused until the call returns, then works."""
    import threading

    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    from manage_agenda.gui import main_window

    window = MainWindow()
    release = threading.Event()
    assert window.runner.submit("stuck", release.wait, 30)
    assert pump(window.runner.is_busy, 1)

    event = QCloseEvent()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        mp.setattr(main_window, "CLOSE_WAIT_MS", 50)
        window.closeEvent(event)
    assert not event.isAccepted()
    assert window.status_label.text()
    assert window.runner.is_busy()

    release.set()
    assert pump(lambda: not window.runner.is_busy())
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
