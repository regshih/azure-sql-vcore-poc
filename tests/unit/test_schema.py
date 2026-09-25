import hashlib
import json
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text

from src.database import manage
from src.database.manage import grant_runtime, runtime_user_sql, tune
from src.database.migrations import batches, discover, migrate
from src.database.seed import products, work_items


def test_migration_order_and_checksums() -> None:
    migrations = discover()
    assert [migration.version for migration in migrations] == ["0001", "0002"]
    for migration in migrations:
        assert migration.checksum == hashlib.sha256(migration.sql.encode()).hexdigest()
    assert batches("SELECT 1;\nGO\nSELECT 2;\nGO -- boundary") == ("SELECT 1;", "SELECT 2;")


def test_sid_uses_sql_uniqueidentifier_byte_order_without_graph() -> None:
    identifier = UUID(int=42)
    sql = runtime_user_sql(str(identifier))
    assert identifier.bytes_le.hex() in sql
    assert "TYPE=E" in sql
    assert "EXTERNAL PROVIDER" not in sql
    with pytest.raises(ValueError):
        runtime_user_sql("not-a-guid; DROP")


def test_seed_reproducible_skew_and_no_personal_fields() -> None:
    assert products(30, 42) == products(30, 42)
    items = list(work_items(1000, 100, 42))
    assert items == list(work_items(1000, 100, 42))
    assert sum(item["product_id"] <= 5 for item in items) > 750
    assert all(item["title"].startswith("Synthetic") for item in items)
    assert items != list(work_items(1000, 100, 43))


def test_tuning_baseline_requires_explicit_permission() -> None:
    engine = MagicMock()
    with pytest.raises(ValueError, match="allow-unsafe"):
        tune(engine, "baseline")
    engine.begin.assert_not_called()
    assert tune(engine, "both") == {"status": "tuned", "mode": "both"}
    sql = engine.begin.return_value.__enter__.return_value.exec_driver_sql.call_args.args[0]
    assert "IX_Products_Tuning_Cover" in sql
    assert "CREATE INDEX" in sql


def test_migration_checksum_drift_is_rejected() -> None:
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    result = MagicMock()
    result.scalar_one.return_value = 0
    result.tuples.return_value = [("0001", "invalid-checksum")]
    connection.execute.return_value = result
    with pytest.raises(ValueError, match="checksum"):
        migrate(engine)
    connection.exec_driver_sql.assert_not_called()


@pytest.mark.parametrize("applied_count", [0, 1, 2])
def test_migration_ledger_consumes_real_sqlalchemy_rows(applied_count: int) -> None:
    migrations = discover()
    database = create_engine("sqlite://")
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    result = MagicMock()
    result.scalar_one.return_value = 0
    try:
        with database.connect() as cursor_connection:
            cursor_connection.execute(text("CREATE TABLE ledger (version TEXT, checksum TEXT)"))
            for migration in migrations[:applied_count]:
                cursor_connection.execute(
                    text("INSERT INTO ledger VALUES (:version, :checksum)"),
                    {"version": migration.version, "checksum": migration.checksum},
                )

            def execute(statement, parameters=None):
                if str(statement) == "SELECT version,checksum FROM dbo.SchemaMigrations":
                    return cursor_connection.execute(text("SELECT version,checksum FROM ledger"))
                return result

            connection.execute.side_effect = execute
            assert migrate(engine) == [
                migration.version for migration in migrations[applied_count:]
            ]
    finally:
        database.dispose()


def test_runtime_grants_are_object_scoped_and_separate_from_admin() -> None:
    runtime_id = UUID(int=42)
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    result = MagicMock()
    result.scalar_one_or_none.side_effect = [UUID(int=43).bytes_le, None, 0]
    connection.execute.return_value = result
    grant_runtime(engine, str(runtime_id))
    statements = [call.args[0] for call in connection.exec_driver_sql.call_args_list]
    assert any("CREATE USER [poc_runtime] WITH SID=0x" in sql for sql in statements)
    assert any("UPDATE (stock_units)" in sql for sql in statements)
    assert not any("db_owner ADD" in sql or "GRANT CONTROL" in sql for sql in statements)
    result.scalar_one_or_none.side_effect = [runtime_id.bytes_le]
    with pytest.raises(ValueError, match="different"):
        grant_runtime(engine, str(runtime_id))


def test_bootstrap_environment_fallback_and_operation_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime_id = UUID(int=42)
    monkeypatch.delenv("OBSERVER_CLIENT_ID", raising=False)
    monkeypatch.setenv("RUNTIME_CLIENT_ID", str(runtime_id))
    monkeypatch.setattr("sys.argv", ["manage", "bootstrap"])
    credential, engine = MagicMock(), MagicMock()
    monkeypatch.setattr(manage, "credential_for", lambda settings: credential)
    monkeypatch.setattr(manage, "connection_creator", lambda *args: MagicMock())
    monkeypatch.setattr(manage, "make_engine", lambda *args: engine)
    order = []

    def migrate(database):
        assert database is engine
        order.append("migrate")
        return ["0001", "0002"]

    def grant(database, identifier):
        assert database is engine
        assert identifier == str(runtime_id)
        order.append("grant")

    def seed(database, **kwargs):
        assert database is engine
        assert kwargs == {"size": "small", "seed": 42, "rows": None}
        order.append("seed")
        return {"status": "seeded"}

    monkeypatch.setattr(manage, "migrate", migrate)
    monkeypatch.setattr(manage, "grant_runtime", grant)
    monkeypatch.setattr(manage, "seed_database", seed)
    assert manage.main() == 0
    assert order == ["migrate", "grant", "seed"]
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "bootstrapped"
    assert json.loads(output)["observer_configured"] is False
    assert str(runtime_id) not in output
    engine.dispose.assert_called_once()
    credential.close.assert_called_once()


def test_bootstrap_invalid_environment_id_fails_before_connecting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RUNTIME_CLIENT_ID", "DO_NOT_ECHO_INVALID_VALUE")
    monkeypatch.setattr("sys.argv", ["manage", "bootstrap"])
    credential_factory = MagicMock()
    monkeypatch.setattr(manage, "credential_for", credential_factory)
    assert manage.main() == 1
    credential_factory.assert_not_called()
    output = capsys.readouterr().out
    assert "DO_NOT_ECHO_INVALID_VALUE" not in output
    assert json.loads(output)["code"] == "invalid_administration_request"
