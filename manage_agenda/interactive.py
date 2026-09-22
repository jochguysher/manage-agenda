"""Interactive selection helpers with varied UX.

`select_from_list` (from socialModules, used throughout this codebase for account and model
selection) is a numbered-entry prompt. `select_one` adds an arrow-key bulleted list, and
`select_many` an arrow-key checkbox, both via `questionary`, so the setup wizard does not
present every choice the same way - falling back to a numbered prompt whenever questionary is
not usable (not installed, no TTY, cancelled), so headless runs and tests keep working
unchanged.
"""

import logging
import sys

import click
from socialModules.configMod import select_from_list

from manage_agenda.i18n import t

try:
    import questionary
except Exception:
    questionary = None


def _has_tty():
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def select_one(options, title="", identifier=None, default=None):
    """Bulleted single-select over `options`. Returns the chosen item itself, not its index.

    Items are shown (and matched back) via `identifier` when they are dicts, or as-is
    otherwise - the same convention `select_from_list` uses. Returns None if nothing was
    chosen (empty `options`, or the prompt was cancelled in both the primary and fallback UI).
    """
    if not options:
        return None
    labels = [
        item.get(identifier) if identifier and isinstance(item, dict) else item for item in options
    ]

    if questionary is not None and _has_tty():
        try:
            answer = questionary.select(title or "Select one", choices=labels, default=default).ask()
        except Exception as error:
            logging.debug(f"questionary selection failed, falling back: {error}")
            answer = None
        if answer is not None:
            return options[labels.index(answer)]

    selection, _name = select_from_list(
        options, identifier=identifier or "", title=title, default=default or ""
    )
    if selection is None or selection < 0 or selection >= len(options):
        return None
    return options[selection]


def select_many(options, title="", identifier=None):
    """Checkbox multi-select over `options` ("one, the other, or both"). Returns a list -
    possibly empty if nothing was chosen.

    Items are shown via `identifier` when they are dicts, or as-is otherwise - the same
    convention `select_one` uses. There is no multi-select in `select_from_list`, so the
    fallback here is a plain comma-separated numbered prompt instead, which needs no
    dependency and works without a terminal.
    """
    if not options:
        return []
    labels = [
        item.get(identifier) if identifier and isinstance(item, dict) else item for item in options
    ]

    if questionary is not None and _has_tty():
        try:
            answer = questionary.checkbox(title or "Select one or more", choices=labels).ask()
        except Exception as error:
            logging.debug(f"questionary multi-select failed, falling back: {error}")
            answer = None
        if answer is not None:
            return [options[labels.index(item)] for item in answer]

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
