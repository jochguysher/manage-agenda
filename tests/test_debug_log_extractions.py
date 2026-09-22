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

    def test_first_call_ever_purges_nothing_and_stamps_a_marker(self, tmp_path, monkeypatch):
        """Grandfathers whatever already sits under log/ the first time
        --debug-log-extractions is ever turned on - notably any `-o file` output written
        there before that mode moved to config.output_dir() (see purge_expired_log_files's
        and write_file's docstrings, docs/investigation-limite1.md)."""
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        write_file("log/old.json", "old", enabled=True)
        old_path = tmp_path / "log" / "old.json"
        old_mtime = (datetime.datetime.now() - datetime.timedelta(days=365)).timestamp()
        os.utime(old_path, (old_mtime, old_mtime))

        deleted = purge_expired_log_files(retention_days=7)

        assert deleted == 0
        assert old_path.exists()
        assert (tmp_path / "log" / ".purge_enabled_since").is_file()

    def test_old_files_are_deleted_fresh_ones_kept_from_the_second_call_onward(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        write_file("log/old.json", "old", enabled=True)
        write_file("log/fresh.json", "fresh", enabled=True)
        purge_expired_log_files(retention_days=7)  # consumes the first-call grace pass
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
        purge_expired_log_files(retention_days=7)  # consumes the first-call grace pass
        old_path = tmp_path / "log" / "model" / "old.json"
        old_mtime = (datetime.datetime.now() - datetime.timedelta(days=30)).timestamp()
        os.utime(old_path, (old_mtime, old_mtime))
        today = datetime.datetime.now(datetime.timezone.utc)

        purge_expired_log_files(retention_days=7, today=today)

        assert not (tmp_path / "log" / "model").exists()

    def test_the_marker_file_itself_is_never_purged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        purge_expired_log_files(retention_days=7)  # stamps the marker
        marker = tmp_path / "log" / ".purge_enabled_since"
        old_mtime = (datetime.datetime.now() - datetime.timedelta(days=365)).timestamp()
        os.utime(marker, (old_mtime, old_mtime))
        today = datetime.datetime.now(datetime.timezone.utc)

        purge_expired_log_files(retention_days=7, today=today)

        assert marker.is_file()

    def test_a_directory_with_a_remaining_fresh_file_is_not_removed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        write_file("log/model/old.json", "old", enabled=True)
        write_file("log/model/fresh.json", "fresh", enabled=True)
        purge_expired_log_files(retention_days=7)  # consumes the first-call grace pass
        old_path = tmp_path / "log" / "model" / "old.json"
        old_mtime = (datetime.datetime.now() - datetime.timedelta(days=30)).timestamp()
        os.utime(old_path, (old_mtime, old_mtime))
        today = datetime.datetime.now(datetime.timezone.utc)

        purge_expired_log_files(retention_days=7, today=today)

        assert (tmp_path / "log" / "model").is_dir()
        assert (tmp_path / "log" / "model" / "fresh.json").exists()

    def test_output_dir_files_are_outside_log_and_never_considered(self, tmp_path, monkeypatch):
        """`-o file` mode's real output lives under config.output_dir(), a sibling of log/,
        not inside it - purge_expired_log_files only ever walks log/, so it structurally
        cannot reach output_dir() regardless of file age."""
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        output_root = tmp_path / "output"
        write_file("post_1_times.json", "output", enabled=True, base_dir=str(output_root))
        output_path = output_root / "post_1_times.json"
        old_mtime = (datetime.datetime.now() - datetime.timedelta(days=365)).timestamp()
        os.utime(output_path, (old_mtime, old_mtime))
        purge_expired_log_files(retention_days=7)  # first-call grace pass
        today = datetime.datetime.now(datetime.timezone.utc)

        purge_expired_log_files(retention_days=7, today=today)

        assert output_path.exists()


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
