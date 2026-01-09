"""Structured logging configuration for Evening News."""

import logging
import sys
from typing import Optional
from ..config import get_settings


class ColoredFormatter(logging.Formatter):
    """Custom formatter with color support for console output."""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        """Format log record with colors."""
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


class DigestFormatter(logging.Formatter):
    """Formatter for digest-related logs with structured context."""

    def format(self, record):
        """Add digest-specific context to log records."""
        # Add component prefix if available
        component = getattr(record, 'component', 'DIGEST')
        record.component = component

        # Format message
        message = super().format(record)

        # Add context if available
        context = getattr(record, 'context', {})
        if context:
            context_str = " | ".join(f"{k}={v}" for k, v in context.items())
            message = f"{message} [{context_str}]"

        return message


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    use_colors: bool = True
) -> None:
    """
    Setup structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file to log to
        use_colors: Whether to use colored output in console
    """
    settings = get_settings()
    log_level = level or settings.log_level

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # Formatter for console
    if use_colors and sys.stdout.isatty():
        console_formatter = ColoredFormatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        console_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        file_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Set specific log levels for noisy libraries
    logging.getLogger('aiosqlite').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)


def get_logger(name: str, component: str = 'DIGEST') -> logging.Logger:
    """
    Get a logger with component-specific context.

    Args:
        name: Logger name (typically __name__)
        component: Component identifier for filtering

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Add adapter for automatic context injection
    return LoggingAdapter(logger, {'component': component})


class LoggingAdapter(logging.LoggerAdapter):
    """Logging adapter that adds component context to all records."""

    def __init__(self, logger: logging.Logger, extra: dict):
        """Initialize adapter with logger and extra context."""
        super().__init__(logger, extra)

    def process(self, msg, kwargs):
        """Process log message to add extra context."""
        # Merge extra context
        extra = kwargs.get('extra', {})
        extra.update(self.extra)
        kwargs['extra'] = extra
        return msg, kwargs


def log_operation(
    logger: logging.Logger,
    operation: str,
    status: str,
    **context
):
    """
    Log operation with structured context.

    Args:
        logger: Logger instance
        operation: Operation name (e.g., 'generate_summary', 'split_message')
        status: Operation status (e.g., 'started', 'completed', 'failed')
        **context: Additional context key-value pairs
    """
    context_str = " | ".join(f"{k}={v}" for k, v in context.items())
    message = f"{operation} | {status}"

    if context_str:
        message = f"{message} | {context_str}"

    if status == 'completed':
        logger.info(message)
    elif status == 'failed':
        logger.error(message)
    elif status == 'started':
        logger.info(message)
    else:
        logger.debug(message)
