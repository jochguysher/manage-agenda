"""
Base utility functions for manage-agenda.
"""

import datetime
import logging
import os
import subprocess
import sys
from pathlib import Path

from manage_agenda.config import config, log_file_path, msg_txt_dir
from manage_agenda.i18n import t
from manage_agenda.ui import echo

logger = logging.getLogger(__name__)

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

    When enabled, the file is chmod'd 0600 - this holds real email/event content, so it must
    never be left group/world-readable regardless of the process umask. Directories: with no
    base_dir, every directory from msg_txt_dir()/log/ down to the file is chmod'd 0700 (never
    msg_txt_dir() itself, which also holds the user's .txt sources). With a base_dir
    (output_dir(), which OUTPUT_DIR may point at a directory the user already owns and uses
    for other things), an existing directory's permissions are NEVER changed - only the
    directories this call creates, from base_dir down, get 0700; an existing one looser than
    0700 is only reported by a warning in the log (see _makedirs_private).

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
            logger.error("Invalid filename: %s - contains path traversal attempts", filename)
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
                logger.error("Invalid filename: %s - resolves outside allowed directory", filename)
                return False
        except OSError:
            # If realpath fails (e.g., path doesn't exist), we can't do the security check,
            # but we can still proceed with the original path check if we're careful
            logger.warning("Could not resolve real paths for security check: %s", filename)
            # We'll continue anyway, but this is less secure

        # Ensure the directory exists
        # Catch specific exceptions related to directory creation to distinguish
        # from other types of errors
        dir_path = os.path.dirname(full_path)
        try:
            if base_dir is None:
                os.makedirs(dir_path, exist_ok=True)
                _chmod_private_tree(os.path.join(default_data_dir, "log"), dir_path)
            else:
                _makedirs_private(base_dir, dir_path)
        except OSError as dir_error:
            # If directory creation fails, we log it but continue to try opening the file
            # This allows tests with fake directories to work while still providing security
            logger.warning("Could not create directory for %s: %s", filename, dir_error)

        with open(full_path, "w") as file:
            file.write(content)
        try:
            os.chmod(full_path, 0o600)
        except OSError as chmod_error:
            # Same "log but continue" reasoning as the mkdir above - e.g. `open` mocked out
            # in a test with no real file underneath full_path to chmod.
            logger.warning(f"Could not chmod {full_path} to 0600: {chmod_error}")
        logger.info(f"File written: {filename}")
        return True
    except Exception as e:
        logger.error("Error writing file %s: %s", filename, e)
        return False


def _chmod_private_tree(root, dir_path):
    """chmod 0700 every directory from root (msg_txt_dir()/log, or output_dir()) down to
    dir_path (inclusive) - never anything above root, e.g. msg_txt_dir() itself, which
    also holds the user's real .txt source files and must keep its normal permissions. A
    no-op if dir_path isn't under root at all (a write outside it is left alone, not
    assumed to be a private tree)."""
    try:
        real_dir = os.path.realpath(dir_path)
        real_root = os.path.realpath(root)
        common = os.path.commonpath([real_dir, real_root])
    except (OSError, ValueError):
        return
    if common != real_root:
        return
    try:
        os.chmod(root, 0o700)
        relative = os.path.relpath(real_dir, real_root)
        if relative == os.curdir:
            return
        current = root
        for part in Path(relative).parts:
            current = os.path.join(current, part)
            os.chmod(current, 0o700)
    except OSError as chmod_error:
        # Same "log but continue" reasoning as write_file()'s own mkdir/chmod guards - e.g.
        # os.makedirs above only partially succeeded, leaving a directory in this chain
        # missing. Must not escape as an uncaught exception: write_file()'s outer
        # `except Exception` would turn that into a failed write, not a permissions warning.
        logger.warning(f"Could not chmod private directory under {root}: {chmod_error}")


_warned_loose_directories = set()


def _makedirs_private(root, dir_path):
    """Create every missing directory from root down to dir_path with mode 0700, and never
    touch the permissions of one that already exists: an existing directory looser than 0700
    (any group/other bit) only gets a warning in the log, once per process per directory, so
    a run writing many files doesn't repeat it. Directories above root (e.g. msg_txt_dir()
    for the default output_dir()) are created, if missing, with default permissions - they
    are not part of the private tree. If dir_path isn't under root, it is just created
    normally."""
    relative = os.path.relpath(dir_path, root)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        os.makedirs(dir_path, exist_ok=True)
        return
    os.makedirs(os.path.dirname(os.path.normpath(root)), exist_ok=True)
    chain = [root]
    if relative != os.curdir:
        for part in Path(relative).parts:
            chain.append(os.path.join(chain[-1], part))
    for directory in chain:
        try:
            # 0700 at creation (umask can only remove bits, never add them), so a new
            # directory is never momentarily group/world-readable.
            os.mkdir(directory, 0o700)
            continue
        except FileExistsError:
            pass
        mode = os.stat(directory).st_mode & 0o777
        if mode & 0o077 and directory not in _warned_loose_directories:
            _warned_loose_directories.add(directory)
            logger.warning(
                f"Existing output directory {directory} has permissions {oct(mode)}, looser "
                f"than 0700 - left unchanged. Files written into it are still 0600; run "
                f"`chmod 700 {directory}` if it should be private."
            )


_PURGE_MARKER_NAME = ".purge_enabled_since"


def purge_expired_log_files(retention_days, today=None):
    """Delete every file under msg_txt_dir()/log/ older than `retention_days` AND more recent
    than the purge's first activation (see below), then remove any subdirectory left empty by
    that. Only meaningful while --debug-log-extractions is on (write_file() writes nothing
    there otherwise, so there is nothing to purge) - the caller decides when to run this (see
    add_events_cli's debug_log_extractions branch), not this function.

    Applies to log/ uniformly, with no per-filename exception (other than the marker itself,
    see below) - safe because `-o file` mode's
    actual output no longer lives under log/ at all (it moved to config.output_dir(), see
    write_file()'s docstring), so nothing purgeable here can be a user's requested result.

    PERMANENT protection of everything that predates the first activation: the first call
    ever for a given log/ (no marker file yet) stamps a marker holding that moment's
    timestamp and purges nothing. Every later call only ever considers files whose mtime is
    strictly AFTER that timestamp - a file older than the marker is never deleted, however
    many times the purge runs afterwards. This matters because `-o file` mode used to write
    log/{model}/{post}_{idx}_times.json (before it moved to output_dir()) - a real user,
    prior to this change, may already have such output sitting under log/, and enabling an
    unrelated debug flag must never sweep it away, neither on the first run nor on any later
    one. The marker is written once and never rewritten, so the boundary does not move.

    If the marker exists but its timestamp can't be read, nothing is purged (a warning is
    logged, saying how to fix it) - with the protection boundary unknown, deleting anything
    could hit a protected file. Deleting the marker re-arms the protection: the next call
    re-stamps it, and every file present at that moment becomes permanently protected.

    The marker itself is excluded by name, whatever its mtime.

    Returns the number of files deleted.
    """
    log_root = Path(msg_txt_dir()) / "log"
    today = today or datetime.datetime.now(datetime.timezone.utc)
    marker = log_root / _PURGE_MARKER_NAME
    if not marker.is_file():
        try:
            log_root.mkdir(parents=True, exist_ok=True)
            marker.write_text(today.isoformat(), encoding="utf-8")
            os.chmod(marker, 0o600)
        except OSError as error:
            logger.warning(f"Could not stamp debug log purge marker under {log_root}: {error}")
        return 0
    try:
        enabled_since = datetime.datetime.fromisoformat(
            marker.read_text(encoding="utf-8").strip()
        )
        if enabled_since.tzinfo is None:
            enabled_since = enabled_since.replace(tzinfo=datetime.timezone.utc)
    except (OSError, ValueError) as error:
        logger.warning(
            f"Unreadable debug log purge marker {marker}, purging nothing: {error}. To fix it, "
            f"delete {marker}: the next purge re-stamps it with the current time, which makes "
            f"every file present under {log_root} at that moment permanently protected (never "
            f"purged); only files written after that are purged once past retention."
        )
        return 0
    cutoff = today - datetime.timedelta(days=retention_days)
    deleted = 0
    for root, _dirs, files in os.walk(log_root, topdown=False):
        for name in files:
            # Excluded by name, never by age: the marker's own mtime can be later than the
            # timestamp it holds (e.g. copied or touched), which would otherwise make it
            # purgeable - and deleting it would re-arm the first-activation stamp.
            if name == _PURGE_MARKER_NAME:
                continue
            file_path = Path(root) / name
            try:
                mtime = datetime.datetime.fromtimestamp(
                    file_path.stat().st_mtime, tz=datetime.timezone.utc
                )
            except OSError:
                continue
            if enabled_since < mtime < cutoff:
                try:
                    file_path.unlink()
                    deleted += 1
                except OSError as error:
                    logger.warning(f"Could not purge expired log file {file_path}: {error}")
        # Bottom-up (topdown=False), so a directory only just emptied by this same pass is
        # already empty by the time we get here - safe to try removing every directory and
        # let rmdir fail harmlessly on any that still has content.
        try:
            Path(root).rmdir()
        except OSError:
            pass
    return deleted


# The logger every manage_agenda module logs through (each has `logger =
# logging.getLogger(__name__)`, a child of this one). setup_logging() attaches the LOG_FILE
# handler HERE, never to the root logger: socialModules configures the root logger at import
# time (a FileHandler on ~/usr/var/log/rssSocial.log plus a stdout handler), and
# logging.basicConfig() is a silent no-op once the root logger has any handler - which is
# exactly how LOG_FILE went unwritten for as long as the calls went through the root logger.
# Attaching to the package logger leaves socialModules' handlers alone; propagation stays on,
# so the root handlers (and tests' assertLogs()/caplog) still see these records too.
PACKAGE_LOGGER_NAME = "manage_agenda"


def _is_manage_agenda_handler(handler):
    return getattr(handler, "manage_agenda_handler", False)


def setup_logging(verbose: bool = False) -> None:
    """Send manage-agenda's own log records to LOG_FILE (log_file_path()), at LOG_LEVEL - or
    DEBUG, with a copy of INFO and above on stdout, when `verbose`.

    Only the "manage_agenda" logger is configured (see PACKAGE_LOGGER_NAME): the root logger
    and whatever other libraries attached to it are not touched. Calling this again (a
    second command in the same process, tests) replaces the handlers a previous call added
    rather than stacking a second copy of each - so every record is written once.
    """
    echo(t("base.setting_logging"))

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

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, date_format)

    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    package_logger.setLevel(log_level)
    for handler in list(package_logger.handlers):
        if _is_manage_agenda_handler(handler):
            package_logger.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.manage_agenda_handler = True
    package_logger.addHandler(file_handler)

    if verbose:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        console_handler.manage_agenda_handler = True
        package_logger.addHandler(console_handler)

    # Set specific log levels for noisy libraries
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logger.info(f"Logging initialized. Level: {logging.getLevelName(log_level)}, File: {log_file}")


def format_time(seconds):
    """Formats seconds into a human-readable string."""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h)}h {int(m)}m {s:.2f}s"


# The browser engines `playwright install` accepts.
BROWSERS = ("chromium", "firefox", "webkit", "chrome", "chrome-beta")


def install_playwright_browser(browser, on_output=None):
    """Run `python -m playwright install <browser>` as a child process, streaming its output
    line by line to `on_output` (echo by default), and return its exit code.

    A child process rather than playwright's own entry point in this one: that entry point
    reads sys.argv and calls sys.exit(), which a GUI cannot survive."""
    report = on_output or echo
    command = [sys.executable, "-m", "playwright", "install", browser]
    logger.info(f"Running: {' '.join(command)}")
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    except OSError as error:
        report(f"{type(error).__name__}: {error}")
        return 1
    assert process.stdout is not None
    for line in process.stdout:
        report(line.rstrip("\n"))
    return process.wait()
