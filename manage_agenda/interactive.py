"""Terminal selection helpers with varied UX - the console side of the UI port.

`select_from_list` (from socialModules) is a numbered-entry prompt. `select_one` adds an
arrow-key bulleted list, and `select_many` an arrow-key checkbox, both via `questionary`, so
the setup wizard does not present every choice the same way - falling back to a numbered
prompt whenever questionary is not usable (not installed, no TTY, cancelled), so headless runs
and tests keep working unchanged.

Only `manage_agenda.ui.console.ConsoleUI` calls these two functions. Library code goes
through `manage_agenda.ui.select_one` / `select_many` (which dispatch to the current UI)
instead, so that a GUI can answer the same questions with a dialog - a rule
tests/test_no_stdin_in_library.py enforces.
"""

import logging
import sys

import click
from socialModules.configMod import select_from_list

from manage_agenda.i18n import t
from manage_agenda.ui import label_for

logger = logging.getLogger(__name__)

try:
    import questionary
except Exception:
    questionary = None


def _has_tty():
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _choices(labels):
    """questionary choices whose value is the option's index - two options with the same
    label (two calendars both called "Work") are told apart, and a non-string option (a
    socialModules rule key is a tuple) is shown as its label instead of being rejected."""
    return [questionary.Choice(title=label, value=index) for index, label in enumerate(labels)]


def _resolve(options, labels, answer):
    """The option behind a questionary answer: its index (a Choice value), or its label."""
    if isinstance(answer, bool):
        return None
    if isinstance(answer, int):
        return options[answer] if 0 <= answer < len(options) else None
    if answer in labels:
        return options[labels.index(answer)]
    return None


def select_one(options, title="", identifier=None, default=None):
    """Bulleted single-select over `options`. Returns the chosen item itself, not its index.

    Items are shown (and matched back) via `identifier` when they are dicts or objects, or
    as-is otherwise - see manage_agenda.ui.label_for. Returns None if nothing was chosen
    (empty `options`, or the prompt was cancelled in both the primary and fallback UI).
    """
    if not options:
        return None
    labels = [label_for(item, identifier) for item in options]

    if questionary is not None and _has_tty():
        try:
            default_index = labels.index(default) if default in labels else None
            answer = questionary.select(
                title or "Select one", choices=_choices(labels), default=default_index
            ).ask()
        except Exception as error:
            logger.debug(f"questionary selection failed, falling back: {error}")
            answer = None
        if answer is not None:
            chosen = _resolve(options, labels, answer)
            if chosen is not None:
                return chosen

    selection, _name = select_from_list(
        options, identifier=identifier or "", title=title, default=default or ""
    )
    if selection is None or selection < 0 or selection >= len(options):
        return None
    return options[selection]


def select_many(options, title="", identifier=None):
    """Checkbox multi-select over `options` ("one, the other, or both"). Returns a list -
    possibly empty if nothing was chosen.

    Items are shown via `identifier` when they are dicts or objects, or as-is otherwise -
    the same convention `select_one` uses. There is no multi-select in `select_from_list`, so
    the fallback here is a plain comma-separated numbered prompt instead, which needs no
    dependency and works without a terminal.
    """
    if not options:
        return []
    labels = [label_for(item, identifier) for item in options]

    if questionary is not None and _has_tty():
        try:
            answer = questionary.checkbox(
                title or "Select one or more", choices=_choices(labels)
            ).ask()
        except Exception as error:
            logger.debug(f"questionary multi-select failed, falling back: {error}")
            answer = None
        if answer is not None:
            chosen = [_resolve(options, labels, item) for item in answer]
            return [item for item in chosen if item is not None]

    return _select_many_fallback(options, labels, title)


def _select_many_fallback(options, labels, title):
    if title:
        click.echo(f"\n{title}")
    for index, label in enumerate(labels):
        click.echo(f"{index}) {label}")
    raw = click.prompt(t("interactive.comma_separated_selection"), default="", show_default=False)
    chosen = []
    for piece in raw.split(","):
        piece = piece.strip()
        if piece.isdigit() and 0 <= int(piece) < len(options):
            chosen.append(options[int(piece)])
    return chosen
