"""
Centralized, persist-to-disk logging setup for TC²-BBS.

Produces (under the resolved log directory):
    app.log      - main application log: INFO/WARNING/ERROR, plus DEBUG when enabled.
                   Anything logged with the root logger (or a logger that isn't one
                   of the dedicated loggers below) ends up here. This is also where
                   features that are *not* enabled fall back to (e.g. JS8Call /
                   sync chatter when those features are off), so nothing is lost.
    js8call.log  - JS8Call integration log. Only created when JS8Call is enabled
                   (i.e. a db_file is configured). Otherwise JS8Call log lines
                   fall back to app.log.
    sync.log     - BBS-to-BBS mail/bulletin sync log. Only created when sync is
                   enabled (i.e. bbs_nodes is configured). Otherwise sync log
                   lines fall back to app.log.
    access.log   - One-liner per inbound user message / outbound reply, with
                   sender/recipient metadata, so a problem report can be traced
                   after the fact. Always enabled. When --debug/DEBUG_BBS is on,
                   raw packets/responses are also dumped (DEBUG level) alongside
                   the one-liners.

Log dir resolution order: --log-dir CLI arg > LOG_DIR env var > ./logs
Debug resolution order: --debug CLI flag > DEBUG_BBS env var
"""

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional

MAX_BYTES = 10 * 1024 * 1024  # 10 MiB per file
BACKUP_COUNT = 5

_FALSY = {"", "0", "false", "no", "off"}

_log_dir: Optional[Path] = None
_debug: bool = False


def resolve_log_dir(cli_log_dir: Optional[str] = None) -> Path:
    """Resolve the log directory from --log-dir, LOG_DIR env, or ./logs, and create it."""
    log_dir = cli_log_dir or os.environ.get("LOG_DIR") or str(Path(os.getcwd()) / "logs")
    path = Path(log_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_debug(cli_debug: bool = False) -> bool:
    """Resolve the debug flag from --debug or the DEBUG_BBS env var."""
    if cli_debug:
        return True
    return os.environ.get("DEBUG_BBS", "").strip().lower() not in _FALSY


def _make_file_handler(path: Path, level: int, fmt: str) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S"))
    return handler


def setup_logging(log_dir: Path, debug: bool = False) -> None:
    """
    Configure the root logger with a console handler and the main app.log
    handler. Must be called once, early, before any other loggers are used.
    """
    global _log_dir, _debug
    _log_dir = Path(log_dir)
    _debug = debug

    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s - %(levelname)s - %(message)s"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = []

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S"))
    root.addHandler(console_handler)

    root.addHandler(_make_file_handler(_log_dir / "app.log", level, fmt))


def get_feature_logger(name: str, filename: str, enabled: bool, debug: Optional[bool] = None) -> logging.Logger:
    """
    Get/configure a named logger for an optional feature (e.g. 'js8call', 'sync').

    When `enabled` is True, the logger gets its own rotating file (under the log
    dir) and stops propagating to the root logger. When `enabled` is False, no
    file is created and the logger propagates to the root logger instead, so its
    (presumably sparse) messages still land in app.log.
    """
    if debug is None:
        debug = _debug
    level = logging.DEBUG if debug else logging.INFO

    logger = logging.getLogger(name)
    logger.handlers = []
    logger.setLevel(level)

    if enabled and _log_dir is not None:
        fmt = "%(asctime)s - %(levelname)s - %(message)s"
        logger.addHandler(_make_file_handler(_log_dir / filename, level, fmt))
        logger.propagate = False
    else:
        logger.propagate = True

    return logger


def get_access_logger(debug: Optional[bool] = None) -> logging.Logger:
    """
    Get/configure the 'access' logger: always-on one-liner log of user messages
    and replies. At DEBUG level, raw packets/responses are also logged.
    """
    if debug is None:
        debug = _debug
    level = logging.DEBUG if debug else logging.INFO

    logger = logging.getLogger("access")
    logger.handlers = []
    logger.setLevel(level)
    logger.propagate = False

    if _log_dir is not None:
        fmt = "%(asctime)s - %(levelname)s - %(message)s"
        logger.addHandler(_make_file_handler(_log_dir / "access.log", level, fmt))

    return logger
