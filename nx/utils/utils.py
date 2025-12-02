import hashlib
import json
import textwrap
import uuid
from typing import Any

from nx.config import config


def json_dumps(data: Any, **kwargs: Any) -> str:
    return json.dumps(data, **kwargs)


def json_loads(data: Any, **kwargs: Any) -> Any:
    return json.loads(data, **kwargs)


def indent(text: str, amount: int = 4) -> str:
    return textwrap.indent(text, " " * amount)


def normalize_uuid(
    value: str | uuid.UUID | None,
    *,
    allow_nulls: bool = False,
    use_hyphens: bool | None = None,
) -> str | None:
    """Convert UUID object or its string representation to string

    Use hyphens in the output if `use_hyphens` is True.
    32-character hex string if `use_hyphens` is False.
    If `use_hyphens` is None, use the global config setting.
    """

    if use_hyphens is None:
        use_hyphens = config.tool_uuid_use_hyphens

    if value is None and allow_nulls:
        return None

    if isinstance(value, uuid.UUID):
        return str(value) if use_hyphens else value.hex

    if isinstance(value, str):
        input_len = len(value)
        if input_len == 32:
            return str(uuid.UUID(value)) if use_hyphens else value

        if input_len == 36:
            return value if use_hyphens else value.replace("-", "")
    raise ValueError(f"Invalid UUID {value}")


def hash_data(data: Any) -> str:
    """Create a SHA-256 hash from arbitrary (json-serializable) data."""
    if isinstance(data, int | float | bool | dict | list | tuple):
        data = json_dumps(data)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def create_uuid(
    *,
    use_hyphens: bool | None = None,
) -> str:
    """Create a new UUID."""

    use_hyphens = (
        use_hyphens if use_hyphens is not None else config.tool_uuid_use_hyphens
    )

    if use_hyphens:
        return str(uuid.uuid4())
    return uuid.uuid4().hex
