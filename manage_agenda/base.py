"""
Base utility functions for manage-agenda.
"""

import datetime
import logging
import os
import sys
from pathlib import Path

from manage_agenda.config import config, log_file_path, msg_txt_dir
from manage_agenda.i18n import t

LOGDIR = ""


# --- File I/O ---
def write_file(filename, content, enabled=False, base_dir=None):
    """Writes content to a file under `base_dir` (msg_txt_dir() if not given) - in practice,
    almost always a `log/...` debug artifact (every caller but one passes one; see
    docs/investigation-limite1.md). The exception is `-o file` mode's actual output
    (extraction.py), which passes base_dir=config.output_dir() - its own dedicated directory,
    not msg_txt_dir()/log/, so purge_expired_log_files() can sweep log/ with no per-filename
    exception without risking a user's requested output.

    `enabled` defaults to False, meaning: no directory created, no file written, no I/O
    attempted at all. Callers pass `enabled=args.debug_log_extractions` (see sources.Args) -
    this content is plaintext message/event data, written once per processed message, so it
    must stay off unless a user explicitly opts in, not merely unlisted/undocumented (see
    docs/investigation-limite1.md - a debug flag threaded through every call site, not a
    single "dry_run"-shaped toggle, because unlike the ledger's dry-run this one is meant to
    stay on for a whole debugging session, and because a caller that forgets to pass
    enabled=True fails safe - closed, not open). `-o file` mode's own write always passes
    enabled=True unconditionally - it is the user's requested result, not an optional trail.

    When enabled and writing under msg_txt_dir()/log/ specifically, the created directory is
    chmod'd 0700 and the file 0600 - this holds real email/event content, so it must never be
    left group/world-readable regardless of the process umask. A different base_dir (e.g.
    output_dir()) is not chmod'd by this function - out of scope for the debug-log permission
    tightening this was written for (see docs/investigation-limite1.md).

    Args:
        filename (str): The name of the file, relative to base_dir.
        content (str): The content to write.
        enabled (bool): Must be explicitly True for anything to be written.
        base_dir (str | None): Defaults to msg_txt_dir() when not given.
    """
    if not enabled:
        return False
    try:
        # Resolved fresh on every call, not a module-level constant - see
        # manage_agenda.config.data_dir()'s docstring for why.
        default_data_dir = base_dir if base_dir is not None else msg_txt_dir()

        # Sanitize the filename to prevent path traversal attacks
        # Normalize the path to resolve any '..' or '.' components
        normalized_filename = os.path.normpath(filename)

        # Ensure the filename doesn't contain path traversal sequences that would allow
        # writing outside default_data_dir
        # Check if the normalized filename is an absolute path (which would
        # bypass default_data_dir) or
        # if it contains '..' components that could traverse up the directory
        # tree
        if os.path.isabs(normalized_filename) or '..' in normalized_filename.split(os.sep):
            logging.error(f"Invalid filename: {filename} - contains path traversal attempts")
            return False

        # Construct the full path using os.path.join for safety
        full_path = os.path.join(default_data_dir, normalized_filename)

        # Double-check that the final path is within the expected directory
        # Resolve both paths to handle symbolic links properly
        try:
            full_path_real = os.path.realpath(full_path)
            default_dir_real = os.path.realpath(default_data_dir)

            # Ensure the resolved file path is within the resolved default
            # directory
            if not full_path_real.startswith(default_dir_real + os.sep) and full_path_real != default_dir_real:
                logging.error(f"Invalid filename: {filename} - resolves outside allowed directory")
                return False
        except OSError:
            # If realpath fails (e.g., path doesn't exist), we can't do the security check,
            # but we can still proceed with the original path check if we're careful
            logging.warning(f"Could not resolve real paths for security check: {filename}")
            # We'll continue anyway, but this is less secure

        # Ensure the directory exists
        # Catch specific exceptions related to directory creation to distinguish
        # from other types of errors
        dir_path = os.path.dirname(full_path)
        try:
            os.makedirs(dir_path, exist_ok=True)
            _chmod_debug_log_tree(default_data_dir, dir_path)
        except OSError as dir_error:
            # If directory creation fails, we log it but continue to try opening the file
            # This allows tests with fake directories to work while still providing security
            logging.warning(f"Could not create directory for {filename}: {dir_error}")

        with open(full_path, "w") as file:
            file.write(content)
        try:
            os.chmod(full_path, 0o600)
        except OSError as chmod_error:
            # Same "log but continue" reasoning as the mkdir above - e.g. `open` mocked out
            # in a test with no real file underneath full_path to chmod.
            logging.warning(f"Could not chmod {full_path} to 0600: {chmod_error}")
        logging.info(f"File written: {filename}")
        return True
    except Exception as e:
        logging.error(f"Error writing file {filename}: {e}")
        return False


def _chmod_debug_log_tree(default_data_dir, dir_path):
    """chmod 0700 every directory from default_data_dir/log down to dir_path (inclusive) -
    never default_data_dir itself, which also holds the user's real .txt source files and
    must keep its normal permissions. A no-op if dir_path isn't under .../log at all (a
    future caller passing enabled=True with some other path is left alone, not assumed to
    be the debug tree)."""
    log_root = os.path.join(default_data_dir, "log")
    try:
        real_dir = os.path.realpath(dir_path)
        real_log_root = os.path.realpath(log_root)
        common = os.path.commonpath([real_dir, real_log_root])
    except (OSError, ValueError):
        return
    if common != real_log_root:
        return
    try:
        os.chmod(log_root, 0o700)
        relative = os.path.relpath(real_dir, real_log_root)
        if relative == os.curdir:
            return
        current = log_root
        for part in Path(relative).parts:
            current = os.path.join(current, part)
            os.chmod(current, 0o700)
    except OSError as chmod_error:
        # Same "log but continue" reasoning as write_file()'s own mkdir/chmod guards - e.g.
        # os.makedirs above only partially succeeded, leaving a directory in this chain
        # missing. Must not escape as an uncaught exception: write_file()'s outer
        # `except Exception` would turn that into a failed write, not a permissions warning.
        logging.warning(f"Could not chmod debug log directory under {log_root}: {chmod_error}")


_PURGE_MARKER_NAME = ".purge_enabled_since"


def purge_expired_log_files(retention_days, today=None):
    """Delete every file under msg_txt_dir()/log/ older than `retention_days`, then remove
    any subdirectory left empty by that. Only meaningful while --debug-log-extractions is on
    (write_file() writes nothing there otherwise, so there is nothing to purge) - the caller
    decides when to run this (see add_events_cli's debug_log_extractions branch), not this
    function, which is a plain sweep once past its first call (see below).

    Applies to log/ uniformly, with no per-filename exception - safe because `-o file` mode's
    actual output no longer lives under log/ at all (it moved to config.output_dir(), see
    write_file()'s docstring), so nothing purgeable here can be a user's requested result.

    First call ever for a given log/ (no marker file yet): stamps a marker and purges
    NOTHING, regardless of how old anything already there is. This matters because `-o file`
    mode used to write log/{model}/{post}_{idx}_times.json (before it moved to
    output_dir()) - a real user, prior to this change, may already have such output sitting
    under log/. The very first time --debug-log-extractions is ever turned on must not sweep
    those away as a side effect of enabling an unrelated debug flag; every call after that
    one purges normally, same as the ledger's own one-time grace pass for an entry with no
    age signal (see purge_expired_ledger_entries) - a file's age only starts counting against
    it from the marker's timestamp onward, never retroactively for what predates it. If you
    have `-o file` output already under MSG_TXT_DIR/log/ that you want to keep indefinitely,
    move it out before enabling --debug-log-extractions a second time.

    Returns the number of files deleted.
    """
    log_root = Path(msg_txt_dir()) / "log"
    today = today or datetime.datetime.now(datetime.timezone.utc)
    marker = log_root / _PURGE_MARKER_NAME
    if not marker.is_file():
        try:
            log_root.mkdir(parents=True, exist_ok=True)
            marker.write_text(today.isoformat(), encoding="utf-8")
        except OSError as error:
            logging.warning(f"Could not stamp debug log purge marker under {log_root}: {error}")
        return 0
    if not log_root.is_dir():
        return 0
    cutoff = today - datetime.timedelta(days=retention_days)
    deleted = 0
    for root, _dirs, files in os.walk(log_root, topdown=False):
        for name in files:
            if name == _PURGE_MARKER_NAME:
                continue
            file_path = Path(root) / name
            try:
                mtime = datetime.datetime.fromtimestamp(
                    file_path.stat().st_mtime, tz=datetime.timezone.utc
                )
            except OSError:
                continue
            if mtime < cutoff:
                try:
                    file_path.unlink()
                    deleted += 1
                except OSError as error:
                    logging.warning(f"Could not purge expired log file {file_path}: {error}")
        # Bottom-up (topdown=False), so a directory only just emptied by this same pass is
        # already empty by the time we get here - safe to try removing every directory and
        # let rmdir fail harmlessly on any that still has content.
        try:
            Path(root).rmdir()
        except OSError:
            pass
    return deleted


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application.

    Args:
        verbose: Enable verbose (DEBUG level) logging.
    """
    print(t("base.setting_logging"))

    # Determine log file location - log_file_path() is resolved fresh on every call (see its
    # docstring), so a test's LOG_FILE env var override, set at any time, is always picked up.
    if not LOGDIR:
        log_file = Path(log_file_path())
    else:
        log_file = Path(f"{LOGDIR}/manage_agenda.log")

    # Create parent directory if needed
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Determine log level
    if verbose:
        log_level = logging.DEBUG
    else:
        log_level = getattr(logging, getattr(config, "LOG_LEVEL", "INFO").upper(), logging.INFO)

    # Configure logging format
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configure root logger
    logging.basicConfig(
        filename=str(log_file),
        level=log_level,
        format=log_format,
        datefmt=date_format,
    )

    # Also add console handler if verbose
    if verbose:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(log_format, date_format))
        logging.getLogger().addHandler(console_handler)

    # Set specific log levels for noisy libraries
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Level: {logging.getLevelName(log_level)}, File: {log_file}")


def format_time(seconds):
    """Formats seconds into a human-readable string."""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h)}h {int(m)}m {s:.2f}s"
