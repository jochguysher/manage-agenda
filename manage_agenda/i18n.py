"""Minimal i18n: an English/French message catalog with runtime language detection.

Not gettext: gettext needs compiled .mo files shipped as package data, and this project's
packaging (pyproject.toml) has no package-data setup for that. A plain dict needs no build
step and is simple enough to maintain for two languages.

Language is resolved lazily, on the first call to t() - which happens as soon as cli.py's
module body runs (its Click option `help=` strings call t() at decoration time), so --help
output is translated too, not just runtime prints. Once resolved it is cached for the rest of
the process; a later change to the saved config only takes effect on the next run.
"""

import logging
import os

SUPPORTED_LANGUAGES = ("en", "fr")
DEFAULT_LANGUAGE = "en"

_CURRENT_LANGUAGE = None


def _language_from_locale_string(value):
    """"fr_FR.UTF-8@euro" -> "fr". None/empty/"C"/"POSIX" -> None (no language signal)."""
    if not value:
        return None
    value = value.split(":")[0]  # LANGUAGE can be a colon-separated priority list
    value = value.split(".")[0].split("@")[0]
    value = value.replace("-", "_")
    primary = value.split("_")[0].strip().lower()
    if primary in ("", "c", "posix"):
        return None
    return primary


def detect_system_language():
    """LC_ALL, then LANG, then LANGUAGE - the precedence glibc uses for locale resolution."""
    for var in ("LC_ALL", "LANG", "LANGUAGE"):
        language = _language_from_locale_string(os.environ.get(var))
        if language:
            return language
    return None


def _resolve_language(config_path=None):
    """config.yaml's `language` (if set) overrides system detection, which overrides the
    English default."""
    try:
        from manage_agenda.user_config import load_user_config

        forced = load_user_config(config_path).get("language")
    except Exception as error:
        logging.debug(f"Could not read saved language: {error}")
        forced = None
    if forced:
        return str(forced).strip().lower()
    return detect_system_language() or DEFAULT_LANGUAGE


def get_language():
    """The active language, resolved and cached on first use. Always one of
    SUPPORTED_LANGUAGES - an unsupported or undetectable value falls back to English."""
    global _CURRENT_LANGUAGE
    if _CURRENT_LANGUAGE is None:
        _CURRENT_LANGUAGE = _resolve_language()
    if _CURRENT_LANGUAGE not in SUPPORTED_LANGUAGES:
        return DEFAULT_LANGUAGE
    return _CURRENT_LANGUAGE


def set_language(language):
    """Force the active language for the rest of the process. Used by tests, and available
    for any future explicit override; an unsupported value falls back to English."""
    global _CURRENT_LANGUAGE
    _CURRENT_LANGUAGE = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def reset_language_cache():
    """Forget the cached language, so the next t()/get_language() call resolves it again.
    Test-only: production never needs to re-resolve mid-process."""
    global _CURRENT_LANGUAGE
    _CURRENT_LANGUAGE = None


def t(key, **kwargs):
    """Translate `key` into the active language, formatting the result with `kwargs`.

    Falls back to English, then to the bare key, so a missing catalog entry or translation
    never crashes the program - it just shows untranslated (English, or the key itself) text.
    """
    from manage_agenda.messages import TRANSLATIONS

    catalog = TRANSLATIONS.get(key)
    if catalog is None:
        logging.debug(f"No translation catalog for key: {key}")
        text = key
    else:
        language = get_language()
        text = catalog.get(language) or catalog.get(DEFAULT_LANGUAGE) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError) as error:
            logging.warning(f"Translation formatting failed for {key!r}: {error}")
            return text
    return text
