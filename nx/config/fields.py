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

PostgresHost = Annotated[
    str | None,
    Field(
        title="Postgres host",
        description="Override the default Postgres host",
        examples=["localhost", "postgres"],
    ),
]

PostgresPort = Annotated[
    int | None,
    Field(
        title="Postgres port",
        description="Override the default Postgres port provided by POSTGRES_URL",
        examples=[5432],
        ge=0,
        le=65535,
    ),
]

PostgresName = Annotated[
    str | None,
    Field(
        title="Postgres database name",
        description="Override the default Postgres database name from POSTGRES_URL",
        examples=["nx"],
    ),
]

PostgresUser = Annotated[
    str | None,
    Field(
        title="Postgres user",
        description="Override the default Postgres user from POSTGRES_URL",
        examples=["nx"],
    ),
]

PostgresPassword = Annotated[
    str | None,
    Field(
        title="Postgres password",
        description="Override the default Postgres password from POSTGRES_URL",
        examples=["nx"],
    ),
]
