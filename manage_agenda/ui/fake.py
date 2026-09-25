"""ScriptedUI: the UI port answered from a queue, for tests.

Shipped inside the package (not under tests/) so a test suite running against a
non-editable install, as CI does, can import it. Each scripted answer is a `(kind, answer)`
pair, `kind` being the port method's name; asking a different kind than the next scripted
one, or asking with an empty queue, fails the test loudly unless `lenient=True`, in which
case a neutral default answer is given (first option, nothing, no, "", accept). An answer
that is the UserCancelled class or an instance of it is raised instead of returned.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from manage_agenda.exceptions import UserCancelled


@dataclass
class Call:
    """One prompt the library made: which method, with which arguments."""

    kind: str
    payload: dict = field(default_factory=dict)


class ScriptedUI:
    """See the module docstring. `calls` is every prompt made, in order; `output` every
    line shown through `echo`."""

    def __init__(self, answers=(), lenient=False):
        self.answers = deque(answers)
        self.lenient = lenient
        self.calls: list[Call] = []
        self.output: list[str] = []

    def queue(self, kind, answer):
        """Append one scripted answer; returns self so calls can be chained."""
        self.answers.append((kind, answer))
        return self

    def assert_consumed(self):
        """Fail if scripted answers were left unused: the flow asked less than expected."""
        assert not self.answers, f"ScriptedUI: unconsumed answers: {list(self.answers)}"

    def _next(self, kind, payload, default):
        self.calls.append(Call(kind, payload))
        if not self.answers:
            if self.lenient:
                return default()
            raise AssertionError(f"ScriptedUI: no scripted answer for {kind}: {payload}")
        expected_kind, answer = self.answers.popleft()
        if expected_kind != kind:
            raise AssertionError(
                f"ScriptedUI: expected the flow to ask {expected_kind!r} next, "
                f"it asked {kind!r}: {payload}"
            )
        if answer is UserCancelled:
            raise UserCancelled()
        if isinstance(answer, UserCancelled):
            raise answer
        return answer

    @staticmethod
    def _is_index(value):
        return isinstance(value, int) and not isinstance(value, bool)

    def choose_one(self, options, title="", identifier=None, default=None):
        options = list(options)
        answer = self._next(
            "choose_one",
            {"options": options, "title": title, "identifier": identifier, "default": default},
            lambda: options[0] if options else None,
        )
        if self._is_index(answer):
            return options[answer]
        return answer

    def choose_many(self, options, title="", identifier=None):
        options = list(options)
        answer = self._next(
            "choose_many",
            {"options": options, "title": title, "identifier": identifier},
            list,
        )
        if isinstance(answer, (list, tuple)):
            return [options[item] if self._is_index(item) else item for item in answer]
        return answer

    def choose_action(self, actions, prompt_text, default=""):
        actions = list(actions)
        return self._next(
            "choose_action",
            {"actions": actions, "prompt_text": prompt_text, "default": default},
            lambda: default or (actions[0][0] if actions else ""),
        )

    def confirm(self, text, default=False):
        return bool(
            self._next("confirm", {"text": text, "default": default}, lambda: default)
        )

    def ask_text(self, text, default=""):
        return self._next("ask_text", {"text": text, "default": default}, lambda: default)

    def ask_multiline(self, text):
        return self._next("ask_multiline", {"text": text}, lambda: "")

    def review_event(self, event, label="", context=None):
        answer = self._next(
            "review_event",
            {"event": event, "label": label, "context": context},
            lambda: "accept",
        )
        if isinstance(answer, tuple):
            decision, edited = answer
            return edited, decision
        return event, answer

    def select_events(self, events, labels, title="", prompt_text="", render=None):
        events = list(events)
        answer = self._next(
            "select_events",
            {"events": events, "labels": list(labels), "title": title, "prompt_text": prompt_text},
            list,
        )
        if answer == "all":
            return events
        if isinstance(answer, (list, tuple)):
            return [events[item] if self._is_index(item) else item for item in answer]
        return answer

    def echo(self, *parts, sep=" ", end="\n", flush=False):
        self.output.append(sep.join(str(part) for part in parts))
