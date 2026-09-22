"""Shared connection helpers for the probe scripts. Not part of the application."""

import argparse
import sys

from socialModules.moduleRules import moduleRules

from manage_agenda.sources import Args


def connect_calendar(calendar_id):
    """Interactively pick a Google Calendar account and return its authenticated client."""
    from manage_agenda.connections import select_api

    args = Args(interactive=True)
    rules = moduleRules.from_config()
    api_dst = select_api(args, "gcalendar", rules=rules, title="Select the TEST calendar's account")
    if api_dst is None or api_dst.getClient() is None:
        print("Could not authenticate a Google Calendar account. Run `manage-agenda auth -i` first.")
        sys.exit(1)
    return api_dst.getClient()


def connect_imap(account_name):
    """Read the named IMAP/Gmail account from socialModules config and return its api_src."""
    rules = moduleRules.from_config()
    source_details = rules.more.get(account_name, {})
    if not source_details and account_name not in (rules.more or {}):
        print(f"No configured account named {account_name!r}. Check your socialModules config.")
        sys.exit(1)
    return rules.readConfigSrc("", account_name, source_details)


def base_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Actually perform the mutating steps. Without this, only print the plan.",
    )
    return parser


def confirm_or_dry_run(yes, action_description):
    """Print what's about to happen. Return True if the caller should proceed."""
    print(f"--- {action_description}")
    if not yes:
        print("    (dry run - pass --yes to actually do this)")
        return False
    return True
