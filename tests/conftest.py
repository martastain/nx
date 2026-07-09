from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

import nx
from nx.db import db
from nx.redis import redis

TEST_POSTGRES_URL = "postgresql://nx:nx@127.0.0.1:55432/nx_test"
TEST_REDIS_URL = "redis://127.0.0.1:56379/0"


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


@pytest.fixture
def integration_postgres_url() -> str:
    return TEST_POSTGRES_URL


@pytest.fixture
def integration_redis_url() -> str:
    return TEST_REDIS_URL


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
