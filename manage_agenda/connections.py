"""Select configured external-service connections."""

import logging
import os
import pickle

from socialModules.configMod import safe_get, select_from_list
from socialModules.moduleRules import moduleRules

from manage_agenda.exceptions import CalendarError
from manage_agenda.interactive import select_many, select_one


def authorize(args, rules=None):
    """Authorize and return a configured service connection."""
    rules = rules or moduleRules.from_config()
    if args.interactive:
        print("Choose the Google service to authorize.")
        print("  gcalendar — write events to Google Calendar (required by add)")
        print("  gmail     — read a Gmail mailbox")
        _choice, service = select_from_list(
            ["gcalendar", "gmail"],
            title="Google service",
            default="gcalendar",
        )
        return rules.selectRuleInteractive(service, title="Account")

    rules_all = rules.selectRule("", "")
    if not rules_all:
        logging.warning("No services configured.")
        return None
    source_name = rules_all[0]
    source_details = rules.more.get(source_name, {})
    logging.info(f"Source: {source_name} - {source_details}")
    return rules.readConfigSrc("", source_name, source_details)


def prepare_calendar(args, rules=None, config_path=None):
    """Select the destination calendar(s) once, before any model call.

    Precedence: -d/--destination (a single raw calendar id, a one-off override - the same
    convention copy/move/clean already use for this flag) > saved user config (a list, "one,
    the other, or both") > interactive wizard (checkbox) > a clear error when none of those
    apply. --reconfigure re-opens the wizard even when a config is already saved; whatever is
    picked interactively is then saved for next time.
    """
    if getattr(args, "output", "calendar") != "calendar":
        return True
    if getattr(args, "calendar_api", None) and getattr(args, "calendar_ids", None):
        return True

    from manage_agenda.user_config import load_user_config, saved_calendar_ids, update_user_config

    rules = rules or moduleRules.from_config()
    saved = load_user_config(config_path)
    reconfigure = getattr(args, "reconfigure", False)
    explicit_calendar = getattr(args, "destination", None)
    account_name = saved.get("calendar_account")

    if reconfigure or not account_name:
        api = select_api(args, "gcalendar", rules=rules, title="Select Calendar")
    else:
        api = rules.readConfigSrc("", account_name, rules.more.get(account_name, {}))

    if api is None or api.getClient() is None:
        # A calendar id resolved from a flag or saved config is only usable together with a
        # working account connection - checked here too, not just inside select_calendars(),
        # since a resolved calendar id skips that call entirely below.
        print(missing_calendar_message(api))
        return False

    if explicit_calendar:
        calendar_ids = [explicit_calendar]
    elif not reconfigure:
        calendar_ids = saved_calendar_ids(saved)
    else:
        calendar_ids = []

    prompted = False
    if not calendar_ids:
        try:
            calendar_ids = select_calendars(api, title="Select calendar(s)", args=args)
        except CalendarError as error:
            print(error)
            return False
        prompted = True

    if not calendar_ids:
        print(missing_calendar_message(api))
        return False

    args.calendar_api = api
    args.calendar_ids = calendar_ids
    args.calendar_id = calendar_ids[0]

    if prompted and not explicit_calendar:
        update_user_config(
            {"calendar_account": getattr(api, "src", account_name), "calendar": calendar_ids},
            config_path,
        )
    return True


def select_api(args, api_type, rules=None, title=""):
    """Select a configured service connection, interactively or not."""
    rules = rules or moduleRules.from_config()
    service = ["gmail", "imap"] if api_type == "email" else (
        list(api_type) if isinstance(api_type, (list, tuple)) else [api_type]
    )

    if args.interactive:
        return rules.selectRuleInteractive(service, title=title)

    sources = rules.selectRule(service, "")
    if not sources:
        logging.warning(f"No {api_type} sources configured.")
        return None
    selected_source = sources[0]
    source_details = rules.more.get(selected_source, {})
    logging.info(f"Source: {selected_source} - {source_details}")
    return rules.readConfigSrc("", selected_source, source_details)


def credential_path(api_src):
    """Path where socialModules looks for the OAuth client JSON."""
    if api_src is None:
        return ""
    try:
        server = api_src.getServer()
        nick = api_src.getNick()
        if server and nick:
            return api_src.confName((server, nick))
    except Exception:
        return ""
    return ""


def describe_auth_failure(api_src):
    """Say why authorization stopped, including the library or Google error when there is one."""
    import json

    expected = credential_path(api_src)
    if not expected:
        return "The OAuth client file path could not be determined."

    lines = [f"Expected credentials file: {expected}"]
    if not os.path.exists(expected):
        lines.append("That file does not exist, so Google was not contacted.")
        folder = os.path.dirname(expected)
        name = os.path.basename(expected)
        neighbor = os.path.join(folder, name[1:] if name.startswith(".") else name)
        if name.startswith(".") and os.path.isfile(neighbor):
            lines.append(f"A file with the same name, without the leading dot, is here: {neighbor}")
            lines.append("The program only reads the name that starts with a dot.")
        else:
            lines.append("No client JSON was found under that name.")
        return "\n".join(lines)

    try:
        with open(expected, encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as error:
        lines.append(f"The file cannot be read: {type(error).__name__}: {error}")
        return "\n".join(lines)

    if isinstance(payload, dict) and "web" in payload and "installed" not in payload:
        lines.append(
            "Google client type is 'web'. This program needs a Desktop app client, "
            "whose JSON starts with \"installed\"."
        )
        return "\n".join(lines)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        InstalledAppFlow.from_client_secrets_file(expected, scopes=["openid"])
    except Exception as error:
        lines.append(f"Google client library rejected the file: {type(error).__name__}: {error}")
        return "\n".join(lines)

    lines.append(
        "The client file is readable, but the browser consent did not finish "
        "and no token was saved."
    )
    return "\n".join(lines)


def complete_desktop_oauth(api_src):
    """Run the browser consent and save the token. Print the Google or library error."""
    path = credential_path(api_src)
    if not path or not os.path.isfile(path) or api_src is None:
        return False
    scopes = getattr(api_src, "scopes", None) or [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(path, scopes=scopes)
        credentials = flow.run_local_server(port=0)
    except Exception as error:
        print(f"{type(error).__name__}: {error}")
        return False
    token_path = api_src.confTokenName((api_src.getServer(), api_src.getNick()))
    with open(token_path, "wb") as handle:
        pickle.dump(credentials, handle)
    os.chmod(token_path, 0o600)
    print(f"Google token saved: {token_path}")
    return True


def missing_calendar_message(calendar_api=None):
    """Explain how to authorize Google Calendar when no client is available."""
    user = ""
    if calendar_api is not None:
        user = getattr(calendar_api, "user", "") or ""
    credential = "~/.mySocial/config/.Gcalendar_<server>_<name>.json"
    if "@" in user:
        nick, _, server = user.rpartition("@")
        credential = f"~/.mySocial/config/.Gcalendar_{server}_{nick}.json"
    account = f" for {user}" if user else ""
    return (
        f"Google Calendar is not authorized{account}.\n"
        "Create an OAuth desktop client in Google Cloud, with the Calendar API enabled, "
        f"and save the downloaded JSON as:\n  {credential}\n"
        "Then run: uv run manage-agenda auth -i"
    )


def _eligible_calendars(calendar_api):
    """Writable calendars on this account, or raise a CalendarError explaining why not."""
    if calendar_api is None or calendar_api.getClient() is None:
        raise CalendarError(missing_calendar_message(calendar_api))
    calendar_api.setCalendarList()
    calendars = calendar_api.getCalendarList()
    if not calendars:
        raise CalendarError("No calendars found in your Google Calendar account")

    eligible_calendars = [
        calendar for calendar in calendars if "reader" not in calendar.get("accessRole", "")
    ]
    if not eligible_calendars:
        raise CalendarError("No writable calendars found. Check your calendar permissions.")
    return eligible_calendars


def _should_prompt_for_calendar(args):
    """Prompt (a bulleted list or checkbox) when `args.interactive` or `args.reconfigure` is
    set, or when no `args` is given at all - callers outside the CLI (events.py's
    clean/copy/move flow) have always prompted unconditionally here."""
    return not args or getattr(args, "interactive", False) or getattr(args, "reconfigure", False)


_NON_INTERACTIVE_MESSAGE = (
    "No calendar configured for non-interactive use. Run with -i once (or --reconfigure) to "
    "choose one, or pass -d/--destination with a calendar id."
)


def select_calendar(calendar_api, title="", args=None):
    """Select a single writable Google Calendar from a configured calendar API.

    Otherwise there is nothing to silently guess: the caller is expected to have already
    resolved a calendar id via saved config or an explicit flag before reaching this point,
    so this raises a clear, actionable error instead of prompting.
    """
    try:
        eligible_calendars = _eligible_calendars(calendar_api)
        if not _should_prompt_for_calendar(args):
            raise CalendarError(_NON_INTERACTIVE_MESSAGE)

        chosen = select_one(eligible_calendars, title=title, identifier="summary")
        if chosen is None:
            raise CalendarError("No calendar was selected.")

        calendar_id = chosen["id"]
        logging.info(f"Selected calendar: {safe_get(chosen, ['summary'])} (ID: {calendar_id})")
        return calendar_id
    except (KeyError, IndexError, TypeError) as error:
        raise CalendarError(f"Failed to select calendar: {error}") from error
    except CalendarError:
        raise
    except Exception as error:
        raise CalendarError(f"Unexpected error selecting calendar: {error}") from error


def select_calendars(calendar_api, title="", args=None):
    """Select one or more writable Google Calendars - checkbox multi-select ("one, the other,
    or both"), used where a single run can write its events to more than one calendar."""
    try:
        eligible_calendars = _eligible_calendars(calendar_api)
        if not _should_prompt_for_calendar(args):
            raise CalendarError(_NON_INTERACTIVE_MESSAGE)

        chosen = select_many(eligible_calendars, title=title, identifier="summary")
        if not chosen:
            raise CalendarError("No calendar was selected.")

        calendar_ids = [item["id"] for item in chosen]
        logging.info(f"Selected calendars: {[safe_get(item, ['summary']) for item in chosen]} (IDs: {calendar_ids})")
        return calendar_ids
    except (KeyError, IndexError, TypeError) as error:
        raise CalendarError(f"Failed to select calendar: {error}") from error
    except CalendarError:
        raise
    except Exception as error:
        raise CalendarError(f"Unexpected error selecting calendar: {error}") from error
