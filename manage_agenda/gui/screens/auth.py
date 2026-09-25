"""The `manage-agenda auth` check and the desktop OAuth consent, as the Accounts screen runs
them for a Google account (in the job runner)."""

from __future__ import annotations

import os

from manage_agenda.connections import (
    complete_desktop_oauth,
    credential_path,
    describe_auth_failure,
)
from manage_agenda.i18n import t
from manage_agenda.ui import echo

SERVICES = ("gcalendar", "gmail")


def _connect(rules, key):
    return rules.readConfigSrc("", key, rules.more.get(key))


def check_auth(rules, key):
    """(authorized, message): what `manage-agenda auth` prints for account `key`."""
    api = _connect(rules, key)
    if api is not None and api.getClient():
        return True, t("cli.auth.authorized_success")
    return False, describe_auth_failure(api)


def run_oauth(rules, key):
    """Run the browser consent for account `key`, as `manage-agenda auth` does when the
    OAuth client file exists: (authorized, message)."""
    api = _connect(rules, key)
    if api is not None and api.getClient():
        return True, t("cli.auth.authorized_success")
    if api is None or not os.path.isfile(credential_path(api)):
        return False, "\n".join(
            [describe_auth_failure(api), "", t("cli.auth.create_oauth_client_instructions")]
        )
    echo(t("cli.auth.opening_browser"))
    if complete_desktop_oauth(api):
        return True, t("cli.auth.authorized_success")
    return False, describe_auth_failure(api)
