import asyncio
import json
from typing import Any, cast

from nx.exceptions import BaseNXError


class FFProbeError(BaseNXError):
    """Exception raised when metadata extraction fails."""


async def ffprobe(path: str) -> dict[str, Any]:
    """Run ffprobe on the given path and return the output as a dictionary."""
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise FFProbeError(f"{stderr.decode()}")

    return cast("dict[str, Any]", json.loads(stdout.decode()))
