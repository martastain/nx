import asyncio
import datetime as dt
from typing import Any

import pytest
from pydantic import BaseModel

import nx
from nx.redis import redis

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("nx_integration"),
]


class Payload(BaseModel):
    value: int
    label: str = "default"


async def _ttl(namespace: str, key: str) -> int:
    """Remaining TTL in seconds (-1 when the key never expires)."""
    pool = redis._pool  # noqa: SLF001
    assert pool is not None
    return int(await pool.ttl(f"{namespace}:{key}"))


#
# Plain key/value operations
#


async def test_redis_crud_and_expiry(redis_ns: str) -> None:
    await nx.redis.ping()

    await nx.redis.set(redis_ns, "plain", "value")
    assert await nx.redis.get(redis_ns, "plain") == b"value"

    await nx.redis.set_json(redis_ns, "json", {"ok": True})
    assert await nx.redis.get_json(redis_ns, "json") == {"ok": True}

    assert await nx.redis.incr(redis_ns, "count") == 1
    assert await nx.redis.incr(redis_ns, "count") == 2

    await nx.redis.delete(redis_ns, "json")
    assert await nx.redis.get(redis_ns, "json") is None

    await nx.redis.expire(redis_ns, "plain", 1)
    await asyncio.sleep(1.1)
    assert await nx.redis.get(redis_ns, "plain") is None


async def test_get_json_rejects_non_json_payloads(redis_ns: str) -> None:
    await nx.redis.set(redis_ns, "plain", "value")

    with pytest.raises(ValueError, match="Invalid JSON"):
        await nx.redis.get_json(redis_ns, "plain")


async def test_set_honours_ttl(redis_ns: str) -> None:
    await nx.redis.set(redis_ns, "temporary", "value", ttl=30)
    await nx.redis.set(redis_ns, "permanent", "value")

    assert 0 < await _ttl(redis_ns, "temporary") <= 30
    assert await _ttl(redis_ns, "permanent") == -1


async def test_iterators_strip_the_namespace(redis_ns: str) -> None:
    await nx.redis.set_json(redis_ns, "one", {"value": 1})
    await nx.redis.set_json(redis_ns, "two", {"value": 2})

    items = {key: value async for key, value in nx.redis.iterate_json(redis_ns)}

    assert items == {"one": {"value": 1}, "two": {"value": 2}}


async def test_pubsub(redis_ns: str) -> None:
    pubsub = await nx.redis.pubsub()
    await pubsub.subscribe(nx.redis.channel)

    try:
        await nx.redis.publish(f"message:{redis_ns}")

        message = None
        for _ in range(10):
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=0.5,
            )
            if message is not None:
                break

        assert message is not None
        assert message["data"] == f"message:{redis_ns}".encode()
    finally:
        await pubsub.unsubscribe(nx.redis.channel)
        await pubsub.aclose()


#
# cached(): basic behaviour
#


async def test_cached_serves_the_second_call_from_redis(redis_ns: str) -> None:
    calls = 0

    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30, model=Payload)
    async def load(item_id: int) -> Payload:
        nonlocal calls
        calls += 1
        return Payload(value=item_id)

    first = await load(7)
    second = await load(7)

    assert first == second == Payload(value=7)
    assert calls == 1


async def test_cached_separates_distinct_arguments(redis_ns: str) -> None:
    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload:
        return Payload(value=item_id)

    assert await load(1) == Payload(value=1)
    assert await load(2) == Payload(value=2)
    assert await load(1) == Payload(value=1)


async def test_cached_writes_the_documented_key(redis_ns: str) -> None:
    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload:
        return Payload(value=item_id)

    await load(3)

    assert load.cache_key(3) == f"{redis_ns}:payload:3"
    assert await nx.redis.get(redis_ns, "payload:3") is not None


async def test_cached_applies_the_ttl(redis_ns: str) -> None:
    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=45)
    async def load(item_id: int) -> Payload:
        return Payload(value=item_id)

    await load(1)

    assert 0 < await _ttl(redis_ns, "payload:1") <= 45


async def test_cached_caches_none(redis_ns: str) -> None:
    """A None result is a real answer and must not be recomputed every time."""
    calls = 0

    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload | None:
        nonlocal calls
        calls += 1
        return None

    assert await load(1) is None
    assert await load(1) is None
    assert calls == 1


async def test_cached_methods_share_one_entry(redis_ns: str) -> None:
    """`self` is excluded from the key, so instances share cached results."""

    class Repo:
        def __init__(self) -> None:
            self.calls = 0

        @nx.redis.cached(ns=redis_ns, key="item:{item_id}", ttl=30)
        async def load(self, item_id: int) -> Payload:
            self.calls += 1
            return Payload(value=item_id)

    first, second = Repo(), Repo()

    assert await first.load(1) == Payload(value=1)
    assert await second.load(1) == Payload(value=1)
    assert (first.calls, second.calls) == (1, 0)


#
# cached(): a hit must be indistinguishable from a miss
#


async def test_cached_hit_matches_miss_for_an_annotated_model(redis_ns: str) -> None:
    """No model= is passed; the return annotation supplies it."""

    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload:
        return Payload(value=item_id)

    miss = await load(1)
    hit = await load(1)

    assert type(miss) is type(hit) is Payload
    assert miss == hit


async def test_cached_hit_matches_miss_for_an_optional_model(redis_ns: str) -> None:
    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload | None:
        return Payload(value=item_id)

    miss = await load(1)
    hit = await load(1)

    assert type(miss) is type(hit) is Payload
    assert miss == hit


async def test_cached_preserves_datetimes(redis_ns: str) -> None:
    """Plain JSON turns a datetime into a string; a model must not."""

    class Event(BaseModel):
        at: dt.datetime

    moment = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC)

    @nx.redis.cached(ns=redis_ns, key="event:{event_id}", ttl=30)
    async def load(event_id: int) -> Event:
        return Event(at=moment)

    miss = await load(1)
    hit = await load(1)

    assert miss.at == hit.at == moment
    assert isinstance(hit.at, dt.datetime)


async def test_cached_preserves_fields_left_at_their_default(redis_ns: str) -> None:
    """set_json() drops defaults; the cache must store the whole model."""

    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload:
        return Payload(value=item_id, label="default")

    await load(1)
    raw = await nx.redis.get(redis_ns, "payload:1")

    assert b'"label"' in raw
    assert (await load(1)).label == "default"


async def test_cached_bytes_mode_round_trips(redis_ns: str) -> None:
    calls = 0

    @nx.redis.cached(ns=redis_ns, key="blob:{blob_id}", ttl=30, model="bytes")
    async def load(blob_id: int) -> bytes:
        nonlocal calls
        calls += 1
        return b"\x89PNG\r\n\x1a\n"

    assert await load(1) == b"\x89PNG\r\n\x1a\n"
    assert await load(1) == b"\x89PNG\r\n\x1a\n"
    assert calls == 1


#
# cached(): recovery
#


async def test_cached_replaces_a_payload_from_an_older_model(redis_ns: str) -> None:
    """The rolling-deploy case: cached JSON predates a field being added."""

    class User(BaseModel):
        name: str
        email: str  # added in a later release

    calls = 0

    @nx.redis.cached(ns=redis_ns, key="user:{user_id}", ttl=30)
    async def load(user_id: int) -> User:
        nonlocal calls
        calls += 1
        return User(name="ada", email="ada@example.com")

    # what the previous release left behind
    await nx.redis.set_json(redis_ns, "user:1", {"name": "ada"}, ttl=30)

    assert await load(1) == User(name="ada", email="ada@example.com")
    assert calls == 1

    # the stale entry was overwritten, so this one is served from cache
    assert await load(1) == User(name="ada", email="ada@example.com")
    assert calls == 1


async def test_cached_replaces_a_corrupt_payload(redis_ns: str) -> None:
    calls = 0

    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload:
        nonlocal calls
        calls += 1
        return Payload(value=item_id)

    await nx.redis.set(redis_ns, "payload:1", "}{ not json", ttl=30)

    assert await load(1) == Payload(value=1)
    assert calls == 1
    assert await load(1) == Payload(value=1)
    assert calls == 1


#
# cached(): invalidation and TTL management
#


async def test_invalidate_forces_a_recompute(redis_ns: str) -> None:
    calls = 0

    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload:
        nonlocal calls
        calls += 1
        return Payload(value=item_id)

    await load(1)
    await load(1)
    assert calls == 1

    await load.invalidate(1)

    await load(1)
    assert calls == 2


async def test_invalidate_only_drops_the_matching_entry(redis_ns: str) -> None:
    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload:
        return Payload(value=item_id)

    await load(1)
    await load(2)

    await load.invalidate(1)

    assert await nx.redis.get(redis_ns, "payload:1") is None
    assert await nx.redis.get(redis_ns, "payload:2") is not None


async def test_auto_extend_refreshes_the_ttl_on_a_hit(redis_ns: str) -> None:
    @nx.redis.cached(
        ns=redis_ns, key="payload:{item_id}", ttl=60, auto_extend=True, model=Payload
    )
    async def load(item_id: int) -> Payload:
        return Payload(value=item_id)

    await load(1)
    await nx.redis.expire(redis_ns, "payload:1", 5)
    assert await _ttl(redis_ns, "payload:1") <= 5

    await load(1)

    assert await _ttl(redis_ns, "payload:1") > 5


async def test_ttl_is_not_refreshed_without_auto_extend(redis_ns: str) -> None:
    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=60, model=Payload)
    async def load(item_id: int) -> Payload:
        return Payload(value=item_id)

    await load(1)
    await nx.redis.expire(redis_ns, "payload:1", 5)

    await load(1)

    assert await _ttl(redis_ns, "payload:1") <= 5


async def test_cached_entries_are_namespaced(redis_ns: str) -> None:
    """Everything the decorator writes must live under its namespace."""

    @nx.redis.cached(ns=redis_ns, key="payload:{item_id}", ttl=30)
    async def load(item_id: int) -> Payload:
        return Payload(value=item_id)

    await load(1)
    await load(2)

    keys = {key async for key, _ in nx.redis.iterate(redis_ns)}

    assert keys == {"payload:1", "payload:2"}


async def test_unstable_key_arguments_are_not_silently_cached(
    redis_ns: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An argument with no __repr__ makes keys unrepeatable - warn, don't hide it."""

    class Opaque:
        pass

    @nx.redis.cached(ns=redis_ns, key="thing:{thing}", ttl=30)
    async def load(thing: Any) -> Payload:
        return Payload(value=1)

    # Held in locals: once freed, CPython happily reuses the address, and two
    # unrelated objects would then collide on one key.
    first, second = Opaque(), Opaque()

    await load(first)
    await load(second)

    assert "has no __str__/__repr__" in capsys.readouterr().err
    assert len([key async for key, _ in nx.redis.iterate(redis_ns)]) == 2
