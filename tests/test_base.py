import logging
import sys
import unittest
from unittest.mock import mock_open, patch

sys.path.append(".")

from manage_agenda.base import setup_logging, write_file


class TestUtilsBase(unittest.TestCase):
    @patch("builtins.open", new_callable=mock_open)
    @patch("logging.info")
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
    @patch("logging.error")
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

    @patch("logging.basicConfig")
    def test_setup_logging_no_logdir(self, mock_basic_config):
        """
        Tests that setup_logging configures logging to the default /tmp directory.
        """
        with (
            patch("manage_agenda.base.LOGDIR", ""),
            patch("manage_agenda.base.log_file_path", return_value="/tmp/manage_agenda.log"),
        ):
            setup_logging(verbose=True)

        mock_basic_config.assert_called_once()
        args, kwargs = mock_basic_config.call_args
        self.assertEqual(kwargs["filename"], "/tmp/manage_agenda.log")
        self.assertEqual(kwargs["level"], logging.DEBUG)

    @patch("logging.basicConfig")
    def test_setup_logging_with_logdir(self, mock_basic_config):
        """
        Tests that setup_logging configures logging to a specified directory.
        """
        with patch("manage_agenda.base.LOGDIR", "/var/log"):
            setup_logging()

        mock_basic_config.assert_called_once()
        args, kwargs = mock_basic_config.call_args
        self.assertEqual(kwargs["filename"], "/var/log/manage_agenda.log")
