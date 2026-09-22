"""write_file()'s enabled flag and purge_expired_log_files() (base.py) - the mechanism behind
--debug-log-extractions/--debug-log-retention-days (see sources.Args, cli.py's `add` command).

Off by default: MSG_TXT_DIR/log/ holds plaintext message/event content and grows on every
processed message, so nothing may be written there unless a user explicitly opts in - not
merely left undocumented. See docs/investigation-limite1.md.
"""

import datetime
import os
from unittest.mock import MagicMock, patch

from manage_agenda.base import purge_expired_log_files, write_file
from manage_agenda.sources import Args, add_events_cli


class TestWriteFileEnabledFlag:
    def test_disabled_by_default_writes_nothing_and_creates_no_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")

        result = write_file("log/model/post_1.json", "content")

        assert result is False
        assert not (tmp_path / "log").exists()

    def test_enabled_writes_the_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")

        result = write_file("log/model/post_1.json", "content", enabled=True)

        assert result is True
        written = tmp_path / "log" / "model" / "post_1.json"
        assert written.read_text(encoding="utf-8") == "content"

    def test_enabled_chmods_the_file_0600_and_log_tree_0700(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")

        write_file("log/model/post_1.json", "content", enabled=True)

        written = tmp_path / "log" / "model" / "post_1.json"
        assert oct(written.stat().st_mode)[-3:] == "600"
        assert oct((tmp_path / "log").stat().st_mode)[-3:] == "700"
        assert oct((tmp_path / "log" / "model").stat().st_mode)[-3:] == "700"

    def test_a_chmod_failure_on_the_log_tree_does_not_fail_the_write(self, tmp_path, monkeypatch):
        """_chmod_debug_log_tree's own chmod calls must be guarded the same way write_file's
        mkdir/file-chmod already are - a permissions error there must degrade to a warning,
        not escape as an uncaught OSError that write_file's outer except turns into a failed
        write (result False, nothing written) despite the file having been written fine."""
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        with patch("os.chmod", side_effect=OSError("Operation not permitted")):
            result = write_file("log/model/post_1.json", "content", enabled=True)

        assert result is True
        assert (tmp_path / "log" / "model" / "post_1.json").read_text(encoding="utf-8") == "content"

    def test_enabled_does_not_chmod_msg_txt_dir_itself(self, tmp_path, monkeypatch):
        """MSG_TXT_DIR also holds the user's real .txt source files - only the log/ subtree
        is a debug artifact area, so only it gets tightened permissions."""
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        before = tmp_path.stat().st_mode

        write_file("log/model/post_1.json", "content", enabled=True)

        assert tmp_path.stat().st_mode == before


class TestPurgeExpiredLogFiles:
    def test_no_log_directory_is_a_no_op(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")

        assert purge_expired_log_files(retention_days=7) == 0

    def test_old_files_are_deleted_fresh_ones_kept(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        write_file("log/old.json", "old", enabled=True)
        write_file("log/fresh.json", "fresh", enabled=True)
        old_path = tmp_path / "log" / "old.json"
        old_mtime = (datetime.datetime.now() - datetime.timedelta(days=30)).timestamp()
        os.utime(old_path, (old_mtime, old_mtime))
        today = datetime.datetime.now(datetime.timezone.utc)

        deleted = purge_expired_log_files(retention_days=7, today=today)

        assert deleted == 1
        assert not old_path.exists()
        assert (tmp_path / "log" / "fresh.json").exists()

    def test_now_empty_subdirectories_are_removed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        write_file("log/model/old.json", "old", enabled=True)
        old_path = tmp_path / "log" / "model" / "old.json"
        old_mtime = (datetime.datetime.now() - datetime.timedelta(days=30)).timestamp()
        os.utime(old_path, (old_mtime, old_mtime))
        today = datetime.datetime.now(datetime.timezone.utc)

        purge_expired_log_files(retention_days=7, today=today)

        assert not (tmp_path / "log" / "model").exists()

    def test_times_json_files_are_never_purged_even_when_old(self, tmp_path, monkeypatch):
        """*_times.json is not always a debug artifact - _process_event_with_llm_and_calendar
        writes log/{model}/{post}_{idx}_times.json unconditionally (enabled=True) as the
        actual result of `-o file` mode, not gated by --debug-log-extractions. Retention must
        never delete a user's requested output just because it lives under log/."""
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        write_file("log/model/post_1_times.json", "output", enabled=True)
        old_path = tmp_path / "log" / "model" / "post_1_times.json"
        old_mtime = (datetime.datetime.now() - datetime.timedelta(days=30)).timestamp()
        os.utime(old_path, (old_mtime, old_mtime))
        today = datetime.datetime.now(datetime.timezone.utc)

        deleted = purge_expired_log_files(retention_days=7, today=today)

        assert deleted == 0
        assert old_path.exists()

    def test_a_directory_with_a_remaining_fresh_file_is_not_removed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        write_file("log/model/old.json", "old", enabled=True)
        write_file("log/model/fresh.json", "fresh", enabled=True)
        old_path = tmp_path / "log" / "model" / "old.json"
        old_mtime = (datetime.datetime.now() - datetime.timedelta(days=30)).timestamp()
        os.utime(old_path, (old_mtime, old_mtime))
        today = datetime.datetime.now(datetime.timezone.utc)

        purge_expired_log_files(retention_days=7, today=today)

        assert (tmp_path / "log" / "model").is_dir()
        assert (tmp_path / "log" / "model" / "fresh.json").exists()


class TestAddEventsCliRetentionWiring:
    """add_events_cli() is the one real dispatcher reached from the `add` CLI command for
    email/web/txt processing (see docs/investigation-limite1.md) - the natural single place
    to run the retention sweep once per invocation, rather than duplicating it in each of
    process_email_cli/process_txt_cli/process_web_cli."""

    def _run(self, args):
        rules = MagicMock()
        rules.selectRule.return_value = []
        with (
            patch("manage_agenda.sources.select_llm", return_value=MagicMock()),
            patch("manage_agenda.sources.get_add_sources", return_value=([], [])),
            patch("manage_agenda.base.purge_expired_log_files") as mock_purge,
        ):
            add_events_cli(args, rules=rules)
        return mock_purge

    def test_purge_not_called_when_debug_log_extractions_is_off(self):
        args = Args(interactive=False, debug_log_extractions=False)
        mock_purge = self._run(args)
        mock_purge.assert_not_called()

    def test_purge_called_with_configured_retention_when_on(self):
        args = Args(interactive=False, debug_log_extractions=True, debug_log_retention_days=14)
        mock_purge = self._run(args)
        mock_purge.assert_called_once_with(14)
