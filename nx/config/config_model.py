from typing import Any, Self, cast
from urllib.parse import urlparse

from pydantic import BaseModel, PostgresDsn, RedisDsn, field_validator, model_validator

from .fields import (
    LogLevel,
    LogMode,
    PostgresHost,
    PostgresName,
    PostgresPassword,
    PostgresPort,
    PostgresUser,
    ServerPort,
)


class ConfigModel(BaseModel):
    log_level: LogLevel = "DEBUG"
    log_mode: LogMode = "text"
    log_context: bool = True
    server_host: str = "0.0.0.0"
    server_port: ServerPort = 8765
    postgres_url: PostgresDsn = PostgresDsn("postgresql://nx:nx@postgres:5432/nx")
    redis_url: RedisDsn = RedisDsn("redis://redis")

    # database connection overrides
    # The folowing fields are used to override the default connection settings
    # provided by POSTGRES_URL

    postgres_host: PostgresHost = None
    postgres_port: PostgresPort = None
    postgres_name: PostgresName = None
    postgres_user: PostgresUser = None
    postgres_password: PostgresPassword = None

    #
    # Tools setup
    #

    tool_uuid_use_hyphens: bool = False

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: Any) -> LogLevel:
        assert isinstance(v, str), "Log level must be a string"
        return cast("LogLevel", v.upper())

    @model_validator(mode="after")
    def construct_final_postgres_url(self) -> Self:
        """Synchronize the postgres_url with the individual fields."""
        parsed = urlparse(str(self.postgres_url))
        # Extract the relevant components
        user = parsed.username if self.postgres_user is None else self.postgres_user
        password = (
            parsed.password
            if self.postgres_password is None
            else self.postgres_password
        )
        host = parsed.hostname if self.postgres_host is None else self.postgres_host
        port = parsed.port or 5432 if self.postgres_port is None else self.postgres_port
        database = parsed.path[1:] if self.postgres_name is None else self.postgres_name

        # rebuild the URL with the overrides

        self.postgres_url = PostgresDsn.build(
            scheme="postgresql",
            username=user,
            password=password,
            host=host,
            port=port,
            path=database,
        )

        # and populate the fields again, so all values are in sync

        parsed = urlparse(str(self.postgres_url))

        self.postgres_host = parsed.hostname
        self.postgres_port = parsed.port or 5432
        self.postgres_name = parsed.path[1:]
        self.postgres_user = parsed.username
        self.postgres_password = parsed.password

        return self

    def initialize(self, **kwargs: Any) -> None:
        _ = kwargs
