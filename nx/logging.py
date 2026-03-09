__all__ = ["logger"]

import contextlib
import enum
import sys
import time
import traceback
from collections.abc import Generator
from contextvars import ContextVar
from typing import Any, Literal, NotRequired, TypedDict, Unpack

from nx.config import config
from nx.utils import indent, json_dumps


class LogLevel(enum.IntEnum):
    """Log level."""

    TRACE = 0
    DEBUG = 1
    INFO = 2
    SUCCESS = 2
    WARNING = 3
    ERROR = 4
    CRITICAL = 5


class LoggerConfiguration(TypedDict):
    strip_prefixes: NotRequired[list[str]]


logger_configuration: LoggerConfiguration = {}
log_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


def _write_stderr(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _serialize(
    logger: "Logger",
    level: LogLevel,
    message: str,
    context: dict[str, Any],
) -> None:
    _context = {**(log_context.get() or {}), **context}

    frame = sys._getframe(2)  # noqa: SLF001
    module = None
    if frame is not None:
        caller_frame = frame.f_back
        if caller_frame is not None:
            module = caller_frame.f_globals.get("__name__", "unknown")
            _context["line"] = caller_frame.f_lineno
            _context["function"] = caller_frame.f_code.co_name

    if logger.log_mode == "json":
        payload = {
            "timestamp": time.time(),
            "level": level.name.lower(),
            "message": message,
            "module": module,
            **_context,
        }
        serialized = json_dumps(payload)
        _write_stderr(serialized)

    else:
        # Text mode logging
        formatted = f"{level.name.upper():<7} {module:<26} | {message}"
        _write_stderr(formatted)

        if config.log_context or "traceback" in context:
            # Put the module name and extra context info in a separate block
            tb = _context.pop("traceback", None)
            if tb:
                _write_stderr("\n" + indent(tb, 8))

            contextual_info = ""
            for k, v in _context.items():
                contextual_info += f"{k}: {v}\n"
            if contextual_info:
                _write_stderr(indent(contextual_info, 8))


class Logger:
    user: str = "nebula"
    level = LogLevel.DEBUG
    log_mode: Literal["text", "json"] = "text"

    def __call__(
        self,
        level: LogLevel,
        *args: Any,
        **context: Any,
    ) -> None:
        if level < self.level:
            return
        message = " ".join([str(arg) for arg in args])
        _serialize(self, level, message, context=context)

    def trace(self, *args: Any, **context: Any) -> None:
        self(LogLevel.TRACE, *args, **context)

    def debug(self, *args: Any, **context: Any) -> None:
        self(LogLevel.DEBUG, *args, **context)

    def info(self, *args: Any, **context: Any) -> None:
        self(LogLevel.INFO, *args, **context)

    def success(self, *args: Any, **context: Any) -> None:
        self(LogLevel.SUCCESS, *args, **context)

    def warn(self, *args: Any, **context: Any) -> None:
        self(LogLevel.WARNING, *args, **context)

    def warning(self, *args: Any, **context) -> None:
        self(LogLevel.WARNING, *args, **context)

    def error(self, *args: Any, **context) -> None:
        self(LogLevel.ERROR, *args, **context)

    def traceback(self, *args: Any, **context) -> str:
        msg = " ".join([str(arg) for arg in args])
        tb = traceback.format_exc()
        self(LogLevel.ERROR, *args, traceback=tb, **context)
        return msg

    def critical(self, *args: Any, **context) -> None:
        self(LogLevel.CRITICAL, *args, **context)

    @contextlib.contextmanager
    def contextualize(self, **context: Any) -> Generator[None, None, None]:
        """Add extra context to the current log context."""
        current = log_context.get() or {}
        updated = {**current, **context}
        log_context.set(updated)
        try:
            yield
        finally:
            log_context.set(current)


logger = Logger()


def init_logger(**kwargs: Unpack[LoggerConfiguration]) -> None:
    pass
