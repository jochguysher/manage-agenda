"""The configured accounts: the sections of socialModules' `~/.mySocial/config/.rssBlogs`
that manage-agenda selects from (gmail, imap, gcalendar), and the IMAP credentials kept in
`.rssImap` next to it.

socialModules only reads these files (moduleRules.checkRules, moduleContent's `.rss<Service>`
lookup); this module is their editor, for the desktop window's Accounts screen. The section
layout it writes is the one the file's own header describes:

    [name]
    url = <address>
    service = imap | gmail | gcalendar
    imap = <nick>              # the section name in .rssImap
    gmail = <address>          # the address that names the Google OAuth client file
    posts = posts
    hold = yes                 # a source stays visible without a publish destination
    folder, mode, mark, max_age_days, include_older, from   # IMAP only

`.rssBlogs` is edited block by block, as text: the header comments, every other section and
the keys this module does not know are kept verbatim. `.rssImap` holds passwords, so it is
parsed without interpolation and written with mode 0600.

Every reader/writer takes an optional `directory` so tests never touch the real files -
socialModules binds CONFIGDIR to the real home at import time, this module resolves
Path.home() fresh on every call (see scheduling.social_config_dir).
"""

from __future__ import annotations

import configparser
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from manage_agenda.i18n import t
from manage_agenda.scheduling import social_config_dir

SERVICES = ("gmail", "imap", "gcalendar")
GOOGLE_SERVICE_NAMES = {"gmail": "Gmail", "gcalendar": "Gcalendar"}
IMAP_MODES = ("auto", "review")
# The IMAP keys in the order the file's header lists them; `from` is present-but-empty on an
# account that must select nothing, so an empty value is written, never dropped.
IMAP_KEYS = ("folder", "mode", "mark", "max_age_days", "include_older", "from")
ACCOUNTS_FILE = ".rssBlogs"
IMAP_SECRETS_FILE = ".rssImap"
_SECTION_HEADER = re.compile(r"^\[(?P<name>[^\]]*)\]\s*$")
_NAME_FORBIDDEN = re.compile(r"[\[\]\r\n]")


class AccountError(ValueError):
    """An account that cannot be saved as given; str() is the message to show."""


@dataclass
class Account:
    name: str
    service: str
    address: str
    # Every other key of the section, in file order: posts, hold, the IMAP keys, and any key
    # this module does not know (since, before, processed_marker...), kept as they were.
    options: dict = field(default_factory=dict)

    @property
    def nick(self):
        """What the `<service> =` key holds: the .rssImap section for IMAP, the address for
        Google (moduleGoogle splits it into server and nick)."""
        return self.name if self.service == "imap" else self.address

    def items(self):
        """The (key, value) pairs of the section, in the order they are written."""
        pairs = [("url", self.address), ("service", self.service)]
        if self.service:
            pairs.append((self.service, self.nick))
        pairs.append(("posts", self.options.get("posts", "posts")))
        pairs.append(("hold", self.options.get("hold", "yes")))
        written = {key for key, _value in pairs}
        for key in IMAP_KEYS:
            if key in self.options and key not in written:
                pairs.append((key, self.options[key]))
                written.add(key)
        for key, value in self.options.items():
            if key not in written:
                pairs.append((key, value))
        return pairs

    def google_client_file(self, directory=None):
        """Where socialModules expects this Google account's OAuth client JSON
        (moduleGoogle.confName: `.<Service>_<server>_<nick>.json`), or None for IMAP or an
        address without an @."""
        service_name = GOOGLE_SERVICE_NAMES.get(self.service)
        if service_name is None or "@" not in self.address:
            return None
        nick, _at, server = self.address.rpartition("@")
        return _directory(directory) / f".{service_name}_{server}_{nick}.json"


def _directory(directory=None):
    return Path(directory) if directory else social_config_dir()


def accounts_file(directory=None):
    return _directory(directory) / ACCOUNTS_FILE


def imap_secrets_file(directory=None):
    return _directory(directory) / IMAP_SECRETS_FILE


# --- .rssBlogs, as blocks of text ---


def _split_blocks(text):
    """(preamble lines, [(section name, lines including the header)])."""
    preamble, blocks = [], []
    current = None
    for line in text.splitlines():
        header = _SECTION_HEADER.match(line)
        if header:
            current = [line]
            blocks.append((header.group("name"), current))
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    return preamble, blocks


def _render(account):
    lines = [f"[{account.name}]"]
    for key, value in account.items():
        value = str(value).strip()
        lines.append(f"{key} = {value}" if value else f"{key} =")
    lines.append("")
    return lines


def _join_blocks(preamble, blocks):
    lines = list(preamble)
    for _name, block_lines in blocks:
        block_lines = list(block_lines)
        while block_lines and not block_lines[-1].strip():
            block_lines.pop()
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block_lines)
    return "\n".join(lines).rstrip("\n") + "\n"


def _write_text(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None and path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(temporary, mode)
    temporary.replace(path)


def _read_text(path):
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _parse_section(name, lines):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string("\n".join(lines) + "\n")
    values = dict(parser.items(name)) if parser.has_section(name) else {}
    service = values.pop("service", "").strip()
    address = values.pop("url", "").strip()
    values.pop(service, None)
    return Account(name=name, service=service, address=address, options=values)


def load_accounts(directory=None):
    """Every section of .rssBlogs as an Account, in file order. A section socialModules would
    refuse (no url or service) is listed as it is, so the screen can show and fix it."""
    _preamble, blocks = _split_blocks(_read_text(accounts_file(directory)))
    accounts = []
    for name, lines in blocks:
        try:
            accounts.append(_parse_section(name, lines))
        except configparser.Error:
            accounts.append(Account(name=name, service="", address=""))
    return accounts


def validate_name(name, existing=(), previous_name=None):
    """The section name `name` may be written: not empty, no brackets, not configparser's
    reserved DEFAULT, and not another section's name (case-sensitive, as configparser is)."""
    if not name or name != name.strip():
        raise AccountError(t("accounts.error_name_required"))
    if _NAME_FORBIDDEN.search(name) or name.upper() == configparser.DEFAULTSECT:
        raise AccountError(t("accounts.error_name_invalid", name=name))
    if name != previous_name and name in existing:
        raise AccountError(t("accounts.error_name_duplicate", name=name))


def _validate(account, server, user, password, existing, previous_name, secrets):
    validate_name(account.name, existing, previous_name)
    if account.service not in SERVICES:
        raise AccountError(t("accounts.error_service_unknown", service=account.service))
    if not account.address or "\n" in account.address:
        raise AccountError(t("accounts.error_address_required"))
    for key, value in account.options.items():
        if "\n" in str(key) or "\n" in str(value):
            # configparser would read the second line as a continuation only if indented;
            # written flat, it would break the next checkRules().
            raise AccountError(t("accounts.error_multiline_value", name=key))
    if account.service in GOOGLE_SERVICE_NAMES and "@" not in account.address:
        raise AccountError(t("accounts.error_google_address"))
    if account.service == "imap":
        if not server:
            raise AccountError(t("accounts.error_imap_server_required"))
        if not user:
            raise AccountError(t("accounts.error_imap_user_required"))
        has_token = bool(previous_name) and secrets.has_option(previous_name, "token")
        if not password and not has_token:
            raise AccountError(t("accounts.error_imap_password_required"))
        mode = account.options.get("mode")
        if mode is not None and mode not in IMAP_MODES:
            raise AccountError(t("accounts.error_imap_mode", mode=mode))


# --- .rssImap ---


def _imap_secrets(directory=None):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(_read_text(imap_secrets_file(directory)))
    return parser


def _write_imap_secrets(parser, directory=None):
    """Write the password file only when its content changes: a Google account's save
    must not touch it."""
    lines = []
    for section in parser.sections():
        lines.append(f"[{section}]")
        lines.extend(f"{key} = {value}" for key, value in parser.items(section))
        lines.append("")
    path = imap_secrets_file(directory)
    text = "\n".join(lines)
    if text != _read_text(path):
        _write_text(path, text, mode=0o600)


def imap_credentials(name, directory=None):
    """The server and login of IMAP account `name` from .rssImap, for a form; never the
    password (`has_password` says whether one is stored)."""
    parser = _imap_secrets(directory)
    known = parser.has_section(name)
    return {
        "server": parser.get(name, "server", fallback="") if known else "",
        "port": parser.get(name, "port", fallback="") if known else "",
        "user": parser.get(name, "user", fallback="") if known else "",
        "has_password": known and parser.has_option(name, "token"),
    }


# --- the operations the Accounts screen runs ---


def save_account(account, password=None, previous_name=None, directory=None):
    """Add `account`, or replace the section `previous_name` with it (a rename moves the
    section, and the .rssImap section with it). `server` and `user` in account.options go
    to .rssImap, not to .rssBlogs; `password` replaces the stored one, None keeps it.
    Raises AccountError when the account cannot be written as given."""
    options = dict(account.options)
    server = str(options.pop("server", "") or "").strip()
    user = str(options.pop("user", "") or "").strip()
    port = str(options.pop("port", "") or "").strip()
    account = Account(account.name, account.service, account.address.strip(), options)
    preamble, blocks = _split_blocks(_read_text(accounts_file(directory)))
    existing = [name for name, _lines in blocks]
    secrets = _imap_secrets(directory)
    _validate(account, server, user, password, existing, previous_name, secrets)
    if account.service == "imap" and port and not (port.isdigit() and 0 < int(port) < 65536):
        raise AccountError(t("accounts.error_imap_port", port=port))

    if previous_name and previous_name != account.name and secrets.has_section(previous_name):
        if not secrets.has_section(account.name):
            secrets.add_section(account.name)
        for key, value in secrets.items(previous_name):
            secrets.set(account.name, key, value)
        secrets.remove_section(previous_name)
    if account.service == "imap":
        if not secrets.has_section(account.name):
            secrets.add_section(account.name)
        secrets.set(account.name, "server", server)
        secrets.set(account.name, "user", user)
        if port:
            # Read by manage_agenda.compat's IMAP shim (socialModules itself uses 993).
            secrets.set(account.name, "port", port)
        else:
            secrets.remove_option(account.name, "port")
        if password:
            secrets.set(account.name, "token", password)
    elif secrets.has_section(account.name):
        # The account is no longer IMAP: its credentials would only linger.
        secrets.remove_section(account.name)

    rendered = _render(account)
    replaced = False
    updated = []
    for name, lines in blocks:
        if name == previous_name:
            updated.append((account.name, rendered))
            replaced = True
        else:
            updated.append((name, lines))
    if not replaced:
        updated.append((account.name, rendered))
    _write_text(accounts_file(directory), _join_blocks(preamble, updated))
    _write_imap_secrets(secrets, directory)
    return account


def remove_account(name, directory=None):
    """Drop section `name` from .rssBlogs and .rssImap. A Google account's OAuth client and
    token files are left in place: they are the user's, and another section may share them.
    True when a section was removed."""
    preamble, blocks = _split_blocks(_read_text(accounts_file(directory)))
    kept = [(block_name, lines) for block_name, lines in blocks if block_name != name]
    removed = len(kept) != len(blocks)
    if removed:
        _write_text(accounts_file(directory), _join_blocks(preamble, kept))
    secrets = _imap_secrets(directory)
    if secrets.remove_section(name):
        _write_imap_secrets(secrets, directory)
        removed = True
    return removed


def import_google_client(account, source, directory=None):
    """Copy the OAuth client JSON `source` (downloaded from the Google Cloud console) to
    where socialModules looks for it; the target path. Raises AccountError when `source`
    is not such a file."""
    target = account.google_client_file(directory)
    if target is None:
        raise AccountError(t("accounts.error_google_address"))
    source = Path(source)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AccountError(
            t("accounts.error_google_client_invalid", file=source, error=error)
        ) from error
    if not isinstance(data, dict) or not ({"installed", "web"} & set(data)):
        raise AccountError(
            t("accounts.error_google_client_invalid", file=source, error="no 'installed' or 'web' key")
        )
    _write_text(target, source.read_text(encoding="utf-8"), mode=0o600)
    return target
