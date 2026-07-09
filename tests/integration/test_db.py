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
