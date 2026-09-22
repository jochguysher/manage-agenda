import logging
import sys
import unittest
from unittest.mock import mock_open, patch

import pytest

sys.path.append(".")

from manage_agenda.base import PACKAGE_LOGGER_NAME, setup_logging, write_file


class TestUtilsBase(unittest.TestCase):
    @patch("builtins.open", new_callable=mock_open)
    @patch("manage_agenda.base.logger.info")
    def test_write_file_success(self, mock_logging_info, mock_open_file):
        """
        Tests that write_file successfully writes content to a file.
        """
        filename = "test.txt"
        content = "This is a test."

        # msg_txt_dir() is resolved fresh on every call (see manage_agenda.config), so it's
        # patched as the function base.py imported, not a module-level constant.
        with patch("manage_agenda.base.msg_txt_dir", return_value="/fake/dir/"):
            write_file(filename, content, enabled=True)

        mock_open_file.assert_called_once_with("/fake/dir/test.txt", "w")
        mock_open_file().write.assert_called_once_with(content)
        mock_logging_info.assert_called_once_with(f"File written: {filename}")

    @patch("builtins.open", new_callable=mock_open)
    def test_write_file_does_nothing_when_not_enabled(self, mock_open_file):
        """enabled defaults to False - no directory created, no file opened, no I/O at all.
        This is the safety property --debug-log-extractions being off is supposed to
        guarantee (see sources.Args.debug_log_extractions): a caller that forgets to pass
        enabled=True fails safe - closed, not open."""
        with patch("manage_agenda.base.msg_txt_dir", return_value="/fake/dir/"):
            result = write_file("test.txt", "content")

        self.assertFalse(result)
        mock_open_file.assert_not_called()

    @patch("builtins.open", side_effect=OSError("Disk full"))
    @patch("manage_agenda.base.logger.error")
    def test_write_file_failure(self, mock_logging_error, mock_open_file):
        """
        Tests that write_file logs an error when it fails to write a file.
        """
        filename = "test.txt"
        content = "This is a test."

        with patch("manage_agenda.base.msg_txt_dir", return_value="/fake/dir/"):
            write_file(filename, content, enabled=True)

        mock_open_file.assert_called_once_with("/fake/dir/test.txt", "w")
        self.assertIn("Error writing file", mock_logging_error.call_args[0][0])



def _package_file_handlers():
    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    return [h for h in package_logger.handlers if isinstance(h, logging.FileHandler)]


@pytest.fixture
def clean_package_logger():
    """Leave the "manage_agenda" logger as the suite found it: no handler of ours, level
    unset - whatever a test's setup_logging() attached is detached and closed."""
    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    before_level = package_logger.level
    yield package_logger
    for handler in list(package_logger.handlers):
        if getattr(handler, "manage_agenda_handler", False):
            package_logger.removeHandler(handler)
            handler.close()
    package_logger.setLevel(before_level)


class TestSetupLogging:
    """setup_logging() configures the package logger only - never the root logger, which
    socialModules already configured at import and where logging.basicConfig() would have
    been a silent no-op (the reason LOG_FILE was never written, see §12)."""

    def test_a_manage_agenda_record_lands_in_log_file(self, clean_package_logger, tmp_path):
        log_file = tmp_path / "logs" / "manage_agenda.log"  # parent doesn't exist yet
        root_handlers_before = list(logging.getLogger().handlers)
        with patch("manage_agenda.base.LOGDIR", ""), patch("manage_agenda.base.log_file_path", return_value=str(log_file)):
            setup_logging()

        logging.getLogger("manage_agenda.sources").info("reconcile: 0 ref(s) migrated")
        for handler in _package_file_handlers():
            handler.flush()

        text = log_file.read_text(encoding="utf-8")
        assert "Logging initialized" in text
        assert "manage_agenda.sources - INFO - reconcile: 0 ref(s) migrated" in text
        assert logging.getLogger().handlers == root_handlers_before  # root untouched

    def test_verbose_means_debug_and_a_console_copy(self, clean_package_logger, tmp_path):
        with patch("manage_agenda.base.LOGDIR", ""), patch(
            "manage_agenda.base.log_file_path", return_value=str(tmp_path / "manage_agenda.log")
        ):
            setup_logging(verbose=True)

        assert clean_package_logger.level == logging.DEBUG
        streams = [h for h in clean_package_logger.handlers if getattr(h, "manage_agenda_handler", False)]
        assert {type(h) for h in streams} == {logging.FileHandler, logging.StreamHandler}

    def test_logdir_overrides_the_file_location(self, clean_package_logger, tmp_path):
        with patch("manage_agenda.base.LOGDIR", str(tmp_path / "var")):
            setup_logging()

        assert [h.baseFilename for h in _package_file_handlers()] == [str(tmp_path / "var" / "manage_agenda.log")]

    def test_a_second_call_replaces_the_handlers_instead_of_stacking_them(self, clean_package_logger, tmp_path):
        first, second = tmp_path / "first.log", tmp_path / "second.log"
        with patch("manage_agenda.base.LOGDIR", ""), patch("manage_agenda.base.log_file_path", return_value=str(first)):
            setup_logging(verbose=True)
        with patch("manage_agenda.base.LOGDIR", ""), patch("manage_agenda.base.log_file_path", return_value=str(second)):
            setup_logging()

        assert [h.baseFilename for h in _package_file_handlers()] == [str(second)]
        assert not [h for h in clean_package_logger.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
        logging.getLogger("manage_agenda.sources").warning("once")
        for handler in _package_file_handlers():
            handler.flush()
        assert second.read_text(encoding="utf-8").count("once") == 1
        assert "once" not in first.read_text(encoding="utf-8")


class TestInstallPlaywrightBrowser:
    def test_streams_the_child_output_and_returns_its_code(self):
        from manage_agenda.base import install_playwright_browser

        process = unittest.mock.MagicMock()
        process.stdout = iter(["Downloading firefox\n", "done\n"])
        process.wait.return_value = 0
        lines = []
        with patch("manage_agenda.base.subprocess.Popen", return_value=process) as popen:
            code = install_playwright_browser("firefox", on_output=lines.append)

        assert code == 0
        assert lines == ["Downloading firefox", "done"]
        command = popen.call_args.args[0]
        assert command[0] == sys.executable
        assert command[1:] == ["-m", "playwright", "install", "firefox"]

    def test_a_missing_interpreter_or_module_is_reported_not_raised(self):
        from manage_agenda.base import install_playwright_browser

        lines = []
        with patch("manage_agenda.base.subprocess.Popen", side_effect=OSError("no python")):
            code = install_playwright_browser("firefox", on_output=lines.append)

        assert code == 1
        assert lines == ["OSError: no python"]

    def test_defaults_to_echo(self):
        from manage_agenda.base import install_playwright_browser
        from manage_agenda.ui import use_ui
        from manage_agenda.ui.fake import ScriptedUI

        process = unittest.mock.MagicMock()
        process.stdout = iter(["line\n"])
        process.wait.return_value = 2
        with patch("manage_agenda.base.subprocess.Popen", return_value=process), use_ui(
            ScriptedUI()
        ) as ui:
            assert install_playwright_browser("webkit") == 2
        assert ui.output == ["line"]
