import os
from typing import Any, Generic, Self, TypeVar, cast
from urllib.parse import urlparse

from dotenv import load_dotenv
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

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: Any) -> LogLevel:
        assert isinstance(v, str), "Log level must be a string"
        return cast(LogLevel, v.upper())

    @model_validator(mode="after")
    def construct_final_postgres_url(self) -> Self:
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

        return self

    def initialize(self, **kwargs: Any) -> None:
        _ = kwargs
        pass


T = TypeVar("T", bound=BaseModel)


class ConfigProxy(Generic[T]):
    _instance: "ConfigProxy[T] | None" = None
    _config_model: type[T]
    _fields: set[str]
    _config: BaseModel | None = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "ConfigProxy[T]":
        _ = args, kwargs
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        pass

    def initialize(self, config_model: type[T], env_prefix: str) -> None:
        self._config_model = config_model
        self._fields = set(config_model.model_fields)
        self._env_prefix = env_prefix

        full_env_prefix = f"{env_prefix}_".lower()
        load_dotenv()
        env_data = {}
        for key, value in dict(os.environ).items():
            if not key.lower().startswith(full_env_prefix):
                continue

            key = key.lower().removeprefix(full_env_prefix)
            if key in self._fields:
                env_data[key] = value

        self._config = self._config_model(**env_data)

    def __getattr__(self, key: str) -> Any:
        if not self._config:
            raise AttributeError("Config not initialized. Call initialize() first.")
        return getattr(self._config, key)

    def resolve(self) -> T:
        if not self._config:
            raise AttributeError("Config not initialized. Call initialize() first.")
        return cast(T, self._config)


_config_proxy = ConfigProxy()  # type: ignore
config = cast(ConfigModel, _config_proxy)
