from typing import Annotated, Literal

from pydantic import Field

LogMode = Annotated[
    Literal["text", "json"],
    Field(
        title="Log mode",
        description="The log mode for the server",
        examples=["text"],
    ),
]

LogLevel = Annotated[
    Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "TRACE"],
    Field(
        title="Log Level",
        description="The log level for the server",
        examples=["INFO"],
    ),
]

ServerPort = Annotated[
    int,
    Field(
        title="Port",
        description="The port the server will listen on",
        examples=[8765],
        ge=0,
        le=65535,
    ),
]
