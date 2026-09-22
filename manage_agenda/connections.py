"""Select configured external-service connections."""

import logging
import os
import pickle

from socialModules.configMod import safe_get, select_from_list
from socialModules.moduleRules import moduleRules

from manage_agenda.exceptions import CalendarError


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


def prepare_calendar(args, rules=None):
    """Select the destination calendar once, before any model call."""
    if getattr(args, "output", "calendar") != "calendar":
        return True
    if getattr(args, "calendar_api", None) and getattr(args, "calendar_id", None):
        return True
    api = select_api(args, "gcalendar", rules=rules, title="Select Calendar")
    try:
        calendar_id = select_calendar(api, title="Select Calendar", args=args)
    except CalendarError as error:
        print(error)
        return False
    if not calendar_id:
        print(missing_calendar_message(api))
        return False
    args.calendar_api = api
    args.calendar_id = calendar_id
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


def select_calendar(calendar_api, title="", args=None):
    """Select a writable Google Calendar from a configured calendar API."""
    if calendar_api is None or calendar_api.getClient() is None:
        raise CalendarError(missing_calendar_message(calendar_api))
    try:
        calendar_api.setCalendarList()
        calendars = calendar_api.getCalendarList()
        if not calendars:
            raise CalendarError("No calendars found in your Google Calendar account")

        eligible_calendars = [
            calendar for calendar in calendars if "reader" not in calendar.get("accessRole", "")
        ]
        if not eligible_calendars:
            raise CalendarError("No writable calendars found. Check your calendar permissions.")

        if (args and args.interactive) or not args:
            selection, calendar = select_from_list(eligible_calendars, "summary", title=title)
        else:
            matches = [calendar for calendar in eligible_calendars if "kkk" in calendar["summary"]]
            calendar = matches[0] if matches else None
            selection = eligible_calendars.index(calendar)

        if selection < 0 or selection >= len(eligible_calendars):
            raise CalendarError(f"Invalid calendar selection: {selection}")

        calendar_id = eligible_calendars[selection]["id"]
        logging.info(f"Selected calendar: {safe_get(calendar, ['summary'])} (ID: {calendar_id})")
        return calendar_id
    except (KeyError, IndexError, TypeError) as error:
        raise CalendarError(f"Failed to select calendar: {error}") from error
    except CalendarError:
        raise
    except Exception as error:
        raise CalendarError(f"Unexpected error selecting calendar: {error}") from error
