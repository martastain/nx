import asyncio

import pytest
from pydantic import BaseModel

import nx

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("nx_integration"),
]


TEST_NAMESPACE = "nx-test"


async def test_redis_crud_and_expiry() -> None:
    await nx.redis.ping()

    await nx.redis.set(TEST_NAMESPACE, "plain", "value")
    assert await nx.redis.get(TEST_NAMESPACE, "plain") == b"value"

    await nx.redis.set_json(TEST_NAMESPACE, "json", {"ok": True})
    assert await nx.redis.get_json(TEST_NAMESPACE, "json") == {"ok": True}

    assert await nx.redis.incr(TEST_NAMESPACE, "count") == 1
    assert await nx.redis.incr(TEST_NAMESPACE, "count") == 2

    await nx.redis.expire(TEST_NAMESPACE, "plain", 1)
    await asyncio.sleep(1.1)
    assert await nx.redis.get(TEST_NAMESPACE, "plain") is None


async def test_redis_iterators_and_cached_decorator() -> None:
    class CachedPayload(BaseModel):
        value: int

    calls = 0

    @nx.redis.cached(
        ns=TEST_NAMESPACE,
        key="payload:{item_id}",
        ttl=30,
        model=CachedPayload,
    )
    async def load_payload(item_id: int) -> CachedPayload:
        nonlocal calls
        calls += 1
        return CachedPayload(value=item_id)

    await nx.redis.set_json(TEST_NAMESPACE, "one", {"value": 1})
    await nx.redis.set_json(TEST_NAMESPACE, "two", {"value": 2})

    items = {key: value async for key, value in nx.redis.iterate_json(TEST_NAMESPACE)}
    assert items["one"] == {"value": 1}
    assert items["two"] == {"value": 2}

    first = await load_payload(7)
    second = await load_payload(7)

    assert first == CachedPayload(value=7)
    assert second == CachedPayload(value=7)
    assert calls == 1


async def test_redis_pubsub() -> None:
    pubsub = await nx.redis.pubsub()
    await pubsub.subscribe(nx.redis.channel)

    try:
        await nx.redis.publish(f"message:{TEST_NAMESPACE}")

        message = None
        for _ in range(10):
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=0.5,
            )
            if message is not None:
                break

        assert message is not None
        assert message["data"] == f"message:{TEST_NAMESPACE}".encode()
    finally:
        await pubsub.unsubscribe(nx.redis.channel)
        await pubsub.aclose()
