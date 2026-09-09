import inspect
import json
from collections.abc import AsyncGenerator, Callable, Coroutine
from functools import wraps
from string import Formatter
from types import UnionType
from typing import (
    Any,
    Literal,
    Self,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel
from redis import asyncio as aioredis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from nx.config import config
from nx.logging import logger
from nx.utils.json import json_dumps, json_loads

type CacheModel = type[BaseModel] | Literal["bytes"] | None
type KeyBuilder = Callable[[tuple[Any, ...], dict[str, Any]], str]

_CACHE_IO_ERRORS = (RedisError, OSError)
_CACHE_DECODE_ERRORS = (ValueError, TypeError)


def _template_field_names(key_template: str) -> set[str]:
    """Return the argument names referenced by a cache key template."""
    names: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(key_template):
        if field_name is None:
            continue
        root = field_name.partition(".")[0].partition("[")[0]
        if not root or root.isdigit():
            raise ValueError(
                f"Cache key template {key_template!r} uses the positional field "
                f"'{{{field_name}}}'. Use named fields such as '{{item_id}}' so "
                f"keys stay stable regardless of how the function is called."
            )
        names.add(root)
    return names


def _has_unstable_repr(value: Any) -> bool:
    """True if formatting `value` embeds its memory address in the key.

    Objects that inherit all of object's formatting hooks render as
    `<Thing object at 0x...>`, which differs on every instance: the cache would
    never hit and the keyspace would grow without bound.
    """
    hooks = ("__format__", "__repr__", "__str__")
    # object itself is dropped from the MRO: it is the source of the defaults.
    return not any(
        hook in vars(klass) for klass in type(value).__mro__[:-1] for hook in hooks
    )


def _make_key_builder(func: Callable[..., Any], key_template: str) -> KeyBuilder:
    """Validate a key template against `func` and return a key builder for it.

    The template is checked at decoration time so a typo surfaces on import
    rather than silently sending every call to a different key.
    """
    sig = inspect.signature(func)
    params = set(sig.parameters) - {"self", "cls"}
    accepts_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )

    fields = _template_field_names(key_template)
    if not accepts_kwargs and (unknown := sorted(fields - params)):
        raise ValueError(
            f"Cache key template {key_template!r} for {func.__qualname__}() "
            f"references unknown argument(s): {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(params)) or 'none'}."
        )

    warned: set[str] = set()

    def build(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        format_args: dict[str, Any] = {}
        for name, value in bound.arguments.items():
            # Instance/class args are excluded: the template addresses the call
            # by its arguments, not by which object it was invoked on.
            if name in {"self", "cls"}:
                continue
            # **kwargs arrive nested under the parameter name; flatten them so
            # a template can reference the keywords it actually received.
            if sig.parameters[name].kind is inspect.Parameter.VAR_KEYWORD:
                format_args.update(value)
            else:
                format_args[name] = value

        for name in fields - warned:
            if _has_unstable_repr(format_args.get(name)):
                warned.add(name)
                logger.warning(
                    f"Cache key for {func.__qualname__}() formats argument "
                    f"'{name}' of type {type(format_args[name]).__name__}, which "
                    f"has no __str__/__repr__. The key will differ on every call. "
                    f"Format a stable attribute such as '{{{name}.id}}' instead."
                )

        return key_template.format(**format_args)

    return build


def _infer_model(func: Callable[..., Any]) -> type[BaseModel] | None:
    """Derive the cache model from the return annotation, if it is unambiguous.

    Without a model, JSON round-trips lose types: a BaseModel comes back as a
    dict and a datetime as a string. Picking the annotation up automatically
    means the common case stays symmetric between a cache hit and a miss.
    """
    try:
        annotation = get_type_hints(func).get("return")
    except Exception as e:  # unresolvable forward refs, exotic annotations, ...
        logger.trace(f"Cannot resolve return type of {func.__qualname__}(): {e}")
        return None

    if get_origin(annotation) in {Union, UnionType}:
        candidates = [a for a in get_args(annotation) if a is not type(None)]
    else:
        candidates = [annotation]

    if len(candidates) == 1 and isinstance(candidates[0], type):
        model = candidates[0]
        if issubclass(model, BaseModel):
            return model
    return None


def _make_lossy_warner(
    func: Callable[..., Any],
    model: CacheModel,
) -> Callable[[Any], None]:
    """Return a guard that warns once if results cannot round-trip faithfully.

    Caching a BaseModel with no model configured stores it fine but hands back
    a plain dict on every hit, so behaviour changes the moment the cache warms
    up. That is worth saying out loud exactly once per decorated function.
    """
    warned = False

    def check(value: Any) -> None:
        nonlocal warned
        if warned or model is not None or not isinstance(value, BaseModel):
            return
        warned = True
        logger.warning(
            f"{func.__qualname__}() caches {type(value).__name__} without a "
            f"model, so cache hits will return plain dicts instead. Annotate "
            f"the return type or pass model= to cached()."
        )

    return check


def _serialize(value: Any, model: CacheModel) -> str | bytes:
    """Encode a return value for storage."""
    if model == "bytes":
        if not isinstance(value, bytes | bytearray | memoryview):
            raise TypeError(
                f"model='bytes' expects a bytes-like result, got {type(value).__name__}"
            )
        return bytes(value)
    if isinstance(value, BaseModel):
        # A full dump, unlike set_json(): exclude_unset/exclude_defaults would
        # let a later change of a field default silently rewrite cached values.
        return value.model_dump_json()
    return json_dumps(value)


def _deserialize(raw: bytes, model: CacheModel) -> Any:
    """Decode a stored payload back into a return value."""
    if model == "bytes":
        return raw
    if model is None:
        return json_loads(raw)
    if raw.strip() == b"null":
        return None
    return model.model_validate_json(raw)


def ensure_connection[T: Callable[..., Coroutine[Any, Any, Any]]](func: T) -> T:
    """Decorator to ensure the connection pool is initialized."""

    async def wrapper(self: "Redis", *args: Any, **kwargs: Any) -> Any:
        if not self.connected:
            await self.connect()
        return await func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class Redis:
    _instance: "Redis | None" = None
    _pool: aioredis.Redis | None = None

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        _ = args, kwargs
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cast("Self", cls._instance)

    connected: bool = False
    channel: str = "nx"

    async def connect(self) -> None:
        """Create a Redis connection pool"""
        if self._pool is None:
            self._pool = aioredis.from_url(str(config.redis_url))
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
            return json_loads(value)
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
            payload = json_dumps(value)
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

    async def _cache_read(
        self,
        ns: str,
        subkey: str,
        model: CacheModel,
    ) -> tuple[bool, Any]:
        """Read one cache entry, returning (hit, value).

        Anything that goes wrong - Redis down, a payload that no longer parses
        into `model` - is reported as a miss so the caller recomputes.
        """
        try:
            raw = await self.get(ns, subkey)
        except _CACHE_IO_ERRORS as e:
            logger.warning(f"Cache read failed for {ns}:{subkey}: {e}")
            return False, None

        if raw is None:
            return False, None

        try:
            return True, _deserialize(raw, model)
        except _CACHE_DECODE_ERRORS as e:
            logger.warning(f"Discarding unreadable cache entry {ns}:{subkey}: {e}")
            return False, None

    async def _cache_write(
        self,
        ns: str,
        subkey: str,
        value: Any,
        model: CacheModel,
        ttl: int,
    ) -> None:
        """Store one cache entry. Failing to cache is never fatal."""
        try:
            await self.set(ns, subkey, _serialize(value, model), ttl=ttl)
        except (*_CACHE_IO_ERRORS, *_CACHE_DECODE_ERRORS) as e:
            logger.warning(f"Cache write failed for {ns}:{subkey}: {e}")

    async def _cache_extend(self, ns: str, subkey: str, ttl: int) -> None:
        """Refresh the TTL of a cache entry that was just read."""
        try:
            await self.expire(ns, subkey, ttl)
        except _CACHE_IO_ERRORS as e:
            logger.warning(f"Could not extend TTL of {ns}:{subkey}: {e}")

    async def _cache_drop(self, ns: str, subkey: str) -> None:
        """Remove one cache entry."""
        try:
            await self.delete(ns, subkey)
        except _CACHE_IO_ERRORS as e:
            logger.warning(f"Cache invalidation failed for {ns}:{subkey}: {e}")

    def cached[F: Callable[..., Coroutine[Any, Any, Any]]](
        self,
        ns: str,
        key: str,
        *,
        ttl: int = 60 * 5,
        model: CacheModel = None,
        auto_extend: bool = False,
    ) -> Callable[[F], F]:
        """Cache the result of an async function in Redis.

        `key` is a format template resolved against the decorated function's
        arguments, e.g. "user:{user_id}". It is validated at decoration time,
        so a name that does not match a parameter raises immediately.

        Values are stored as JSON. Pass `model` to get them back as the same
        type they were computed as:

        - a BaseModel subclass: payloads are validated into that model on read.
          Inferred from the return annotation when it is a single model type,
          so `async def f(...) -> User` needs no `model` argument.
        - "bytes": the result is stored and returned verbatim.
        - None (and no usable annotation): plain JSON, meaning a cache hit
          yields dicts and ISO strings where a miss yielded models and
          datetimes. Prefer annotating the function or passing `model`.

        Redis being unreachable degrades to a cache miss rather than raising,
        as does a payload that no longer matches `model` (after a deploy that
        changed its shape, say) - it is discarded and recomputed.

        The decorated function gains two helpers, both taking the same
        arguments as the function itself (including `self` for methods, even
        though it never contributes to the key):

        - `await f.invalidate(*args, **kwargs)` drops the entry for one call.
        - `f.cache_key(*args, **kwargs)` returns the full key it would use.
        """

        def decorator(func: F) -> F:
            build_key = _make_key_builder(func, key)
            resolved_model = model if model is not None else _infer_model(func)
            warn_lossy = _make_lossy_warner(func, resolved_model)

            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                subkey = build_key(args, kwargs)

                hit, value = await self._cache_read(ns, subkey, resolved_model)
                if hit:
                    if auto_extend:
                        await self._cache_extend(ns, subkey, ttl)
                    return value

                logger.trace(f"Cache miss for key: {ns}:{subkey}")
                result = await func(*args, **kwargs)
                warn_lossy(result)
                await self._cache_write(ns, subkey, result, resolved_model, ttl)
                return result

            async def invalidate(*args: Any, **kwargs: Any) -> None:
                """Drop the cache entry for one specific call."""
                await self._cache_drop(ns, build_key(args, kwargs))

            def cache_key(*args: Any, **kwargs: Any) -> str:
                """Return the full Redis key used for one specific call."""
                return f"{ns}:{build_key(args, kwargs)}"

            wrapper.invalidate = invalidate  # type: ignore[attr-defined]
            wrapper.cache_key = cache_key  # type: ignore[attr-defined]
            return cast("F", wrapper)

        return decorator


redis = Redis()
