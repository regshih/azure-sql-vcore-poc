import json
from unittest.mock import MagicMock
from uuid import UUID

import pyodbc
import pytest

from src.database import manage
from src.database.manage import grant_observer

ADMIN = UUID(int=1)
RUNTIME = UUID(int=2)
OBSERVER = UUID(int=3)


def observer_engine(
    *,
    administrator: bytes | None = ADMIN.bytes_le,
    runtime: bytes | None = RUNTIME.bytes_le,
    existing: dict | None = None,
    owner: int = 0,
    unexpected_permissions: int = 0,
) -> MagicMock:
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value

    def execute(statement):
        result = MagicMock()
        sql = str(statement)
        if sql == "SELECT SUSER_SID()":
            result.scalar_one_or_none.return_value = administrator
        elif "WHERE name='poc_runtime'" in sql:
            result.scalar_one_or_none.return_value = runtime
        elif "WHERE name='poc_observer'" in sql:
            result.mappings.return_value.one_or_none.return_value = existing
        elif "IS_ROLEMEMBER" in sql:
            result.scalar_one_or_none.return_value = owner
        else:
            assert "sys.database_role_members" in sql
            assert "sys.database_permissions" in sql
            assert "sys.schemas" in sql
            result.scalar_one.return_value = unexpected_permissions
        return result

    connection.execute.side_effect = execute
    return engine


@pytest.mark.parametrize("exists", [False, True])
def test_observer_only_gets_database_state_and_connect(exists: bool) -> None:
    engine = observer_engine(existing={"sid": OBSERVER.bytes_le, "type": "E"} if exists else None)
    grant_observer(engine, str(OBSERVER), str(RUNTIME))
    connection = engine.begin.return_value.__enter__.return_value
    statements = [call.args[0] for call in connection.exec_driver_sql.call_args_list]
    expected = ["GRANT CONNECT TO [poc_observer]", "GRANT VIEW DATABASE STATE TO [poc_observer]"]
    if not exists:
        expected.insert(
            0, f"CREATE USER [poc_observer] WITH SID=0x{OBSERVER.bytes_le.hex()}, TYPE=E;"
        )
    assert statements == expected
    assert not any(
        token in " ".join(statements)
        for token in ("EXTERNAL PROVIDER", "SERVER STATE", "SELECT", "INSERT", "ALTER ROLE")
    )
    engine.begin.return_value.__exit__.assert_called_once_with(None, None, None)


def test_observer_runtime_collision_fails_before_database_access() -> None:
    engine = MagicMock()
    with pytest.raises(ValueError, match="different"):
        grant_observer(engine, str(RUNTIME), str(RUNTIME))
    engine.begin.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [
        {"administrator": OBSERVER.bytes_le},
        {"administrator": None},
        {"runtime": None},
        {"runtime": ADMIN.bytes_le},
        {"existing": {"sid": ADMIN.bytes_le, "type": "E"}},
        {"existing": {"sid": OBSERVER.bytes_le, "type": "S"}},
        {"existing": {"sid": OBSERVER.bytes_le, "type": "E"}, "owner": 1},
        {
            "existing": {"sid": OBSERVER.bytes_le, "type": "E"},
            "unexpected_permissions": 1,
        },
    ],
)
def test_observer_fails_closed_without_changing_principals(options: dict) -> None:
    engine = observer_engine(**options)
    with pytest.raises(ValueError):
        grant_observer(engine, str(OBSERVER), str(RUNTIME))
    connection = engine.begin.return_value.__enter__.return_value
    connection.exec_driver_sql.assert_not_called()


def test_unsupported_database_permission_is_not_ignored() -> None:
    engine = observer_engine()
    connection = engine.begin.return_value.__enter__.return_value
    connection.exec_driver_sql.side_effect = [
        None,
        None,
        pyodbc.Error("42000", "Synthetic unsupported permission (297)"),
    ]
    with pytest.raises(pyodbc.Error):
        grant_observer(engine, str(OBSERVER), str(RUNTIME))
    assert engine.begin.return_value.__exit__.call_args.args[0] is pyodbc.Error


def mock_bootstrap(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, list[str]]:
    credential = MagicMock()
    engine = MagicMock()
    order: list[str] = []
    monkeypatch.setenv("RUNTIME_OBJECT_ID", str(RUNTIME))
    monkeypatch.setattr(manage, "credential_for", lambda settings: credential)
    monkeypatch.setattr(manage, "connection_creator", lambda *args: MagicMock())
    monkeypatch.setattr(manage, "make_engine", lambda *args: engine)
    monkeypatch.setattr(manage, "migrate", lambda database: order.append("migrate") or ["0001"])
    monkeypatch.setattr(manage, "grant_runtime", lambda *args: order.append("runtime"))
    monkeypatch.setattr(
        manage,
        "seed_database",
        lambda *args, **kwargs: order.append("seed") or {"status": "seeded"},
    )
    return engine, order


@pytest.mark.parametrize("explicit", [False, True])
def test_bootstrap_observer_env_fallback_and_explicit_override(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], explicit: bool
) -> None:
    engine, order = mock_bootstrap(monkeypatch)
    monkeypatch.setenv("OBSERVER_OBJECT_ID", str(ADMIN) if explicit else str(OBSERVER))
    arguments = ["manage", "bootstrap"]
    if explicit:
        arguments.extend(["--observer-object-id", str(OBSERVER)])
    monkeypatch.setattr("sys.argv", arguments)

    def grant(database, observer_id, runtime_id):
        assert database is engine
        assert observer_id == str(OBSERVER)
        assert runtime_id == str(RUNTIME)
        order.append("observer")

    monkeypatch.setattr(manage, "grant_observer", grant)
    assert manage.main() == 0
    assert order == ["migrate", "runtime", "observer", "seed"]
    output = capsys.readouterr().out
    assert json.loads(output)["observer_configured"] is True
    assert all(str(identifier) not in output for identifier in (ADMIN, RUNTIME, OBSERVER))


@pytest.mark.parametrize("value", ["INVALID_OBSERVER_PRIVATE_VALUE", str(RUNTIME)])
def test_bootstrap_invalid_or_colliding_observer_fails_before_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    monkeypatch.setenv("RUNTIME_OBJECT_ID", str(RUNTIME))
    monkeypatch.setenv("OBSERVER_OBJECT_ID", value)
    monkeypatch.setattr("sys.argv", ["manage", "bootstrap"])
    credential = MagicMock()
    monkeypatch.setattr(manage, "credential_for", credential)
    assert manage.main() == 1
    credential.assert_not_called()
    output = capsys.readouterr().out
    assert value not in output
    assert json.loads(output)["code"] == "invalid_administration_request"


def test_bootstrap_observer_permission_error_is_sanitized_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, order = mock_bootstrap(monkeypatch)
    monkeypatch.setenv("OBSERVER_OBJECT_ID", str(OBSERVER))
    monkeypatch.setattr("sys.argv", ["manage", "bootstrap"])
    monkeypatch.setattr(
        manage,
        "grant_observer",
        MagicMock(side_effect=pyodbc.Error("42000", "PRIVATE_RAW_ERROR permission denied (297)")),
    )
    assert manage.main() == 1
    assert "seed" not in order
    output = capsys.readouterr().out
    assert "PRIVATE_RAW_ERROR" not in output
    payload = json.loads(output)
    assert payload["status"] == "failed"
    assert payload["category"] == "database_nontransient_error"
    assert payload["code"] == "42000"
