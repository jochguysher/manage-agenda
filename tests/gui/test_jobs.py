"""JobRunner: one job at a time in a QThread, outcome reported on the GUI thread."""

from manage_agenda.exceptions import UserCancelled
from manage_agenda.gui.bridge import Bridge
from manage_agenda.gui.jobs import JobRunner
from manage_agenda.ui import echo, get_ui


class _Recorder:
    def __init__(self, runner):
        self.events = []
        runner.started.connect(lambda name: self.events.append(("started", name)))
        runner.finished.connect(lambda result: self.events.append(("finished", result)))
        runner.failed.connect(lambda summary, trace: self.events.append(("failed", summary)))
        runner.cancelled.connect(lambda: self.events.append(("cancelled",)))

    def ended(self):
        return len(self.events) >= 2


def test_finished_with_the_flows_return_value_and_on_done(qapp, pump):
    runner = JobRunner(Bridge())
    recorder = _Recorder(runner)
    done = []

    assert runner.submit("job", lambda a, b=0: a + b, 40, b=2, on_done=done.append)
    assert runner.is_busy()
    assert pump(recorder.ended)
    assert recorder.events == [("started", "job"), ("finished", 42)]
    assert done == [42]
    assert not runner.is_busy()


def test_a_second_submit_while_busy_is_refused(qapp, pump):
    import threading

    runner = JobRunner(Bridge())
    recorder = _Recorder(runner)
    release = threading.Event()
    assert runner.submit("slow", release.wait, 5)
    assert runner.submit("second", lambda: None) is False
    release.set()
    assert pump(recorder.ended)
    assert runner.submit("third", lambda: "ok")
    assert pump(lambda: len(recorder.events) >= 4)


def test_an_exception_is_reported_with_its_type_and_message(qapp, pump):
    runner = JobRunner(Bridge())
    recorder = _Recorder(runner)

    def boom():
        raise ValueError("bad input")

    runner.submit("job", boom)
    assert pump(recorder.ended)
    assert recorder.events[1] == ("failed", "ValueError: bad input")


def test_user_cancelled_becomes_the_cancelled_signal(qapp, pump):
    runner = JobRunner(Bridge())
    recorder = _Recorder(runner)

    def backs_out():
        raise UserCancelled()

    runner.submit("job", backs_out)
    assert pump(recorder.ended)
    assert recorder.events[1] == ("cancelled",)


def test_the_qt_ui_port_and_stdout_are_installed_only_during_the_job(qapp, pump):
    from manage_agenda.gui.bridge import QtUI

    bridge = Bridge()
    lines = []
    bridge.echo_line.connect(lines.append)
    runner = JobRunner(bridge)
    recorder = _Recorder(runner)
    seen = {}

    def flow():
        seen["ui"] = type(get_ui()).__name__
        echo("through the port")
        print("through stdout", end="")
        return "done"

    before = get_ui()
    runner.submit("job", flow)
    assert pump(recorder.ended)
    assert seen["ui"] == QtUI.__name__
    assert pump(lambda: lines == ["through the port", "through stdout"])
    assert get_ui() is before


def test_cancel_releases_a_pending_prompt(qapp, pump):
    bridge = Bridge()
    requests = []
    bridge.request_ready.connect(requests.append)
    runner = JobRunner(bridge)
    recorder = _Recorder(runner)

    runner.submit("job", lambda: get_ui().confirm("?"))
    assert pump(lambda: bool(requests))
    runner.cancel()
    assert pump(recorder.ended)
    assert recorder.events[1] == ("cancelled",)
    assert requests[0].cancelled
