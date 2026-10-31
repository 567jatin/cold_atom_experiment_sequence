"""
Logging utility module for the FPGA TTL and Analog Waveform Sequence Controller.

Provides:
- setup_logger: Create loggers with timestamped formatting and optional file output.
- LogSignalHandler: A logging handler that emits PySide6 signals for GUI integration.
- get_app_logger: Retrieve the main application logger.
"""

import logging
import threading
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_LOGGER_NAME = "fpga_sequence_controller"
_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"  # ISO 8601

_logger_lock = threading.RLock()
_configured_loggers: dict[str, logging.Logger] = {}


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------
def setup_logger(
    name: str,
    log_file: str | None = None,
    level: int = logging.DEBUG,
) -> logging.Logger:
    """Create (or retrieve) a named logger with console and optional file handlers.

    Parameters
    ----------
    name:
        Logger name (dot-separated hierarchy supported).
    log_file:
        If provided, a ``FileHandler`` writing to this path is added.
    level:
        Logging level applied to the logger and all new handlers.

    Returns
    -------
    logging.Logger
        The configured logger instance.
    """
    with _logger_lock:
        if name in _configured_loggers:
            logger = _configured_loggers[name]
            if log_file and not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
                formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
                formatter.converter = lambda *_args: datetime.now(timezone.utc).timetuple()
                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setLevel(level)
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
            return logger

        logger = logging.getLogger(name)
        logger.setLevel(level)

        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
        # Force UTC timestamps
        formatter.converter = lambda *_args: datetime.now(timezone.utc).timetuple()

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # Optional file handler
        if log_file is not None:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        _configured_loggers[name] = logger
        return logger


# ---------------------------------------------------------------------------
# PySide6 signal bridge (avoids QObject + Handler multiple-inheritance issues)
# ---------------------------------------------------------------------------
class _LogSignalEmitter(QObject):
    """Internal QObject that owns the Qt signal."""

    log_message = Signal(str, str)  # (level_name, formatted_message)


class LogSignalHandler(logging.Handler):
    """A :class:`logging.Handler` that forwards log records as PySide6 signals.

    Usage::

        handler = LogSignalHandler()
        handler.log_message.connect(some_slot)   # convenience proxy
        logger.addHandler(handler)

    The ``log_message`` attribute is a direct reference to the underlying
    :pyqt:`Signal` so callers can connect/disconnect without reaching into
    private internals.
    """

    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self._emitter = _LogSignalEmitter()
        # Expose the signal at handler level for convenience.
        self.log_message: Signal = self._emitter.log_message

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003 (shadows builtin)
        """Format *record* and emit the ``log_message`` signal (thread-safe)."""
        try:
            msg = self.format(record)
            self._emitter.log_message.emit(record.levelname, msg)
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Application-level convenience
# ---------------------------------------------------------------------------
def get_app_logger(name: str | None = None) -> logging.Logger:
    """Return the main application logger (or a child logger), creating it if necessary."""
    with _logger_lock:
        if APP_LOGGER_NAME not in _configured_loggers:
            main_logger = setup_logger(APP_LOGGER_NAME)
        else:
            main_logger = _configured_loggers[APP_LOGGER_NAME]

    if name and name != APP_LOGGER_NAME:
        return main_logger.getChild(name)
    return main_logger
