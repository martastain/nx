__all__ = ["db"]

import asyncio
import datetime as dt
import sys
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Self, cast

import asyncpg

from nx.config import config
from nx.logging import logger
from nx.utils import json_dumps, json_loads, normalize_uuid

if TYPE_CHECKING:
    from asyncpg.pool import PoolConnectionProxy
    from asyncpg.prepared_stmt import PreparedStatement

_current_connection: ContextVar["PoolConnectionProxy | None"] = ContextVar(
    "_current_connection", default=None
)

CommitHook = Callable[[], Awaitable[Any]]

# Hooks of the current (outermost) transaction, run after it commits
_commit_hooks: ContextVar[list[CommitHook] | None] = ContextVar(
    "_commit_hooks", default=None
)

_connection_lock = asyncio.Lock()


async def _run_commit_hooks(hooks: list[CommitHook]) -> None:
    # The data is already committed: one failing hook must not skip the others
    # or turn a finished transaction into an error
    for hook in hooks:
        try:
            await hook()
        except Exception:
            logger.traceback("Post-commit hook failed")


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
    _pool: asyncpg.pool.Pool | None = None

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        _ = args, kwargs
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cast("Self", cls._instance)

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
    ) -> AsyncIterator["PoolConnectionProxy"]:
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
        *,
        timeout: int | None = None,  # noqa: ASYNC109
        force_new: bool = False,
    ) -> AsyncIterator["PoolConnectionProxy"]:
        """Acquire a connection from the pool and manage transaction state.

        Inside a transaction, a nested block joins it: nothing is committed
        until the outermost block ends.
        """
        async with self.acquire(timeout=timeout, force_new=force_new) as connection:
            if connection.is_in_transaction():
                yield connection
                return

            hooks: list[CommitHook] = []
            token = _commit_hooks.set(hooks)
            try:
                async with connection.transaction():
                    yield connection
            finally:
                _commit_hooks.reset(token)
            # Only reached when the transaction committed. The connection is
            # still the current one and no longer in a transaction, so hooks
            # can run statements that refuse a transaction block
            # (CREATE INDEX CONCURRENTLY, VACUUM).
            await _run_commit_hooks(hooks)

    async def on_commit(self, hook: CommitHook) -> None:
        """Run `hook` after the current transaction commits (now if there is none).

        Hooks can be added anywhere inside the transaction, also in nested
        `transaction()` blocks, which join the outer one. They run in the
        order they were added, after the outermost transaction commits, and
        are dropped on rollback. An exception in a hook is logged and doesn't
        stop the others: the data is committed by then.
        """
        hooks = _commit_hooks.get()
        if hooks is not None and self.is_in_transaction:
            hooks.append(hook)
        else:
            await hook()

    async def advisory_xact_lock(self, key: str, *, shared: bool = False) -> None:
        """Wait for an advisory lock on `key`, held until the transaction ends.

        Keys are hashed strings, so all callers share one key space: use a
        "<domain>:<id>" prefix to avoid clashes. Shared locks only block,
        and are blocked by, exclusive ones.
        """
        fn = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
        async with self.acquire() as conn:
            # Outside a transaction the lock would be released immediately
            if not conn.is_in_transaction():
                raise RuntimeError("Advisory xact lock requires a transaction")
            await conn.execute(f"SELECT {fn}(hashtextextended($1, 0))", key)

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

    async def prepare(self, query: str, *args: Any) -> "PreparedStatement":
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
        """Run a query and yield its rows, read with a cursor.

        Inside a transaction the query runs in it, so it sees the
        transaction's own writes and locks. Otherwise it gets a connection
        of its own, which `timeout` (seconds) waits for.
        """
        # No context manager and no ContextVar.set() here: a generator may
        # be resumed in, or abandoned by, a different context

        current = _current_connection.get()
        if current is not None and current.is_in_transaction():
            # Only then: a cursor opened outside a transaction would need its
            # own, left open on the shared connection if the caller stops early
            statement = await current.prepare(query)
            async for record in statement.cursor(*args):
                yield record
            return

        if self._pool is None:
            await self._connect()
        assert self._pool is not None, "Database pool is not initialized"

        conn = await self._pool.acquire(timeout=timeout)
        try:
            async with conn.transaction():
                statement = await conn.prepare(query)
                async for record in statement.cursor(*args):
                    yield record
        finally:
            await self._pool.release(conn)


db = DB()
