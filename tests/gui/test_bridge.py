"""QtUI: a prompt made on a worker thread blocks until the GUI thread answers or cancels."""

import threading

import pytest

from manage_agenda.exceptions import UserCancelled
from manage_agenda.gui.bridge import Bridge, EchoStream, QtUI, UIRequest, on_gui_thread


class _Worker:
    """Runs one port call on a plain thread and records what came out of it."""

    def __init__(self, ui, method, *args, **kwargs):
        self.result = None
        self.error = None
        self.thread = threading.Thread(
            target=self._run, args=(ui, method, args, kwargs), daemon=True
        )

    def _run(self, ui, method, args, kwargs):
        try:
            self.result = getattr(ui, method)(*args, **kwargs)
        except BaseException as error:  # noqa: BLE001 - the test inspects it
            self.error = error

    def start(self):
        self.thread.start()
        return self

    def done(self):
        return not self.thread.is_alive()


def test_echo_stream_splits_complete_lines_and_flushes_the_rest():
    lines = []

    class _UI:
        def echo(self, *parts, **_kwargs):
            lines.append(" ".join(str(p) for p in parts))

    stream = EchoStream(_UI())
    stream.write("a\nb")
    stream.write("c\n\nd")
    assert lines == ["a", "bc", ""]
    stream.flush()
    assert lines == ["a", "bc", "", "d"]
    stream.flush()
    assert lines == ["a", "bc", "", "d"]


def test_a_prompt_from_a_worker_is_answered_on_the_gui_thread(qapp, pump):
    bridge = Bridge()
    received = []

    def answer(request):
        assert on_gui_thread()
        received.append(request)
        request.answer(request.payload["options"][1])

    bridge.request_ready.connect(answer)
    ui = QtUI(bridge, threading.Event())

    worker = _Worker(ui, "choose_one", ["a", "b"], title="pick").start()

    assert pump(worker.done)
    assert worker.error is None
    assert worker.result == "b"
    assert [r.kind for r in received] == ["choose_one"]
    assert received[0].payload["title"] == "pick"
    assert ui.pending is None


def test_cancelling_the_pending_request_raises_in_the_worker(qapp, pump):
    bridge = Bridge()
    requests = []
    bridge.request_ready.connect(requests.append)
    ui = QtUI(bridge, threading.Event())

    worker = _Worker(ui, "confirm", "sure?").start()
    assert pump(lambda: bool(requests))
    assert ui.pending is requests[0]

    requests[0].cancel()
    assert pump(worker.done)
    assert isinstance(worker.error, UserCancelled)
    assert ui.pending is None


def test_a_set_cancel_flag_raises_before_asking(qapp):
    bridge = Bridge()
    asked = []
    bridge.request_ready.connect(asked.append)
    flag = threading.Event()
    flag.set()
    ui = QtUI(bridge, flag)

    with pytest.raises(UserCancelled):
        ui.ask_text("x")
    assert asked == []


def test_a_prompt_on_the_gui_thread_is_refused(qapp):
    ui = QtUI(Bridge(), threading.Event())
    with pytest.raises(RuntimeError):
        ui.confirm("would deadlock")


def test_empty_choices_do_not_open_a_dialog(qapp):
    ui = QtUI(Bridge(), threading.Event())
    # No worker thread needed: these return before any request is made.
    assert ui.choose_one([]) is None
    assert ui.choose_many([]) == []


def test_echo_and_log_signals_carry_text(qapp, pump):
    bridge = Bridge()
    lines = []
    bridge.echo_line.connect(lines.append)
    ui = QtUI(bridge, threading.Event())
    worker = _Worker(ui, "echo", "a", 1, sep="-", flush=True).start()
    assert pump(worker.done)
    assert pump(lambda: lines == ["a-1"])


def test_uirequest_answer_and_cancel_release_the_waiter():
    request = UIRequest("confirm", {})
    request.answer(True)
    assert request.done.is_set() and request.result is True and not request.cancelled
    other = UIRequest("confirm", {})
    other.cancel()
    assert other.done.is_set() and other.cancelled
