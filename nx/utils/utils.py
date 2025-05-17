import hashlib
import json
import textwrap
import uuid
from typing import Any


def json_dumps(data: Any, **kwargs: Any) -> str:
    return json.dumps(data, **kwargs)


def json_loads(data: Any, **kwargs: Any) -> Any:
    return json.loads(data, **kwargs)


def indent(text: str, amount: int = 4) -> str:
    return textwrap.indent(text, " " * amount)


def normalize_uuid(
    value: str | uuid.UUID | None,
    allow_nulls: bool = False,
) -> str | None:
    """Convert UUID object or its string representation to string"""
    if value is None and allow_nulls:
        return None
    if isinstance(value, uuid.UUID):
        return value.hex
    if isinstance(value, str):
        entity_id = value.replace("-", "")
        if len(entity_id) == 32:
            return entity_id
    raise ValueError(f"Invalid entity ID {entity_id}")


def hash_data(data: Any) -> str:
    """Create a SHA-256 hash from arbitrary (json-serializable) data."""
    if isinstance(data, int | float | bool | dict | list | tuple):
        data = json_dumps(data)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def create_uuid() -> str:
    """Create a new UUID."""
    return uuid.uuid4().hex
