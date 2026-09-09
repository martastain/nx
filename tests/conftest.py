import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

import nx
from nx.db import db
from nx.redis import redis

DEFAULT_POSTGRES_URL = "postgresql://nx:nx@127.0.0.1:55432/nx_test"
DEFAULT_REDIS_URL = "redis://127.0.0.1:56379/0"


async def _close_db_pool() -> None:
    pool = db._pool  # noqa: SLF001
    if pool is None:
        return
    await pool.close()
    db._pool = None  # noqa: SLF001


async def _close_redis_pool() -> None:
    pool = redis._pool  # noqa: SLF001
    if pool is None:
        redis.connected = False
        return
    await pool.aclose()
    redis._pool = None  # noqa: SLF001
    redis.connected = False


@pytest.fixture(autouse=True)
def _initialized_config() -> None:
    """nx.config is a process-wide singleton the logger reads on every call.

    Initializing it for every test keeps tests from depending on whichever
    earlier test happened to set it up.
    """
    nx.initialize(standalone=True)


@pytest.fixture
def integration_postgres_url() -> str:
    """Postgres to test against; NX_POSTGRES_URL wins, as the README promises."""
    return os.environ.get("NX_POSTGRES_URL", DEFAULT_POSTGRES_URL)


@pytest.fixture
def integration_redis_url() -> str:
    """Redis to test against; NX_REDIS_URL wins, as the README promises."""
    return os.environ.get("NX_REDIS_URL", DEFAULT_REDIS_URL)


@pytest_asyncio.fixture
async def nx_integration(
    monkeypatch: pytest.MonkeyPatch,
    integration_postgres_url: str,
    integration_redis_url: str,
) -> AsyncIterator[dict[str, str]]:
    await _close_db_pool()
    await _close_redis_pool()

    monkeypatch.setenv("NX_POSTGRES_URL", integration_postgres_url)
    monkeypatch.setenv("NX_REDIS_URL", integration_redis_url)

    nx.initialize(standalone=True)

    yield {
        "postgres_url": integration_postgres_url,
        "redis_url": integration_redis_url,
    }

    await _close_db_pool()
    await _close_redis_pool()


@pytest_asyncio.fixture
async def redis_ns(nx_integration: dict[str, str]) -> AsyncIterator[str]:
    """A namespace private to one test, deleted afterwards.

    Redis outlives a test run, so tests that share a fixed namespace leak state
    into each other and into the next run - a counter that keeps climbing, a
    stale key that breaks an unrelated iteration. A fresh namespace per test
    keeps the suite repeatable against a long-lived container.
    """
    _ = nx_integration
    namespace = f"nx-test-{uuid.uuid4().hex}"

    yield namespace

    async for key, _payload in redis.iterate(namespace):
        await redis.delete(namespace, key)
