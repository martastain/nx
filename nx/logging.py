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


_get_frame = sys._getframe  # noqa: SLF001


def _serialize(
    logger: "Logger",
    level: LogLevel,
    message: str,
    context: dict[str, Any],
) -> None:

    # Combine the context from the context variable and
    # the inline context passed to the log method.
    # The inline context takes precedence.

    _context = log_context.get()
    if _context is None:
        _context = {}
    if context:
        _context.update(context)

    # Get the caller's module name, function name, and line number
    # and include them in the log context. This is done by inspecting the call stack.

    frame = _get_frame(2)
    if frame is not None:
        caller_frame = frame.f_back
        if caller_frame is not None:
            _context["code_module"] = caller_frame.f_globals.get("__name__", "unknown")
            _context["code_func"] = caller_frame.f_code.co_name
            _context["code_file"] = caller_frame.f_code.co_filename
            _context["code_line"] = caller_frame.f_lineno

    # Format the log message based on the logger's log mode (text or json).
    # In text mode, include the log level and message. If there is context,
    # include it in a separate block. In json mode, serialize the entire
    # payload as JSON.

    if logger.log_mode == "json":
        payload = {
            "timestamp": time.time(),
            "level": level.name.lower(),
            "message": message,
            **_context,
        }
        serialized = json_dumps(payload)
        _write_stderr(serialized)
        return

    # Text mode logging

    formatted = f"{level.name.upper():<7} {message}"

    if config.log_context or "traceback" in context:
        # Put the module name and extra context info in a separate block
        tb = _context.pop("traceback", "").strip()
        if tb:
            formatted += "\n\n" + indent(tb, 8)

        contextual_info = "\n\n"
        for k, v in _context.items():
            contextual_info += f"{k}: {v}\n"
        if contextual_info:
            formatted += indent(contextual_info, 8)

    _write_stderr(formatted)


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

    def warning(self, *args: Any, **context: Any) -> None:
        self(LogLevel.WARNING, *args, **context)

    def error(self, *args: Any, **context: Any) -> None:
        self(LogLevel.ERROR, *args, **context)

    def traceback(self, *args: Any, **context: Any) -> str:
        msg = " ".join([str(arg) for arg in args])
        tb = traceback.format_exc()
        self(LogLevel.ERROR, *args, traceback=tb, **context)
        return msg

    def critical(self, *args: Any, **context: Any) -> None:
        self(LogLevel.CRITICAL, *args, **context)

    @contextlib.contextmanager
    def contextualize(self, **context: Any) -> Generator[None, None, None]:
        """Add extra context to the current log context."""

        current = log_context.get() or {}
        updated = {**current, **context}
        token = log_context.set(updated)
        try:
            yield
        finally:
            log_context.reset(token)


logger = Logger()


def init_logger(**kwargs: Unpack[LoggerConfiguration]) -> None:
    pass
