"""manage_agenda.accounts: the .rssBlogs / .rssImap editor behind the Accounts screen. Every
test writes under tmp_path (and conftest's fake HOME for the default location)."""

import configparser
import json
import stat

import pytest

from manage_agenda import accounts
from manage_agenda.accounts import Account, AccountError

HEADER = """# Accounts manage-agenda can select.
# `hold = yes` keeps a source visible even when it has no publish destination.

"""

SAMPLE = HEADER + """[royal-auto]
url = info@royal-up.com
service = imap
imap = royal-auto
posts = posts
hold = yes
folder = INBOX
mode = auto
mark = seen
max_age_days = 5
include_older = no
from =

[royal-review]
url = info@royal-up.com
service = imap
imap = royal-review
posts = posts
hold = yes
folder = INBOX
mode = review
mark = seen
max_age_days = 5
include_older = no
since = 2026-09-01
from = name:"Christine Fecteau"

[gcalendar]
url = me@gmail.com
service = gcalendar
gcalendar = me@gmail.com
posts = posts
hold = yes
"""

SECRETS = """[royal-auto]
server = imap.example.org
user = info@royal-up.com
token = s3cret%pass

[royal-review]
server = imap.example.org
user = info@royal-up.com
token = other
"""


@pytest.fixture
def config_dir(tmp_path):
    (tmp_path / ".rssBlogs").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / ".rssImap").write_text(SECRETS, encoding="utf-8")
    return tmp_path


def _sections(path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)
    return {section: dict(parser.items(section)) for section in parser.sections()}


def _imap(name="new", **options):
    base = {
        "server": "mail.example.org",
        "user": "someone",
        "folder": "INBOX",
        "mode": "auto",
        "mark": "seen",
        "max_age_days": "7",
        "include_older": "no",
        "from": "@example.org",
    }
    base.update(options)
    return Account(name, "imap", "someone@example.org", base)


def test_load_accounts_lists_every_section_in_file_order(config_dir):
    loaded = accounts.load_accounts(config_dir)
    assert [account.name for account in loaded] == ["royal-auto", "royal-review", "gcalendar"]
    auto, review, calendar = loaded
    assert auto.service == "imap" and auto.address == "info@royal-up.com" and auto.nick == "royal-auto"
    assert auto.options["from"] == "" and auto.options["mode"] == "auto"
    assert "imap" not in auto.options and "url" not in auto.options
    assert review.options["since"] == "2026-09-01"
    assert calendar.service == "gcalendar" and calendar.nick == "me@gmail.com"
    assert calendar.google_client_file(config_dir) == config_dir / ".Gcalendar_gmail.com_me.json"
    assert auto.google_client_file(config_dir) is None


def test_default_location_follows_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert accounts.accounts_file() == tmp_path / ".mySocial" / "config" / ".rssBlogs"
    assert accounts.load_accounts() == []


def test_save_new_imap_account_writes_both_files_and_keeps_the_rest(config_dir):
    accounts.save_account(_imap(), password="pw", directory=config_dir)
    text = (config_dir / ".rssBlogs").read_text(encoding="utf-8")
    assert text.startswith(HEADER)
    assert text.index("[royal-auto]") < text.index("[royal-review]") < text.index("[gcalendar]") < text.index("[new]")
    assert text.endswith(
        "[new]\nurl = someone@example.org\nservice = imap\nimap = new\nposts = posts\nhold = yes\n"
        "folder = INBOX\nmode = auto\nmark = seen\nmax_age_days = 7\ninclude_older = no\n"
        "from = @example.org\n"
    )
    sections = _sections(config_dir / ".rssBlogs")
    assert sections["royal-review"]["from"] == 'name:"Christine Fecteau"'
    assert "server" not in sections["new"] and "user" not in sections["new"]
    secrets = _sections(config_dir / ".rssImap")
    assert secrets["new"] == {"server": "mail.example.org", "user": "someone", "token": "pw"}
    assert secrets["royal-auto"]["token"] == "s3cret%pass"
    assert stat.S_IMODE((config_dir / ".rssImap").stat().st_mode) == 0o600


def test_save_creates_the_files_when_there_are_none(tmp_path):
    accounts.save_account(_imap(), password="pw", directory=tmp_path)
    assert _sections(tmp_path / ".rssBlogs")["new"]["service"] == "imap"
    assert _sections(tmp_path / ".rssImap")["new"]["token"] == "pw"


def test_edit_keeps_unknown_keys_and_the_stored_password(config_dir):
    review = accounts.load_accounts(config_dir)[1]
    review.options.update(accounts.imap_credentials("royal-review", config_dir))
    review.options.pop("has_password")
    review.options["folder"] = "Archive"
    review.options["from"] = ""
    accounts.save_account(review, password=None, previous_name="royal-review", directory=config_dir)
    text = (config_dir / ".rssBlogs").read_text(encoding="utf-8")
    assert "\nfrom =\n" in text
    sections = _sections(config_dir / ".rssBlogs")
    assert sections["royal-review"]["folder"] == "Archive"
    assert sections["royal-review"]["since"] == "2026-09-01"
    assert sections["royal-review"]["from"] == ""
    assert list(sections) == ["royal-auto", "royal-review", "gcalendar"]
    assert _sections(config_dir / ".rssImap")["royal-review"]["token"] == "other"
    assert text.count("[royal-review]") == 1 and text.startswith(HEADER)


def test_rename_moves_the_section_and_its_credentials(config_dir):
    auto = accounts.load_accounts(config_dir)[0]
    auto.name = "royal"
    auto.options.update(server="imap.example.org", user="info@royal-up.com")
    accounts.save_account(auto, previous_name="royal-auto", directory=config_dir)
    sections = _sections(config_dir / ".rssBlogs")
    assert list(sections) == ["royal", "royal-review", "gcalendar"]
    assert sections["royal"]["imap"] == "royal"
    secrets = _sections(config_dir / ".rssImap")
    assert "royal-auto" not in secrets and secrets["royal"]["token"] == "s3cret%pass"


def test_imap_credentials_never_return_the_password(config_dir):
    assert accounts.imap_credentials("royal-auto", config_dir) == {
        "server": "imap.example.org",
        "port": "",
        "user": "info@royal-up.com",
        "has_password": True,
    }
    assert accounts.imap_credentials("nope", config_dir) == {
        "server": "",
        "port": "",
        "user": "",
        "has_password": False,
    }


def test_imap_port_round_trips_through_the_password_file(config_dir):
    accounts.save_account(_imap(port="1143"), password="pw", directory=config_dir)
    assert _sections(config_dir / ".rssImap")["new"]["port"] == "1143"
    assert accounts.imap_credentials("new", config_dir)["port"] == "1143"
    assert "port" not in _sections(config_dir / ".rssBlogs")["new"]

    accounts.save_account(_imap(port=""), previous_name="new", directory=config_dir)
    assert "port" not in _sections(config_dir / ".rssImap")["new"]
    with pytest.raises(AccountError, match="port"):
        accounts.save_account(_imap(port="abc"), previous_name="new", directory=config_dir)
    with pytest.raises(AccountError, match="port"):
        accounts.save_account(_imap(port="70000"), previous_name="new", directory=config_dir)


def test_google_account_needs_no_credentials_file(config_dir):
    account = Account("mail", "gmail", "me@gmail.com")
    accounts.save_account(account, directory=config_dir)
    sections = _sections(config_dir / ".rssBlogs")
    assert sections["mail"] == {
        "url": "me@gmail.com",
        "service": "gmail",
        "gmail": "me@gmail.com",
        "posts": "posts",
        "hold": "yes",
    }
    assert "mail" not in _sections(config_dir / ".rssImap")


def test_saving_a_google_account_leaves_the_password_file_untouched(config_dir):
    secrets = config_dir / ".rssImap"
    before = (secrets.read_bytes(), secrets.stat().st_mtime_ns)
    accounts.save_account(Account("mail", "gmail", "me@gmail.com"), directory=config_dir)
    accounts.save_account(
        Account("gcalendar", "gcalendar", "other@gmail.com"), previous_name="gcalendar", directory=config_dir
    )
    assert (secrets.read_bytes(), secrets.stat().st_mtime_ns) == before


def test_switching_an_account_away_from_imap_drops_its_credentials(config_dir):
    accounts.save_account(
        Account("royal-auto", "gmail", "info@royal-up.com"), previous_name="royal-auto", directory=config_dir
    )
    assert "royal-auto" not in _sections(config_dir / ".rssImap")
    assert _sections(config_dir / ".rssBlogs")["royal-auto"]["service"] == "gmail"


@pytest.mark.parametrize(
    "account, password, previous, message",
    [
        (_imap(""), "pw", None, "name"),
        (_imap(" x"), "pw", None, "name"),
        (_imap("a[b]"), "pw", None, "section name"),
        (_imap("DEFAULT"), "pw", None, "section name"),
        (_imap("royal-auto"), "pw", None, "already exists"),
        (Account("x", "twitter", "a@b"), None, None, "Unknown service"),
        (Account("x", "gmail", ""), None, None, "address"),
        (Account("x", "gcalendar", "no-at"), None, None, "@"),
        (_imap(server=""), "pw", None, "server"),
        (_imap(user=""), "pw", None, "login"),
        (_imap(), None, None, "password"),
        (_imap(mode="weekly"), "pw", None, "mode"),
        (Account("x", "gmail", "a@b", {"since": "2026-09-01\n2026-10-01"}), None, None, "several lines"),
    ],
)
def test_save_refuses_an_account_it_cannot_write(config_dir, account, password, previous, message):
    before = (config_dir / ".rssBlogs").read_text(encoding="utf-8")
    with pytest.raises(AccountError, match=message):
        accounts.save_account(account, password=password, previous_name=previous, directory=config_dir)
    assert (config_dir / ".rssBlogs").read_text(encoding="utf-8") == before
    assert (config_dir / ".rssImap").read_text(encoding="utf-8") == SECRETS


def test_rename_may_keep_its_own_name(config_dir):
    auto = accounts.load_accounts(config_dir)[0]
    auto.options.update(server="s", user="u")
    accounts.save_account(auto, previous_name="royal-auto", directory=config_dir)
    assert _sections(config_dir / ".rssImap")["royal-auto"] == {"server": "s", "user": "u", "token": "s3cret%pass"}


def test_remove_account_drops_both_sections_and_keeps_google_files(config_dir):
    client = config_dir / ".Gcalendar_gmail.com_me.json"
    client.write_text("{}", encoding="utf-8")
    assert accounts.remove_account("royal-auto", config_dir)
    assert list(_sections(config_dir / ".rssBlogs")) == ["royal-review", "gcalendar"]
    assert "royal-auto" not in _sections(config_dir / ".rssImap")
    assert (config_dir / ".rssBlogs").read_text(encoding="utf-8").startswith(HEADER)
    assert accounts.remove_account("gcalendar", config_dir)
    assert client.is_file()
    assert not accounts.remove_account("gcalendar", config_dir)


def test_import_google_client_copies_a_client_json_into_place(config_dir, tmp_path):
    account = Account("gcalendar", "gcalendar", "me@gmail.com")
    source = tmp_path / "downloaded.json"
    source.write_text(json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8")
    target = accounts.import_google_client(account, source, config_dir)
    assert target == config_dir / ".Gcalendar_gmail.com_me.json"
    assert json.loads(target.read_text(encoding="utf-8")) == {"installed": {"client_id": "x"}}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600

    source.write_text('{"nope": 1}', encoding="utf-8")
    with pytest.raises(AccountError, match="not an OAuth client"):
        accounts.import_google_client(account, source, config_dir)
    source.write_text("not json", encoding="utf-8")
    with pytest.raises(AccountError, match="not an OAuth client"):
        accounts.import_google_client(account, source, config_dir)
    with pytest.raises(AccountError):
        accounts.import_google_client(Account("x", "imap", "a"), source, config_dir)


def test_written_files_round_trip_through_configparser_like_socialmodules(config_dir):
    accounts.save_account(_imap(**{"from": 'name:"A B" @x.org'}), password="p%w", directory=config_dir)
    reloaded = {account.name: account for account in accounts.load_accounts(config_dir)}
    assert reloaded["new"].options["from"] == 'name:"A B" @x.org'
    assert _sections(config_dir / ".rssImap")["new"]["token"] == "p%w"
