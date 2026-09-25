"""The Accounts screen and its dialog against a temporary .rssBlogs / .rssImap (the screen
is given the directory; the real ~/.mySocial is never read)."""

import json
from unittest.mock import patch

from manage_agenda import accounts
from manage_agenda.gui.bridge import Bridge
from manage_agenda.gui.jobs import JobRunner
from manage_agenda.gui.screens import accounts as accounts_screen
from manage_agenda.gui.screens.accounts import AccountDialog, AccountsScreen

SAMPLE = """# header comment

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

SECRETS = """[royal-review]
server = imap.example.org
user = info@royal-up.com
token = secret
"""


def _screen(qapp, tmp_path):
    (tmp_path / ".rssBlogs").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / ".rssImap").write_text(SECRETS, encoding="utf-8")
    screen = AccountsScreen(JobRunner(Bridge()), directory=tmp_path)
    screen.refresh()
    return screen


def _cell(screen, row, column):
    return screen.table.item(row, column).text()


def test_table_lists_the_accounts_with_their_details(qapp, tmp_path):
    screen = _screen(qapp, tmp_path)
    assert [account.name for account in screen.accounts] == ["royal-review", "gcalendar"]
    assert screen.table.rowCount() == 2
    assert [_cell(screen, 0, column) for column in range(3)] == ["royal-review", "imap", "info@royal-up.com"]
    details = _cell(screen, 0, 3)
    assert "imap.example.org" in details and "review" in details and "Christine" in details
    assert ".Gcalendar_gmail.com_me.json" in _cell(screen, 1, 3)
    assert screen.message.text() == ""

    (tmp_path / ".Gcalendar_gmail.com_me.json").write_text("{}", encoding="utf-8")
    screen.refresh()
    assert ".json" not in _cell(screen, 1, 3)


def test_empty_directory_shows_where_the_file_would_be(qapp, tmp_path):
    screen = AccountsScreen(JobRunner(Bridge()), directory=tmp_path)
    screen.refresh()
    assert screen.table.rowCount() == 0
    assert ".rssBlogs" in screen.message.text()


def test_dialog_prefills_an_imap_account_and_saves_through_the_screen(qapp, tmp_path):
    screen = _screen(qapp, tmp_path)
    account = screen.accounts[0]
    dialog = AccountDialog(
        lambda new, password: screen.save_account(new, password, previous_name=account.name),
        account=account,
        credentials=accounts.imap_credentials(account.name, tmp_path),
        directory=tmp_path,
    )
    assert dialog.name.text() == "royal-review"
    assert dialog.service.currentData() == "imap"
    assert dialog.server.text() == "imap.example.org" and dialog.login.text() == "info@royal-up.com"
    assert dialog.password.text() == "" and dialog.password.placeholderText()
    assert dialog.mode.currentData() == "review" and dialog.mark_seen.isChecked()
    assert dialog.max_age.value() == 5 and not dialog.include_older.isChecked()
    assert dialog.senders.text() == 'name:"Christine Fecteau"'
    assert not dialog.imap_box.isHidden() and dialog.google_box.isHidden()

    dialog.folder.setText("Archive")
    dialog.senders.setText("")
    dialog.include_older.setChecked(True)
    dialog._save()
    assert dialog.result() == AccountDialog.DialogCode.Accepted
    reloaded = {item.name: item for item in accounts.load_accounts(tmp_path)}
    assert reloaded["royal-review"].options["folder"] == "Archive"
    assert reloaded["royal-review"].options["from"] == ""
    assert reloaded["royal-review"].options["include_older"] == "yes"
    assert reloaded["royal-review"].options["since"] == "2026-09-01"
    assert accounts.imap_credentials("royal-review", tmp_path)["has_password"]
    assert (tmp_path / ".rssBlogs").read_text(encoding="utf-8").startswith("# header comment\n")
    assert "royal-review" in screen.message.text()
    assert "Archive" in _cell(screen, 0, 3)


def test_dialog_shows_the_error_and_stays_open(qapp, tmp_path):
    screen = _screen(qapp, tmp_path)
    before = (tmp_path / ".rssBlogs").read_text(encoding="utf-8")
    dialog = AccountDialog(screen.save_account, directory=tmp_path)
    dialog.service.setCurrentIndex(dialog.service.findData("imap"))
    dialog.name.setText("royal-review")
    dialog.address.setText("a@b")
    dialog.server.setText("s")
    dialog.login.setText("u")
    dialog.password.setText("p")
    dialog._save()
    assert dialog.result() != AccountDialog.DialogCode.Accepted
    assert "royal-review" in dialog.error.text()
    assert (tmp_path / ".rssBlogs").read_text(encoding="utf-8") == before

    dialog.name.setText("fresh")
    dialog._save()
    assert dialog.result() == AccountDialog.DialogCode.Accepted
    assert [item.name for item in screen.accounts] == ["royal-review", "gcalendar", "fresh"]
    assert accounts.imap_credentials("fresh", tmp_path) == {
        "server": "s",
        "port": "993",
        "user": "u",
        "has_password": True,
    }


def test_dialog_builds_a_google_account_and_imports_its_client(qapp, tmp_path):
    screen = _screen(qapp, tmp_path)
    dialog = AccountDialog(screen.save_account, directory=tmp_path)
    dialog.service.setCurrentIndex(dialog.service.findData("gmail"))
    assert dialog.imap_box.isHidden() and not dialog.google_box.isHidden()
    dialog.name.setText("mail")
    dialog.address.setText("me@gmail.com")
    assert ".Gmail_gmail.com_me.json" in dialog.client_status.text()

    source = tmp_path / "client_secret.json"
    source.write_text(json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8")
    with patch.object(accounts_screen.QFileDialog, "getOpenFileName", return_value=(str(source), "")):
        dialog.import_client()
    assert (tmp_path / ".Gmail_gmail.com_me.json").is_file()
    assert dialog.client_status.property("role") == "ok"

    dialog._save()
    assert dialog.result() == AccountDialog.DialogCode.Accepted
    saved = {item.name: item for item in accounts.load_accounts(tmp_path)}["mail"]
    assert saved.service == "gmail" and saved.nick == "me@gmail.com"
    assert "folder" not in saved.options
    assert "mail" not in (tmp_path / ".rssImap").read_text(encoding="utf-8")


def test_remove_asks_first_and_needs_a_selection(qapp, tmp_path):
    screen = _screen(qapp, tmp_path)
    screen.remove()
    assert screen.message.text() and screen.table.rowCount() == 2

    screen.table.selectRow(0)
    with patch.object(screen, "confirm_remove", return_value=False):
        screen.remove()
    assert screen.table.rowCount() == 2
    with patch.object(screen, "confirm_remove", return_value=True):
        screen.remove()
    assert [item.name for item in screen.accounts] == ["gcalendar"]
    assert "royal-review" not in (tmp_path / ".rssImap").read_text(encoding="utf-8")
    assert "royal-review" in screen.message.text()


def test_edit_and_add_are_disabled_while_a_job_runs(qapp, tmp_path):
    screen = _screen(qapp, tmp_path)
    screen.set_running(True)
    assert not screen.add_button.isEnabled() and not screen.edit_button.isEnabled()
    assert not screen.remove_button.isEnabled() and screen.reload_button.isEnabled()
    screen.set_running(False)
    assert screen.add_button.isEnabled()
