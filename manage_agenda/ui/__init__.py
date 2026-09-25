"""The UI port: the one seam between manage-agenda's library code and whoever drives it.

Library code (sources, extraction, events, connections, llm, ...) never reads stdin or
writes stdout directly. Every question it asks goes through the current `UI` object's prompt
methods and every line it shows goes through `echo`. Three implementations exist:

- `manage_agenda.ui.console.ConsoleUI`, the default: the classic terminal behaviour
  (`input()`, questionary lists, `print`), so the CLI never notices the seam;
- `manage_agenda.ui.fake.ScriptedUI`: answers from a queue, for tests;
- `manage_agenda.gui.bridge.QtUI`: turns each prompt into a dialog on the GUI thread.

The current UI is process-global (`get_ui()` / `set_ui()` / `use_ui()`), not thread-local:
one flow runs at a time, and the GUI's job runner is the only place that enforces it. A
prompt method may raise `manage_agenda.exceptions.UserCancelled` (a BaseException, like
KeyboardInterrupt) when the user backs out; library code never catches it.

`tests/test_no_stdin_in_library.py` walks the package's AST and fails on any `input()`,
`click.prompt`, `select_from_list` or `selectRuleInteractive` call outside the console
implementation - the seam is enforced, not just documented.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Protocol

from manage_agenda.i18n import t


class UI(Protocol):
    """One method per kind of question the library asks. `ConsoleUI` (manage_agenda.ui.
    console) documents the exact terminal semantics each one reproduces."""

    def choose_one(self, options, title="", identifier=None, default=None) -> Any:
        """Pick one item of `options` (shown via `label_for`); the item itself, or None."""

    def choose_many(self, options, title="", identifier=None) -> list:
        """Pick any number of items of `options`; a (possibly empty) list of items."""

    def choose_action(self, actions, prompt_text, default="") -> str:
        """Pick one of `actions` ([(key, label), ...]) and return its key. The console
        returns the raw line typed at `prompt_text`, so callers keep their own mapping."""

    def confirm(self, text, default=False) -> bool:
        """A yes/no question."""

    def ask_text(self, text, default="") -> str:
        """One line of free text (the raw line, not stripped)."""

    def ask_multiline(self, text) -> str:
        """Several lines of free text; "" when nothing was entered."""

    def review_event(self, event, label="", context=None) -> tuple:
        """Let the user check and edit an extracted event's dates; (event, decision) with
        decision "accept" or "retry" (ask the LLM again). `context` names the source
        message (subject, sender, date, identifier - see describe_source()) so the person
        can find it and judge the extraction against it."""

    def select_events(self, events, labels, title="", prompt_text="", render=None) -> list:
        """Pick any number of `events` (shown as `labels`); a list of events."""

    def echo(self, *parts, sep=" ", end="\n", flush=False) -> None:
        """Show one line to the user. Same signature as print(), so library code's
        `print(...)` calls became `echo(...)` mechanically, keyword arguments included."""


def describe_source(context) -> str:
    """One line naming the message an event came from, built from whichever of `context`'s
    subject, sender, date and identifier the flow knew; "" when it knew none. What every UI
    shows next to an event under review."""
    context = context or {}
    parts = []
    if context.get("subject"):
        parts.append(t("events.review_source_subject", subject=context["subject"]))
    if context.get("sender"):
        parts.append(t("events.review_source_from", sender=context["sender"]))
    if context.get("date"):
        parts.append(t("events.review_source_date", date=context["date"]))
    if context.get("identifier"):
        parts.append(t("events.review_source_id", identifier=context["identifier"]))
    return t("events.review_source", details=" · ".join(parts)) if parts else ""


def describe_nature(context) -> str:
    """One line saying what a proposed event is when the tool made it up from the message
    rather than extracting it: a cleaning after a room occupation (extraction.event_nature()
    puts kind, room, occupied_from and occupied_to in `context`). "" for an extracted event."""
    context = context or {}
    if context.get("kind") != "cleaning":
        return ""
    first, last = context.get("occupied_from") or "", context.get("occupied_to") or ""
    room = context.get("room") or ""
    if first and first == last:
        text = t("events.review_nature_cleaning_day", room=room, day=first)
    else:
        text = t("events.review_nature_cleaning", room=room, first=first, last=last)
    if context.get("clean_before"):
        text += " " + t("events.review_nature_deadline", when=context["clean_before"])
    return text


def label_for(item, identifier=None) -> str:
    """The text a UI shows for `item`: `item[identifier]` for a dict, `item.identifier` for an
    object (Ollama's model list is pydantic objects with `.model`, Mistral's has `.id`), else
    `str(item)`. Always a string: a socialModules rule key is a tuple such as
    ("imap", "set", "me@host", "posts"), which questionary refuses as a choice."""
    if identifier:
        value = item.get(identifier) if isinstance(item, dict) else getattr(item, identifier, None)
        if value is not None:
            return str(value)
    return item if isinstance(item, str) else str(item)


_current: UI | None = None


def get_ui() -> UI:
    """The UI every prompt goes through; a ConsoleUI is created on first use when none was
    set (the console module is imported lazily: this package must stay importable without
    dragging the rest of the package in)."""
    global _current
    if _current is None:
        from manage_agenda.ui.console import ConsoleUI

        _current = ConsoleUI()
    return _current


def set_ui(ui: UI | None) -> None:
    """Install `ui` as the current UI; None goes back to the console default."""
    global _current
    _current = ui


@contextmanager
def use_ui(ui: UI):
    """Install `ui` for the duration of the block, then restore what was there before."""
    previous = _current
    set_ui(ui)
    try:
        yield ui
    finally:
        set_ui(previous)


def select_one(options, title="", identifier=None, default=None):
    """`get_ui().choose_one(...)`; kept as a module-level name so callers (and their tests)
    can bind it like the old `interactive.select_one`."""
    return get_ui().choose_one(options, title=title, identifier=identifier, default=default)


def select_many(options, title="", identifier=None):
    """`get_ui().choose_many(...)`; see select_one."""
    return get_ui().choose_many(options, title=title, identifier=identifier)


def echo(*parts, sep=" ", end="\n", flush=False):
    """`get_ui().echo(...)`: what library code calls instead of print()."""
    get_ui().echo(*parts, sep=sep, end=end, flush=flush)
