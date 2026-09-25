"""JobRunner: runs one core flow at a time in a QThread, with the QtUI port installed.

Signals are emitted on the GUI thread (from the QThread's own `finished` signal), so
screens can update widgets in their slots. `submit()` refuses a second job while one runs:
the UI port holder and sys.stdout are process-global, and the core's ledger and config
files are not locked, so concurrency inside one process is simply not offered.
"""

from __future__ import annotations

import contextlib
import threading
import traceback

from PySide6.QtCore import QObject, QThread, Signal

from manage_agenda.exceptions import UserCancelled
from manage_agenda.gui.bridge import Bridge, EchoStream, QtUI
from manage_agenda.ui import use_ui


class _JobThread(QThread):
    def __init__(self, bridge, cancel_flag, func, args, kwargs, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.cancel_flag = cancel_flag
        self.func, self.args, self.kwargs = func, args, kwargs
        self.ui: QtUI | None = None
        self.outcome = ("failed", ("RuntimeError", "job never ran", ""))

    def run(self):
        ui = QtUI(self.bridge, self.cancel_flag)
        self.ui = ui
        stream = EchoStream(ui)
        try:
            with use_ui(ui), contextlib.redirect_stdout(stream):
                result = self.func(*self.args, **self.kwargs)
        except UserCancelled:
            self.outcome = ("cancelled", None)
        except BaseException as error:  # noqa: BLE001 - reported to the user, never lost
            self.outcome = (
                "failed",
                (type(error).__name__, str(error), traceback.format_exc()),
            )
        else:
            self.outcome = ("finished", result)
        finally:
            stream.flush()


class JobRunner(QObject):
    """See the module docstring. `on_done(result)` is called, on the GUI thread, when the
    job returns normally - for a screen that needs its result, unlike the `finished` signal
    every screen listens to for its enabled state."""

    started = Signal(str)  # job name
    finished = Signal(object)  # the flow's return value
    failed = Signal(str, str)  # "ExceptionType: message", traceback
    cancelled = Signal()

    def __init__(self, bridge: Bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self._thread: _JobThread | None = None
        self._cancel_flag: threading.Event | None = None
        self._on_done = None
        self.current_name = ""

    def is_busy(self):
        return self._thread is not None

    def submit(self, name, func, *args, on_done=None, **kwargs):
        """Start `func(*args, **kwargs)` in the worker; False (and nothing started) when a job
        is already running."""
        if self.is_busy():
            return False
        self._cancel_flag = threading.Event()
        self._on_done = on_done
        self.current_name = name
        thread = _JobThread(self.bridge, self._cancel_flag, func, args, kwargs, parent=self)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self.started.emit(name)
        thread.start()
        return True

    def cancel(self):
        """Ask the running job to stop: at its next prompt, or right now if it is waiting on
        one. A long call in progress (an LLM request, a mailbox fetch) is not interrupted."""
        if self._thread is None or self._cancel_flag is None:
            return
        self._cancel_flag.set()
        ui = self._thread.ui
        pending = ui.pending if ui is not None else None
        if pending is not None:
            pending.cancel()

    def wait(self, milliseconds):
        """Block until the worker thread has ended; True if it has (or none was running)."""
        return self._thread.wait(milliseconds) if self._thread is not None else True

    def _on_thread_finished(self):
        thread = self._thread
        if thread is None:
            return
        self._thread = None
        on_done, self._on_done = self._on_done, None
        kind, payload = thread.outcome
        thread.deleteLater()
        if kind == "finished":
            if on_done is not None:
                on_done(payload)
            self.finished.emit(payload)
        elif kind == "cancelled":
            self.cancelled.emit()
        else:
            type_name, message, trace = payload
            self.failed.emit(f"{type_name}: {message}", trace)
