"""The bridge between a core flow running in a worker thread and the Qt GUI thread.

`QtUI` is the UI port implementation the worker uses: every prompt becomes a `UIRequest`
emitted through `Bridge.request_ready` (a queued signal, so the slot runs on the GUI
thread), and the worker blocks on the request's `threading.Event` until the GUI answers or
cancels it. `echo` and log records go the same way, without blocking. `EchoStream` stands in
for sys.stdout during a job, so what third-party code prints (socialModules, display_posts)
lands in the log panel too.
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass, field

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal

from manage_agenda.exceptions import UserCancelled
from manage_agenda.i18n import t


@dataclass
class UIRequest:
    """One question from the worker to the GUI: `kind` is the port method's name, `payload`
    its keyword arguments. The GUI calls answer() or cancel(); the worker waits on `done`."""

    kind: str
    payload: dict
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    cancelled: bool = False

    def answer(self, result):
        self.result = result
        self.done.set()

    def cancel(self):
        self.cancelled = True
        self.done.set()


class Bridge(QObject):
    """Signals from the worker to the GUI thread. Created on the GUI thread, connected with
    Qt.QueuedConnection: the emitter is the worker."""

    request_ready = Signal(object)  # UIRequest
    echo_line = Signal(str)  # one line for the log panel
    log_record = Signal(str, int)  # formatted logging record, level number


def on_gui_thread():
    """Whether the caller runs on the application's (GUI) thread."""
    app = QCoreApplication.instance()
    return app is not None and QThread.currentThread() is app.thread()


class QtUI:
    """The UI port for a core flow running in a worker thread. One instance per job."""

    def __init__(self, bridge: Bridge, cancel_flag: threading.Event):
        self.bridge = bridge
        self.cancel_flag = cancel_flag
        self.pending: UIRequest | None = None

    def _ask(self, kind, **payload):
        if self.cancel_flag.is_set():
            raise UserCancelled()
        if on_gui_thread():
            # A queued signal to the thread that is already here would wait for itself.
            raise RuntimeError(t("gui.port_called_outside_job"))
        request = UIRequest(kind, payload)
        self.pending = request
        try:
            self.bridge.request_ready.emit(request)
            request.done.wait()
        finally:
            self.pending = None
        if request.cancelled or self.cancel_flag.is_set():
            raise UserCancelled()
        return request.result

    def choose_one(self, options, title="", identifier=None, default=None):
        options = list(options)
        if not options:
            # As interactive.select_one: nothing to choose from, nothing to ask.
            return None
        return self._ask(
            "choose_one", options=options, title=title, identifier=identifier, default=default
        )

    def choose_many(self, options, title="", identifier=None):
        options = list(options)
        if not options:
            return []
        return self._ask("choose_many", options=options, title=title, identifier=identifier)

    def choose_action(self, actions, prompt_text, default=""):
        return self._ask(
            "choose_action", actions=list(actions), prompt_text=prompt_text, default=default
        )

    def confirm(self, text, default=False):
        return self._ask("confirm", text=text, default=default)

    def ask_text(self, text, default=""):
        return self._ask("ask_text", text=text, default=default)

    def ask_multiline(self, text):
        return self._ask("ask_multiline", text=text)

    def review_event(self, event, label="", context=None):
        return self._ask("review_event", event=event, label=label, context=context or {})

    def select_events(self, events, labels, title="", prompt_text="", render=None):
        # `render` prints the list on a terminal; the dialog shows `labels` instead.
        return self._ask(
            "select_events",
            events=list(events),
            labels=list(labels),
            title=title,
            prompt_text=prompt_text,
        )

    def echo(self, *parts, sep=" ", end="\n", flush=False):
        self.bridge.echo_line.emit(sep.join(str(part) for part in parts))


class EchoStream(io.TextIOBase):
    """A text stream whose complete lines go to `ui.echo`: what sys.stdout is replaced with
    while a job runs."""

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self._buffer = ""

    def writable(self):
        return True

    def write(self, text):
        self._buffer += str(text)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.ui.echo(line)
        return len(text)

    def flush(self):
        if self._buffer:
            self.ui.echo(self._buffer)
            self._buffer = ""
