import json
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any, TypeVar

from pydantic import BaseModel
from redis import asyncio as aioredis
from redis.asyncio.client import PubSub

from nx.config import config
from nx.logging import logger

T = TypeVar("T", bound=Callable[..., Coroutine[Any, Any, Any]])


def ensure_connection(func: T) -> T:
    """Decorator to ensure the connection pool is initialized."""

    async def wrapper(self: "Redis", *args: Any, **kwargs: Any) -> Any:
        if not self.connected:
            await self.connect()
        return await func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class Redis:
    _instance: "Redis | None" = None
    _pool: aioredis.Redis | None = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "Redis":
        _ = args, kwargs
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    connected: bool = False
    channel: str = "nx"

    async def connect(self) -> None:
        """Create a Redis connection pool"""
        if self._pool is None:
            self._pool = aioredis.from_url(str(config.redis_url))  # type: ignore[no-untyped-call]
        assert self._pool is not None, "Redis pool is not initialized"
        try:
            await self._pool.set("CONN", "alive")
        except ConnectionError:
            logger.error("Redis connection failed")
        except OSError:
            logger.error("Redis connection failed (OS error)")
        else:
            self.connected = True
            return
        self.connected = False
        raise ConnectionError("Redis is not connected")

    @ensure_connection
    async def get(self, namespace: str, key: str) -> Any:
        """Get a value from Redis"""
        assert self._pool is not None, "Redis pool is not initialized"
        return await self._pool.get(f"{namespace}:{key}")

    @ensure_connection
    async def get_json(self, namespace: str, key: str) -> Any:
        """Get a JSON-serialized value from Redis"""
        value = await self.get(namespace, key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.decoder.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {namespace}:{key}") from e

    @ensure_connection
    async def set(
        self,
        namespace: str,
        key: str,
        value: str | bytes | float | bool | None,
        *,
        ttl: int = 0,
    ) -> None:
        """Create/update a record in Redis

        Optional ttl argument may be provided to set expiration time.
        """
        command: list[Any] = ["set", f"{namespace}:{key}", value]
        if ttl:
            command.extend(["ex", str(ttl)])
        assert self._pool is not None, "Redis pool is not initialized"
        await self._pool.execute_command(*command)  # type: ignore[no-untyped-call]

    @ensure_connection
    async def set_json(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        ttl: int = 0,
    ) -> None:
        """Create/update a record in Redis with JSON-serialized value"""
        if isinstance(value, BaseModel):
            payload = value.model_dump_json(exclude_unset=True, exclude_defaults=True)
        else:
            payload = json.dumps(value)
        await self.set(namespace, key, payload, ttl=ttl)

    @ensure_connection
    async def delete(self, namespace: str, key: str) -> None:
        """Delete a record from Redis"""
        assert self._pool is not None, "Redis pool is not initialized"
        await self._pool.delete(f"{namespace}:{key}")

    @ensure_connection
    async def incr(self, namespace: str, key: str) -> int:
        """Increment a value in Redis"""
        assert self._pool is not None, "Redis pool is not initialized"
        res: int = await self._pool.incr(f"{namespace}:{key}")
        return res

    @ensure_connection
    async def expire(self, namespace: str, key: str, ttl: int) -> None:
        """Set a TTL for a key in Redis"""
        assert self._pool is not None, "Redis pool is not initialized"
        await self._pool.expire(f"{namespace}:{key}", ttl)

    @ensure_connection
    async def pubsub(self) -> PubSub:
        """Create a Redis pubsub connection"""
        if not self.connected:
            await self.connect()
        assert self._pool is not None, "Redis pool is not initialized"
        return self._pool.pubsub()

    @ensure_connection
    async def publish(self, message: str) -> None:
        """Publish a message to a Redis channel"""
        assert self._pool is not None, "Redis pool is not initialized"
        await self._pool.publish(self.channel, message)

    @ensure_connection
    async def ping(self) -> None:
        """Ping the Redis server to check connection"""
        assert self._pool is not None, "Redis pool is not initialized"
        await self._pool.execute_command("ping")  # type: ignore[no-untyped-call]

    async def iterate(self, namespace: str) -> AsyncGenerator[tuple[str, str]]:
        """Iterate over stored keys

        Yield (key, payload) tuples matching given namespace.
        Namespace prefix is stripped from keys.
        """
        if not self.connected:
            await self.connect()
        assert self._pool is not None, "Redis pool is not initialized"

        async for key in self._pool.scan_iter(match=f"{namespace}:*"):
            key_without_ns = key.decode("ascii").removeprefix(f"{namespace}:")
            payload = await self._pool.get(key)
            yield key_without_ns, payload

    async def iterate_json(self, namespace: str) -> AsyncGenerator[tuple[str, Any]]:
        """Iterate over stored keys

        Yield (key, payload) tuples matching given namespace.
        Namespace prefix is stripped from keys.

        This method is same as iterate() but deserializes
        JSON payloads in the process.
        """
        async for key, payload in self.iterate(namespace):
            if payload is None:
                logger.warning(f"Redis {namespace}:{key} has no value (JSON expected)")
                continue
            yield key, json.loads(payload)


redis = Redis()
