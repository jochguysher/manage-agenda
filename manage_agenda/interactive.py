"""Interactive selection helpers with varied UX.

`select_from_list` (from socialModules, used throughout this codebase for account and model
selection) is a numbered-entry prompt. `select_one` adds an arrow-key bulleted list on top of
it via `questionary`, so the setup wizard does not present every choice the same way - falling
back to `select_from_list` whenever questionary is not usable (not installed, no TTY,
cancelled), so headless runs and tests keep working unchanged.
"""

import logging
import sys

from socialModules.configMod import select_from_list

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
