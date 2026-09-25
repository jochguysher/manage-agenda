"""GUI tests: skipped as a whole when PySide6 (the `gui` extra) is not installed, and run
against Qt's offscreen platform so no display is needed."""

import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def wait_until(app, predicate, timeout=5.0):
    """Pump the event loop until `predicate()` is true; False on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


@pytest.fixture
def pump(qapp):
    return lambda predicate, timeout=5.0: wait_until(qapp, predicate, timeout)
