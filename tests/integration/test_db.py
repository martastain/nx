import asyncio
import datetime as dt
import uuid

import pytest

import nx

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("nx_integration"),
]


async def test_db_round_trips_postgres_codecs() -> None:
    table_name = f"test_db_codecs_{uuid.uuid4().hex}"
    payload = {"message": "hello", "value": 42}
    event_id = uuid.uuid4()
    happened_at = dt.datetime.now(dt.UTC).replace(microsecond=0)

    await nx.db.execute(
        f"""
        CREATE TABLE {table_name} (
            id uuid PRIMARY KEY,
            payload jsonb NOT NULL,
            happened_at timestamptz NOT NULL
        )
        """
    )

    try:
        await nx.db.execute(
            f"""
            INSERT INTO {table_name} (id, payload, happened_at)
            VALUES ($1, $2, $3)
            """,
            event_id,
            payload,
            happened_at,
        )

        row = await nx.db.fetchrow(
            f"""
            SELECT id, payload, happened_at
            FROM {table_name}
            WHERE id = $1
            """,
            event_id,
        )
    finally:
        await nx.db.execute(f"DROP TABLE IF EXISTS {table_name}")

    assert row is not None
    assert row["id"] == event_id.hex
    assert row["payload"] == payload
    assert row["happened_at"] == happened_at


async def test_db_reuses_connection_inside_transaction() -> None:
    async with nx.db.transaction() as outer_connection:
        assert nx.db.is_in_transaction is True

        async with nx.db.acquire() as reused_connection:
            assert reused_connection is outer_connection

        async with nx.db.transaction() as nested_connection:
            assert nested_connection is outer_connection

        statement = await nx.db.prepare("SELECT $1::int + 1")
        result = await statement.fetchval(41)

    assert nx.db.is_in_transaction is False
    assert result == 42


async def test_db_iterate_streams_rows() -> None:
    table_name = f"test_db_iterate_{uuid.uuid4().hex}"

    await nx.db.execute(f"CREATE TABLE {table_name} (value integer NOT NULL)")

    try:
        await nx.db.executemany(
            f"INSERT INTO {table_name} (value) VALUES ($1)",
            [(1,), (2,), (3,)],
        )

        rows = [
            row
            async for row in nx.db.iterate(
                f"SELECT value FROM {table_name} ORDER BY value"
            )
        ]
    finally:
        await nx.db.execute(f"DROP TABLE IF EXISTS {table_name}")

    assert [row["value"] for row in rows] == [1, 2, 3]


async def test_on_commit_runs_hooks_after_the_outermost_commit() -> None:
    calls: list[str] = []

    async def hook(name: str) -> None:
        # Runs on the same connection, no longer in a transaction
        assert nx.db.is_in_transaction is False
        calls.append(name)

    async with nx.db.transaction():
        await nx.db.on_commit(lambda: hook("outer"))
        async with nx.db.transaction():
            await nx.db.on_commit(lambda: hook("nested"))
        assert calls == []

    assert calls == ["outer", "nested"]


async def test_on_commit_drops_hooks_on_rollback() -> None:
    calls: list[str] = []

    async def hook() -> None:
        calls.append("hook")

    async def failing_transaction() -> None:
        async with nx.db.transaction():
            await nx.db.on_commit(hook)
            raise RuntimeError("rollback")

    with pytest.raises(RuntimeError, match="rollback"):
        await failing_transaction()

    assert calls == []

    # The hooks of a rolled back transaction don't leak into the next one
    async with nx.db.transaction():
        pass
    assert calls == []


async def test_on_commit_runs_at_once_outside_a_transaction() -> None:
    calls: list[str] = []

    async def hook() -> None:
        calls.append("hook")

    await nx.db.on_commit(hook)
    assert calls == ["hook"]

    # Holding a connection is not a transaction
    async with nx.db.acquire():
        await nx.db.on_commit(hook)
        assert calls == ["hook", "hook"]


async def test_on_commit_failing_hook_does_not_stop_the_others() -> None:
    calls: list[str] = []

    async def failing() -> None:
        raise RuntimeError("hook failed")

    async def hook() -> None:
        calls.append("hook")

    async with nx.db.transaction():
        await nx.db.on_commit(failing)
        await nx.db.on_commit(hook)

    assert calls == ["hook"]


async def test_on_commit_hook_can_create_an_index_concurrently() -> None:
    table_name = f"test_db_hook_{uuid.uuid4().hex}"

    async def create_index() -> None:
        await nx.db.execute(
            f"CREATE INDEX CONCURRENTLY {table_name}_idx ON {table_name}(value)"
        )

    try:
        async with nx.db.transaction():
            await nx.db.execute(f"CREATE TABLE {table_name} (value integer)")
            await nx.db.on_commit(create_index)

        rows = await nx.db.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = $1", table_name
        )
    finally:
        await nx.db.execute(f"DROP TABLE IF EXISTS {table_name}")

    assert [row["indexname"] for row in rows] == [f"{table_name}_idx"]


async def test_advisory_xact_lock_blocks_until_the_holder_commits() -> None:
    key = f"test:{uuid.uuid4().hex}"
    order: list[str] = []
    holding = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with nx.db.transaction():
            await nx.db.advisory_xact_lock(key)
            holding.set()
            await release.wait()
            order.append("holder")

    async def waiter() -> None:
        await holding.wait()
        async with nx.db.transaction():
            await nx.db.advisory_xact_lock(key)
            order.append("waiter")

    tasks = [asyncio.create_task(holder()), asyncio.create_task(waiter())]
    await holding.wait()
    await asyncio.sleep(0.2)
    assert order == []  # the waiter is blocked
    release.set()
    await asyncio.gather(*tasks)

    assert order == ["holder", "waiter"]


async def test_advisory_xact_lock_shared_locks_do_not_block_each_other() -> None:
    key = f"test:{uuid.uuid4().hex}"

    async with nx.db.transaction():
        await nx.db.advisory_xact_lock(key, shared=True)
        async with nx.db.transaction(force_new=True):
            await asyncio.wait_for(
                nx.db.advisory_xact_lock(key, shared=True), timeout=2
            )


async def test_advisory_xact_lock_requires_a_transaction() -> None:
    with pytest.raises(RuntimeError, match="requires a transaction"):
        await nx.db.advisory_xact_lock("test:no-transaction")


async def test_db_iterate_sees_the_writes_of_its_transaction() -> None:
    table_name = f"test_db_iterate_tx_{uuid.uuid4().hex}"

    await nx.db.execute(f"CREATE TABLE {table_name} (value integer NOT NULL)")
    try:
        async with nx.db.transaction():
            await nx.db.execute(f"INSERT INTO {table_name} VALUES (1), (2)")
            values = []
            async for row in nx.db.iterate(f"SELECT value FROM {table_name}"):
                values.append(row["value"])
                # The connection stays usable while the cursor is open
                await nx.db.fetch("SELECT 1")
    finally:
        await nx.db.execute(f"DROP TABLE IF EXISTS {table_name}")

    assert sorted(values) == [1, 2]
