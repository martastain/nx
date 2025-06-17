__all__ = [
    "ConfigModel",
    "ConfigProxy",
    "config",
]

import os
from typing import Any, Generic, TypeVar, cast

from dotenv import load_dotenv
from pydantic import BaseModel

from .config_model import ConfigModel

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

            fkey = key.lower().removeprefix(full_env_prefix)
            if fkey in self._fields:
                env_data[fkey] = value

        self._config = self._config_model(**env_data)

    def __getattr__(self, key: str) -> Any:
        if not self._config:
            raise AttributeError("Config not initialized. Call initialize() first.")
        return getattr(self._config, key)


_config_proxy = ConfigProxy()  # type: ignore[var-annotated]
config = cast("ConfigModel", _config_proxy)
