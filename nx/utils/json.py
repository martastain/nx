import datetime
import json
from typing import Any


def json_loads(s: str) -> Any:
    """Load a JSON string into a Python object"""
    return json.loads(s)


def default_serializer(obj: Any) -> Any:
    """Default JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime.datetime | datetime.date):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def json_dumps(obj: Any) -> str:
    """Dump a Python object into a JSON string"""

    return json.dumps(obj, default=default_serializer)
