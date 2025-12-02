__all__ = ["db"]

import asyncio
import datetime as dt
import sys
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import asyncpg

from nx.config import config
from nx.logging import logger
from nx.utils import json_dumps, json_loads, normalize_uuid

if TYPE_CHECKING:
    from asyncpg.pool import PoolConnectionProxy
    from asyncpg.prepared_stmt import PreparedStatement

_current_connection: ContextVar["PoolConnectionProxy | None"] = ContextVar(  # type: ignore[type-arg]
    "_current_connection", default=None
)

_connection_lock = asyncio.Lock()


def timestamptz_encoder(v: Any) -> str:
    if isinstance(v, int | float):
        return dt.datetime.fromtimestamp(v, tz=dt.UTC).isoformat()
    if isinstance(v, dt.datetime):
        return v.isoformat()
    if isinstance(v, str):
        return dt.datetime.fromisoformat(v).isoformat()
    raise ValueError(f"Unsupported type for timestamptz_encoder: {type(v).__name__}")


def timestamptz_decoder(v: Any) -> dt.datetime:
    if isinstance(v, int | float):
        return dt.datetime.fromtimestamp(v, tz=dt.UTC)
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, str):
        return dt.datetime.fromisoformat(v)
    raise ValueError


class DB:
    _instance: "DB | None" = None
    _pool: asyncpg.pool.Pool | None = None  # type: ignore[type-arg]

    def __new__(cls, *args: Any, **kwargs: Any) -> "DB":
        _ = args, kwargs
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def _init_connection(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.set_type_codec(
            "jsonb",
            encoder=json_dumps,
            decoder=json_loads,
            schema="pg_catalog",
        )
        await conn.set_type_codec(
            "uuid",
            encoder=lambda x: normalize_uuid(x, allow_nulls=True),
            decoder=lambda x: normalize_uuid(x, allow_nulls=True),
            schema="pg_catalog",
        )
        await conn.set_type_codec(
            "timestamptz",
            encoder=timestamptz_encoder,
            decoder=timestamptz_decoder,
            schema="pg_catalog",
        )

    async def _connect(self) -> None:
        """Create a Postgres connection pool."""
        async with _connection_lock:
            if self._pool is not None:
                return  # Double check

            try:
                self._pool = await asyncpg.create_pool(
                    str(config.postgres_url),
                    init=self._init_connection,
                )
            except Exception as e:
                logger.error(f"Failed to connect to the database: {e}")
                logger.error(
                    f"Unrecoverable error while "
                    f"connecting to '{config.postgres_url}'. Exiting."
                )
                sys.exit(1)

    @asynccontextmanager
    async def acquire(
        self,
        *,
        timeout: int | None = None,  # noqa: ASYNC109
        force_new: bool = False,
    ) -> AsyncIterator["PoolConnectionProxy"]:  # type: ignore[type-arg]
        """Resolve the current connection from the contextvar or acquire a new one.
        If the connection is not available, create a new one.
        """
        conn = _current_connection.get()
        if not force_new and conn is not None:
            yield conn
            return

        if self._pool is None:
            await self._connect()
        assert self._pool is not None, "Database pool is not initialized"

        try:
            connection_proxy = await self._pool.acquire(timeout=timeout)
        except TimeoutError as e:
            raise ConnectionError("Database pool timeout") from e

        token = _current_connection.set(connection_proxy)

        try:
            yield connection_proxy
        finally:
            _current_connection.reset(token)
            await self._pool.release(connection_proxy)

    @asynccontextmanager
    async def transaction(
        self,
        timeout: int | None = None,  # noqa: ASYNC109
        force_new: bool = False,
    ) -> AsyncIterator["PoolConnectionProxy"]:  # type: ignore[type-arg]
        """Acquire a connection from the pool and manage transaction state."""
        async with self.acquire(timeout=timeout, force_new=force_new) as connection:
            if connection.is_in_transaction():
                yield connection
            else:
                async with connection.transaction():
                    yield connection

    @property
    def is_in_transaction(self) -> bool:
        """Check if the current connection is in a transaction."""
        conn = _current_connection.get()
        if conn is None:
            return False
        return conn.is_in_transaction()

    async def execute(self, query: str, *args: Any) -> str:
        """Exeuute a query and return the status."""
        async with self.acquire() as conn:
            return await conn.execute(query, *args)

    async def executemany(self, query: str, *args: Any) -> None:
        """Execute a query multiple times and return the result."""
        async with self.acquire() as conn:
            await conn.executemany(query, *args)

    async def prepare(self, query: str, *args: Any) -> "PreparedStatement":  # type: ignore[type-arg]
        """Fetch a query and return the result."""
        async with self.acquire() as conn:
            if not conn.is_in_transaction():
                raise RuntimeError("Transaction not started")
            return await conn.prepare(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        """Fetch a query and return the result."""
        async with self.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        """Fetch a query and return the first result."""
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def iterate(
        self,
        query: str,
        *args: Any,
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> AsyncGenerator[asyncpg.Record]:
        """Run a query and yield rows in batches using cursor.fetch()."""
        if self._pool is None:
            await self._connect()
        assert self._pool is not None, "Database pool is not initialized"

        conn = await self._pool.acquire(timeout=timeout)

        try:
            if not conn.is_in_transaction():
                async with conn.transaction():
                    statement = await conn.prepare(query)
                    async for record in statement.cursor(*args):
                        yield record
            else:
                statement = await conn.prepare(query)
                async for record in statement.cursor(*args):
                    yield record
        finally:
            await self._pool.release(conn)


db = DB()
