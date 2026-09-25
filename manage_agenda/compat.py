"""Run-time adjustments to socialModules, installed once by install_socialmodules_shims().

IMAP port. moduleImap.makeConnection() connects with IMAP4_SSL on port 993, hardcoded. A
local bridge listens elsewhere - Proton Mail Bridge serves IMAP on 127.0.0.1:1143 - so an
account's `.rssImap` section may carry `port = 1143`, the key moduleSmtp already reads from
its own config, and the shim connects there; without the key, 993 as before. Worth an
upstream change (fernand0/socialModules); until then this keeps the tool working from a plain
install of the library instead of a hand-edited copy of it.

The shims are installed by manage_agenda.connections at import, idempotently, before any
account is connected.
"""

from __future__ import annotations

import functools
import imaplib
import logging
import ssl

logger = logging.getLogger(__name__)

IMAP_DEFAULT_PORT = 993
_MARK = "_manage_agenda_shim"


def imap_port_from_config(config, section):
    """The `port` of `.rssImap` section `section`, or IMAP_DEFAULT_PORT."""
    try:
        value = config.get(section, "port", fallback="")
    except Exception:  # noqa: BLE001 - a malformed section is the caller's problem, not ours
        value = ""
    value = str(value or "").strip()
    return int(value) if value.isdigit() and 0 < int(value) < 65536 else IMAP_DEFAULT_PORT


def _wrap_get_keys(original):
    @functools.wraps(original)
    def getKeys(self, config):  # noqa: N802 - socialModules' name
        # self.user is the section name here; the original replaces it with the login.
        port = imap_port_from_config(config, self.user)
        result = original(self, config)
        self.port = port
        return result

    setattr(getKeys, _MARK, True)
    return getKeys


def _make_connection(self, SERVER, USER, PASSWORD):  # noqa: N803 - socialModules' names
    """moduleImap.makeConnection() with the port getKeys() read: IMAP4_SSL, then login. A
    failure raises; socialModules' initApi() catches anything there and the account ends
    with no client, exactly as after the original's sys.exit()."""
    port = getattr(self, "port", IMAP_DEFAULT_PORT)
    logger.info(f"IMAP connection: {USER} at {SERVER}:{port}")
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    client = imaplib.IMAP4_SSL(SERVER, port, ssl_context=context)
    client.login(USER, PASSWORD)
    return client


setattr(_make_connection, _MARK, True)


def install_socialmodules_shims():
    """Install the shims on socialModules' classes; a second call changes nothing."""
    from socialModules.moduleImap import moduleImap

    if not getattr(moduleImap.getKeys, _MARK, False):
        moduleImap.getKeys = _wrap_get_keys(moduleImap.getKeys)
    if not getattr(moduleImap.makeConnection, _MARK, False):
        moduleImap.makeConnection = _make_connection
