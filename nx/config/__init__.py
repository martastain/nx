import os
from typing import Any, Generic, TypeVar, cast

from dotenv import load_dotenv
from pydantic import BaseModel, PostgresDsn, RedisDsn, field_validator

from .fields import LogLevel, LogMode, ServerPort


class ConfigModel(BaseModel):
    log_level: LogLevel = "DEBUG"
    log_mode: LogMode = "text"
    log_context: bool = True
    server_host: str = "0.0.0.0"
    server_port: ServerPort = 8765
    postgres_url: PostgresDsn = PostgresDsn("postgresql://nx:nx@postgres:5432/nx")
    redis_url: RedisDsn = RedisDsn("redis://redis")

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: Any) -> LogLevel:
        assert isinstance(v, str), "Log level must be a string"
        return cast(LogLevel, v.upper())

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
