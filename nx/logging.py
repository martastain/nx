__all__ = ["logger"]

import sys
import time
from typing import TYPE_CHECKING, NotRequired, TypedDict, Unpack

from loguru import logger as loguru_logger

from nx.config import config
from nx.utils import indent, json_dumps

if TYPE_CHECKING:
    from loguru import Message


class LoggerConfiguration(TypedDict):
    strip_prefixes: NotRequired[list[str]]


logger_configuration: LoggerConfiguration = {}


def _write_stderr(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _serializer(message: "Message") -> None:
    record = message.record
    level = record["level"].name
    text = record["message"]
    module = record["extra"].pop("module", None) or record["name"]

    if isinstance(module, str):
        for prefix in logger_configuration.get("strip_prefixes", []):
            module = module.removeprefix(f"{prefix}.")

    if config.log_mode == "json":
        payload = {
            "timestamp": time.time(),
            "level": level.lower(),
            "message": text,
            "module": module,
            **record["extra"],
        }
        serialized = json_dumps(payload)
        _write_stderr(serialized)

    else:
        # Text mode logging

        formatted = f"{level:<7} {module:<26} | {text}"
        _write_stderr(formatted)

        if config.log_context or "traceback" in record["extra"]:
            # Put the module name and extra context info in a separate block
            contextual_info = ""
            for k, v in record["extra"].items():
                val = v
                if k == "traceback":
                    val = f"\n{indent(v)}"
                contextual_info += f"{k}: {val}\n"
            if contextual_info:
                _write_stderr(indent(contextual_info))


logger = loguru_logger.bind()


def init_logger(**kwargs: Unpack[LoggerConfiguration]) -> None:
    logger_configuration.update(kwargs)
    logger.remove(0)
    logger.add(_serializer, level=config.log_level)
