"""write_file()'s enabled flag and purge_expired_log_files() (base.py) - the mechanism behind
--debug-log-extractions/--debug-log-retention-days (see sources.Args, cli.py's `add` command).

Off by default: MSG_TXT_DIR/log/ holds plaintext message/event content and grows on every
processed message, so nothing may be written there unless a user explicitly opts in - not
merely left undocumented. See docs/investigation-limite1.md.
"""

import datetime
import os
from pathlib import Path
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


def _set_age(path, days):
    mtime = (datetime.datetime.now() - datetime.timedelta(days=days)).timestamp()
    os.utime(path, (mtime, mtime))


def _enable_purge_days_ago(days):
    """Stamps the first-activation marker as if the purge had been enabled `days` ago, so a
    file can then be given an mtime that is both after the marker and past retention."""
    now = datetime.datetime.now(datetime.timezone.utc)
    purge_expired_log_files(retention_days=7, today=now - datetime.timedelta(days=days))


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
        _enable_purge_days_ago(60)
        write_file("log/old.json", "old", enabled=True)
        write_file("log/fresh.json", "fresh", enabled=True)
        old_path = tmp_path / "log" / "old.json"
        _set_age(old_path, 30)

        deleted = purge_expired_log_files(retention_days=7)

        assert deleted == 1
        assert not old_path.exists()
        assert (tmp_path / "log" / "fresh.json").exists()

    def test_a_file_older_than_the_first_activation_survives_every_later_pass(
        self, tmp_path, monkeypatch
    ):
        """Permanent protection, not a one-time grace pass: a file that predates the marker
        (e.g. `-o file` output written under log/ before it moved to output_dir()) is never
        deleted, however many purges run afterwards - while a file written after the marker
        and past retention, in the same log/, is."""
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        write_file("log/model/legacy_1_times.json", "legacy", enabled=True)
        legacy_path = tmp_path / "log" / "model" / "legacy_1_times.json"
        _set_age(legacy_path, 365)
        _enable_purge_days_ago(60)
        write_file("log/model/expired.json", "expired", enabled=True)
        expired_path = tmp_path / "log" / "model" / "expired.json"
        _set_age(expired_path, 30)

        total_deleted = sum(purge_expired_log_files(retention_days=7) for _ in range(5))

        assert total_deleted == 1
        assert legacy_path.read_text(encoding="utf-8") == "legacy"
        assert not expired_path.exists()

    def test_the_marker_timestamp_does_not_move_on_later_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        _enable_purge_days_ago(60)
        marker = tmp_path / "log" / ".purge_enabled_since"
        stamped = marker.read_text(encoding="utf-8")

        purge_expired_log_files(retention_days=7)
        purge_expired_log_files(retention_days=7)

        assert marker.read_text(encoding="utf-8") == stamped

    def test_an_unreadable_marker_purges_nothing(self, tmp_path, monkeypatch, caplog):
        """With the protection boundary unknown, deleting anything could hit a protected file."""
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        _enable_purge_days_ago(60)
        (tmp_path / "log" / ".purge_enabled_since").write_text("garbage", encoding="utf-8")
        write_file("log/expired.json", "expired", enabled=True)
        expired_path = tmp_path / "log" / "expired.json"
        _set_age(expired_path, 30)

        with caplog.at_level("WARNING"):
            assert purge_expired_log_files(retention_days=7) == 0
        assert expired_path.exists()
        message = next(r.getMessage() for r in caplog.records if "purge marker" in r.getMessage())
        assert "delete" in message and "permanently protected" in message

    def test_now_empty_subdirectories_are_removed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        _enable_purge_days_ago(60)
        write_file("log/model/old.json", "old", enabled=True)
        _set_age(tmp_path / "log" / "model" / "old.json", 30)

        purge_expired_log_files(retention_days=7)

        assert not (tmp_path / "log" / "model").exists()

    def test_the_marker_is_excluded_by_name_whatever_its_mtime(self, tmp_path, monkeypatch):
        """The marker's mtime here is AFTER the timestamp it holds and past retention - by
        age alone it would be purgeable; it must survive because of its name."""
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        _enable_purge_days_ago(60)
        marker = tmp_path / "log" / ".purge_enabled_since"
        stamped = datetime.datetime.fromisoformat(marker.read_text(encoding="utf-8"))
        _set_age(marker, 30)
        marker_mtime = datetime.datetime.fromtimestamp(marker.stat().st_mtime, tz=datetime.timezone.utc)
        assert stamped < marker_mtime < datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)

        purge_expired_log_files(retention_days=7)

        # Content checked too, not just existence: a deleted marker would be re-stamped (with a
        # new, later timestamp) by the next call, so existence alone could hide the deletion.
        assert marker.is_file()
        assert datetime.datetime.fromisoformat(marker.read_text(encoding="utf-8")) == stamped
        purge_expired_log_files(retention_days=7)
        assert datetime.datetime.fromisoformat(marker.read_text(encoding="utf-8")) == stamped

    def test_a_directory_with_a_remaining_fresh_file_is_not_removed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        _enable_purge_days_ago(60)
        write_file("log/model/old.json", "old", enabled=True)
        write_file("log/model/fresh.json", "fresh", enabled=True)
        _set_age(tmp_path / "log" / "model" / "old.json", 30)

        purge_expired_log_files(retention_days=7)

        assert (tmp_path / "log" / "model").is_dir()
        assert (tmp_path / "log" / "model" / "fresh.json").exists()

    def test_output_dir_files_are_outside_log_and_never_considered(self, tmp_path, monkeypatch):
        """`-o file` mode's real output lives under config.output_dir(), a sibling of log/,
        not inside it - purge_expired_log_files only ever walks log/, so it structurally
        cannot reach output_dir() regardless of file age."""
        monkeypatch.setenv("MSG_TXT_DIR", str(tmp_path) + "/")
        output_root = tmp_path / "output"
        _enable_purge_days_ago(60)
        write_file("post_1_times.json", "output", enabled=True, base_dir=str(output_root))
        output_path = output_root / "post_1_times.json"
        _set_age(output_path, 30)

        purge_expired_log_files(retention_days=7)

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


class TestEvaluateWritesNothingUnderLog:
    """`llm evaluate` builds its own Args with no --debug-log-extractions option, so it must
    never write under MSG_TXT_DIR/log/ - its `-o file` result goes to output_dir() only. Runs
    the real CLI command end to end (real txt source, real extraction, real write_file), with
    only the Ollama client mocked."""

    def test_evaluate_creates_no_file_under_log(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from manage_agenda import cli
        from manage_agenda.config import msg_txt_dir, output_dir

        txt_dir = tmp_path / "txt"
        txt_dir.mkdir()
        monkeypatch.setenv("MSG_TXT_DIR", str(txt_dir) + "/")
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
        (txt_dir / "meeting.txt").write_text(
            "Team meeting\nFrom: someone\n\nMeeting on 2030-01-15 at 10:00 for one hour.\nDate: 2030-01-01\n",
            encoding="utf-8",
        )
        llm_reply = (
            '{"summary": "Team meeting", "start": {"dateTime": "2030-01-15T10:00:00", '
            '"timeZone": "Europe/Madrid"}, "end": {"dateTime": "2030-01-15T11:00:00", '
            '"timeZone": "Europe/Madrid"}}'
        )
        client = MagicMock()
        client.model_name = "fake-model"
        client.generate_text.return_value = llm_reply

        with patch("manage_agenda.evaluation.OllamaClient") as mock_ollama:
            mock_ollama.list_models.return_value = [{"model": "fake-model"}]
            mock_ollama.return_value = client
            result = CliRunner().invoke(cli.cli, ["llm", "evaluate", "--type", "txt", "-o", "file"])

        assert result.exit_code == 0, result.output
        client.generate_text.assert_called()
        # The run really reached the `-o file` write - otherwise "nothing under log/" would
        # hold vacuously.
        assert list(Path(output_dir()).rglob("*_times.json"))
        log_dir = Path(msg_txt_dir()) / "log"
        assert not log_dir.exists() or not [p for p in log_dir.rglob("*") if p.is_file()]
