from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pyodbc
import pytest
from azure.core.credentials import AccessToken
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.pool import QueuePool

from src.configuration.settings import Settings
from src.database.connection import connection_creator
from src.database.models import WorkItemCreate, WorkItemLineInput
from src.database.repository import IdempotencyConflict, PageWindow, ProductFilter
from src.database.runtime import RuntimeRepository
from src.database.sql_repository import SqlRepository, command_hash
from src.telemetry.metrics import Registry


def sql_repository() -> tuple[SqlRepository, MagicMock]:
    settings = Settings(
        sql_server="sql.example.invalid", sql_database="synthetic", retry_base_delay_seconds=0
    )
    engine = MagicMock()
    return SqlRepository(settings, engine=engine, credential=MagicMock()), engine


def result(value=None, rows=()) -> MagicMock:
    query = MagicMock()
    query.scalar_one.return_value = value
    query.mappings.return_value.one_or_none.return_value = value
    query.mappings.return_value.one.return_value = value
    query.mappings.return_value.__iter__.return_value = iter(rows)
    return query


def test_metadata_reports_seed_counts_separately_from_current_dataset_state() -> None:
    repository, engine = sql_repository()
    connection = engine.connect.return_value
    connection.execute.side_effect = [
        result(
            {
                "schema_version": "0002",
                "dataset_version": "synthetic-v1-s42-p24-w100",
                "product_count": 24,
                "work_item_count": 100,
                "tuning_mode": "baseline",
                "dataset_kind": "synthetic-v1",
            }
        ),
        result({"products": 24, "work_items": 105, "stock_units": 2399999990}),
    ]
    metadata = repository.dataset_metadata()
    assert metadata["work_item_count"] == 100
    assert metadata["dataset_state"]["work_items"] == 105
    assert len(metadata["dataset_state_fingerprint"]) == 64
    assert metadata["dataset_fingerprint_scope"] == "aggregate_state_not_full_content"
    assert metadata["dataset_kind"] == "synthetic-v1"


def test_product_query_is_parameterized_and_escapes_like_metacharacters() -> None:
    repository, engine = sql_repository()
    connection = engine.connect.return_value
    connection.execute.side_effect = [
        result(24),
        result(
            rows=[
                {
                    "id": 1,
                    "sku": "SYN-1",
                    "name": "Synthetic",
                    "department": "operations",
                    "unit_price_cents": 1,
                    "stock_units": 10,
                }
            ]
        ),
    ]
    filters = ProductFilter(department="operations", q="'%_[")
    page = repository.list_products(filters, PageWindow(limit=2))
    assert page.items[0].id == 1
    statement, parameters = connection.execute.call_args.args
    sql = str(statement)
    assert filters.q not in sql
    assert parameters["q"] == "%'~%~_~[%"
    assert parameters["take"] == 3
    assert "id>:after_id" in sql
    assert "ORDER BY id" in sql


def test_physical_pool_limit_and_reconnect_requests_new_token() -> None:
    settings = Settings(sql_server="sql.example.invalid", sql_database="synthetic")
    credential = MagicMock()
    credential.get_token.side_effect = [
        AccessToken("synthetic-one", 9999999999),
        AccessToken("synthetic-two", 9999999999),
    ]
    connect = MagicMock(side_effect=[MagicMock(), MagicMock()])
    pool = QueuePool(
        connection_creator(settings, credential, connect), pool_size=1, max_overflow=0, timeout=0.02
    )
    first = pool.connect()
    with pytest.raises(PoolTimeout):
        pool.connect()
    first.invalidate()
    first.close()
    with_connection = pool.connect()
    assert credential.get_token.call_count == 2
    assert (
        connect.call_args_list[0].kwargs["attrs_before"]
        != connect.call_args_list[1].kwargs["attrs_before"]
    )
    with_connection.close()
    pool.dispose()


def test_ambiguous_commit_replays_durable_key_without_second_insert() -> None:
    repository, _ = sql_repository()
    command = WorkItemCreate(
        title="Synthetic ambiguous commit", lines=(WorkItemLineInput(product_id=1, quantity=2),)
    )
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    first = MagicMock()
    first.execute.side_effect = [
        result(0),
        result(None),
        result({"unit_price_cents": 500, "stock_units": 10}),
        result(),
        result({"id": 9, "created_at": timestamp}),
        result(),
        result(),
        result(),
    ]
    replay = MagicMock()
    replay.execute.side_effect = [
        result(0),
        result({"command_hash": command_hash(command), "work_item_id": 9}),
        result(
            {
                "id": 9,
                "title": command.title,
                "status": "open",
                "created_at": timestamp,
                "total_cents": 1000,
            }
        ),
        result(rows=[{"work_item_id": 9, "product_id": 1, "quantity": 2, "unit_price_cents": 500}]),
    ]
    attempts = 0

    @contextmanager
    def simulated_transaction(**kwargs):
        nonlocal attempts
        attempts += 1
        yield first if attempts == 1 else replay
        if attempts == 1:
            raise pyodbc.Error("08S01", "simulated lost acknowledgement (10054)")

    repository.connection = simulated_transaction
    runtime = RuntimeRepository(repository, repository.settings, Registry(repository.settings))
    created = runtime.create_work_item(command, "ambiguous-commit")
    assert created.replayed is True
    assert created.item.id == 9
    assert attempts == 2
    all_sql = [
        str(call.args[0])
        for connection in (first, replay)
        for call in connection.execute.call_args_list
    ]
    assert sum("INSERT dbo.WorkItems" in sql for sql in all_sql) == 1
    assert sum("UPDATE dbo.Products" in sql for sql in all_sql) == 1


def test_existing_sql_key_with_different_hash_is_conflict() -> None:
    repository, _ = sql_repository()
    connection = MagicMock()
    connection.execute.side_effect = [
        result(0),
        result({"command_hash": b"different", "work_item_id": 1}),
    ]

    @contextmanager
    def simulated_transaction(**kwargs):
        yield connection

    repository.connection = simulated_transaction
    command = WorkItemCreate(
        title="Synthetic conflicting request", lines=(WorkItemLineInput(product_id=1, quantity=1),)
    )
    with pytest.raises(IdempotencyConflict):
        repository.create_work_item(command, "conflict")
    assert connection.execute.call_count == 2
