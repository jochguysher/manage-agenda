"""Select configured external-service connections."""

import logging
import os
import pickle

from socialModules.configMod import safe_get
from socialModules.moduleRules import moduleRules

from manage_agenda.exceptions import CalendarAccountChoiceRequired, CalendarError
from manage_agenda.i18n import t
from manage_agenda.ui import echo, get_ui, select_many, select_one

logger = logging.getLogger(__name__)


def select_rule_interactive(rules, service, title=""):
    """Let the user pick one configured socialModules account of `service` (a name, or a
    list of names) and connect it: what `rules.selectRuleInteractive()` did, minus its own
    terminal prompt, so the choice goes through the UI port like every other one.

    Returns the connected api object - or, as socialModules does, the bare rule key when
    readConfigSrc() gives nothing back - and None when nothing was chosen."""
    services = list(service) if isinstance(service, (list, tuple)) else [service]
    candidates = []
    for name in services:
        candidates.extend(rules.selectRule(name, "") or [])
    chosen = get_ui().choose_one(candidates, title=title)
    if chosen is None:
        return None
    echo(t("connections.selected_rule", rule=chosen))
    api = rules.readConfigSrc("", chosen, rules.more.get(chosen))
    return api or chosen


def authorize(args, rules=None):
    """Authorize and return a configured service connection."""
    rules = rules or moduleRules.from_config()
    if args.interactive:
        echo(t("connections.choose_service_to_authorize"))
        echo(t("connections.gcalendar_service_description"))
        echo(t("connections.gmail_service_description"))
        service = get_ui().choose_one(
            ["gcalendar", "gmail"],
            title=t("connections.google_service_title"),
            default="gcalendar",
        )
        if service is None:
            return None
        return select_rule_interactive(rules, service, title=t("connections.account_title"))

    rules_all = rules.selectRule("", "")
    if not rules_all:
        logger.warning("No services configured.")
        return None
    source_name = rules_all[0]
    source_details = rules.more.get(source_name, {})
    logger.info(f"Source: {source_name} - {source_details}")
    return rules.readConfigSrc("", source_name, source_details)


def calendar_account_key(src):
    """A socialModules rule key (tuple, list, or plain string) as the stable string that
    identifies a calendar account everywhere manage-agenda records one: ledger_migration.json,
    each ledger ref's `calendar_account`, and calendar_sync_tokens.json - None if `src` isn't a
    usable rule key."""
    if isinstance(src, (list, tuple)) and src:
        return "|".join(str(part) for part in src)
    if isinstance(src, str) and src:
        return src
    return None


def select_calendar_account(args, rules=None, config_path=None):
    """The calendar account for ledger maintenance (`migrate-ledger`, `reconcile`), set on
    `args.calendar_api` and returned - None when no account can be connected.

    `-i` (args.interactive) ALWAYS offers the choice, even with a calendar_account saved:
    migrating or reconciling another account's refs is exactly what -i is for. Without -i: the
    saved calendar_account `add` uses; with none saved, the only configured gcalendar account
    when there is exactly one; with several configured, nothing is guessed -
    CalendarAccountChoiceRequired is raised (its message asks for -i; the caller prints it
    and nothing else) before any account is connected (readConfigSrc can trigger OAuth, so
    "no Calendar call" means stopping before it, not just skipping getClient()). Never "the
    first configured account": ledger maintenance marks an account as migrated, and that must
    never land on an account picked by configuration order.

    Never writes the user config, unlike prepare_calendar(): choosing an account for one
    maintenance run must never change the account `add` publishes to. No destination
    calendar is chosen either - ledger maintenance works from the refs recorded in the ledger,
    never from args.calendar_ids."""
    from manage_agenda.user_config import load_user_config

    rules = rules or moduleRules.from_config()
    if args.interactive:
        api = select_api(args, "gcalendar", rules=rules, title=t("connections.select_calendar_title"))
    else:
        account_name = load_user_config(config_path).get("calendar_account")
        if isinstance(account_name, list):
            # See prepare_calendar(): config.yaml stores the rule-key tuple as a list.
            account_name = tuple(account_name)
        if not account_name:
            configured = list(rules.selectRule(["gcalendar"], "") or [])
            if len(configured) > 1:
                raise CalendarAccountChoiceRequired(
                    t(
                        "connections.calendar_account_choice_required",
                        accounts=", ".join(calendar_account_key(src) or str(src) for src in configured),
                    )
                )
            if configured:
                account_name = configured[0]
        if account_name:
            api = rules.readConfigSrc("", account_name, rules.more.get(account_name, {}))
        else:
            logger.warning("No gcalendar sources configured.")
            api = None
    if api is None or api.getClient() is None:
        echo(missing_calendar_message(api))
        return None
    args.calendar_api = api
    return api


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
    if isinstance(account_name, list):
        # A socialModules rule key is a tuple; config.yaml (yaml.safe_dump) stores it as a
        # list, which can't be used as the dict key rules.more is looked up by.
        account_name = tuple(account_name)

    if reconfigure or not account_name:
        api = select_api(args, "gcalendar", rules=rules, title=t("connections.select_calendar_title"))
    else:
        api = rules.readConfigSrc("", account_name, rules.more.get(account_name, {}))

    if api is None or api.getClient() is None:
        # A calendar id resolved from a flag or saved config is only usable together with a
        # working account connection - checked here too, not just inside select_calendars(),
        # since a resolved calendar id skips that call entirely below.
        echo(missing_calendar_message(api))
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
            calendar_ids = select_calendars(api, title=t("connections.select_calendars_title"), args=args)
        except CalendarError as error:
            echo(error)
            return False
        prompted = True

    if not calendar_ids:
        echo(missing_calendar_message(api))
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
        return select_rule_interactive(rules, service, title=title)

    sources = rules.selectRule(service, "")
    if not sources:
        logger.warning(f"No {api_type} sources configured.")
        return None
    selected_source = sources[0]
    source_details = rules.more.get(selected_source, {})
    logger.info(f"Source: {selected_source} - {source_details}")
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
        return t("connections.oauth_path_undetermined")

    lines = [t("connections.expected_credentials_file", expected=expected)]
    if not os.path.exists(expected):
        lines.append(t("connections.file_does_not_exist"))
        folder = os.path.dirname(expected)
        name = os.path.basename(expected)
        neighbor = os.path.join(folder, name[1:] if name.startswith(".") else name)
        if name.startswith(".") and os.path.isfile(neighbor):
            lines.append(t("connections.same_name_without_dot", neighbor=neighbor))
            lines.append(t("connections.only_reads_dot_name"))
        else:
            lines.append(t("connections.no_client_json_found"))
        return "\n".join(lines)

    try:
        with open(expected, encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as error:
        lines.append(
            t("connections.file_cannot_be_read", error_type=type(error).__name__, error=error)
        )
        return "\n".join(lines)

    if isinstance(payload, dict) and "web" in payload and "installed" not in payload:
        lines.append(t("connections.wrong_client_type"))
        return "\n".join(lines)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        InstalledAppFlow.from_client_secrets_file(expected, scopes=["openid"])
    except Exception as error:
        lines.append(
            t("connections.client_library_rejected", error_type=type(error).__name__, error=error)
        )
        return "\n".join(lines)

    lines.append(t("connections.consent_not_finished"))
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
        echo(f"{type(error).__name__}: {error}")
        return False
    token_path = api_src.confTokenName((api_src.getServer(), api_src.getNick()))
    with open(token_path, "wb") as handle:
        pickle.dump(credentials, handle)
    os.chmod(token_path, 0o600)
    echo(t("connections.google_token_saved", token_path=token_path))
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
    account = t("connections.for_account", user=user) if user else ""
    return t("connections.missing_calendar_message", account=account, credential=credential)


def _eligible_calendars(calendar_api):
    """Writable calendars on this account, or raise a CalendarError explaining why not."""
    if calendar_api is None or calendar_api.getClient() is None:
        raise CalendarError(missing_calendar_message(calendar_api))
    calendar_api.setCalendarList()
    calendars = calendar_api.getCalendarList()
    if not calendars:
        raise CalendarError(t("connections.no_calendars_found"))

    eligible_calendars = [
        calendar for calendar in calendars if "reader" not in calendar.get("accessRole", "")
    ]
    if not eligible_calendars:
        raise CalendarError(t("connections.no_writable_calendars_found"))
    return eligible_calendars


def _should_prompt_for_calendar(args):
    """Prompt (a bulleted list or checkbox) when `args.interactive` or `args.reconfigure` is
    set, or when no `args` is given at all - callers outside the CLI (events.py's
    clean/copy/move flow) have always prompted unconditionally here."""
    return not args or getattr(args, "interactive", False) or getattr(args, "reconfigure", False)


def select_calendar(calendar_api, title="", args=None):
    """Select a single writable Google Calendar from a configured calendar API.

    Otherwise there is nothing to silently guess: the caller is expected to have already
    resolved a calendar id via saved config or an explicit flag before reaching this point,
    so this raises a clear, actionable error instead of prompting.
    """
    try:
        eligible_calendars = _eligible_calendars(calendar_api)
        if not _should_prompt_for_calendar(args):
            raise CalendarError(t("connections.non_interactive_message"))

        chosen = select_one(eligible_calendars, title=title, identifier="summary")
        if chosen is None:
            raise CalendarError(t("connections.no_calendar_selected"))

        calendar_id = chosen["id"]
        logger.info(f"Selected calendar: {safe_get(chosen, ['summary'])} (ID: {calendar_id})")
        return calendar_id
    except (KeyError, IndexError, TypeError) as error:
        raise CalendarError(t("connections.failed_to_select_calendar", error=error)) from error
    except CalendarError:
        raise
    except Exception as error:
        raise CalendarError(t("connections.unexpected_error_selecting_calendar", error=error)) from error


def select_calendars(calendar_api, title="", args=None):
    """Select one or more writable Google Calendars - checkbox multi-select ("one, the other,
    or both"), used where a single run can write its events to more than one calendar."""
    try:
        eligible_calendars = _eligible_calendars(calendar_api)
        if not _should_prompt_for_calendar(args):
            raise CalendarError(t("connections.non_interactive_message"))

        chosen = select_many(eligible_calendars, title=title, identifier="summary")
        if not chosen:
            raise CalendarError(t("connections.no_calendar_selected"))

        calendar_ids = [item["id"] for item in chosen]
        logger.info(f"Selected calendars: {[safe_get(item, ['summary']) for item in chosen]} (IDs: {calendar_ids})")
        return calendar_ids
    except (KeyError, IndexError, TypeError) as error:
        raise CalendarError(t("connections.failed_to_select_calendar", error=error)) from error
    except CalendarError:
        raise
    except Exception as error:
        raise CalendarError(t("connections.unexpected_error_selecting_calendar", error=error)) from error
