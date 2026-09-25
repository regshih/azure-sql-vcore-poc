import json
from unittest.mock import MagicMock

import pytest

from src.database import manage
from src.database.dataset_state import dataset_state
from src.database.seed import seed_database

VERSION = "synthetic-v1-s42-p24-w2"
STATE = {
    "products": 24,
    "stock_units": 2399999996,
    "work_items": 2,
    "last_work_item_id": 2,
    "work_item_total_cents": 1234,
    "work_item_lines": 2,
    "quantities": 4,
    "activity": 2,
    "last_activity_id": 2,
    "idempotency_keys": 0,
}


def seed_engine(*, marker: str | None = "synthetic-v1") -> MagicMock:
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value

    def execute(statement, parameters=None):
        sql = str(statement)
        result = MagicMock()
        result.scalar_one.return_value = 0
        if "WHERE [key]='dataset_kind'" in sql:
            result.scalar_one_or_none.return_value = marker
        elif "SELECT version,generation_seed" in sql:
            result.mappings.return_value.all.return_value = [
                {
                    "version": VERSION,
                    "generation_seed": 42,
                    "product_count": 24,
                    "work_item_count": 2,
                }
            ]
        elif sql == "SELECT version FROM dbo.DatasetVersions":
            result.scalars.return_value.all.return_value = [VERSION]
        elif "AS last_work_item_id" in sql:
            result.mappings.return_value.one.return_value = STATE
        return result

    connection.execute.side_effect = execute
    return engine


@pytest.mark.parametrize("allow,confirm", [(False, False), (True, False), (False, True)])
def test_reset_needs_both_flags_before_any_connection(allow: bool, confirm: bool) -> None:
    engine = MagicMock()
    with pytest.raises(ValueError, match="confirm-poc"):
        seed_database(engine, reset=True, allow_destructive_tests=allow, confirm_poc=confirm)
    engine.begin.assert_not_called()


@pytest.mark.parametrize("marker", [None, "customer-data"])
def test_reset_rejects_missing_or_foreign_safety_marker(marker: str | None) -> None:
    engine = seed_engine(marker=marker)
    with pytest.raises(ValueError, match="safety marker"):
        seed_database(engine, rows=2, reset=True, allow_destructive_tests=True, confirm_poc=True)
    connection = engine.begin.return_value.__enter__.return_value
    connection.exec_driver_sql.assert_not_called()


def test_reset_is_one_transaction_and_restores_identities_and_state() -> None:
    engine = seed_engine()
    result = seed_database(
        engine, rows=2, reset=True, allow_destructive_tests=True, confirm_poc=True
    )
    assert result["status"] == "reset_and_seeded"
    assert result["previous_dataset_version"] == VERSION
    assert result["dataset_version"] == VERSION
    assert result["destructive_reset"] is True
    assert result["dataset_state"] == STATE
    assert len(result["full_dataset_fingerprint"]) == 64
    assert result["full_dataset_fingerprint_scope"] == "ordered_business_rows_v1"
    engine.begin.assert_called_once()
    connection = engine.begin.return_value.__enter__.return_value
    statements = [call.args[0] for call in connection.exec_driver_sql.call_args_list]
    assert statements[:6] == [
        "DELETE FROM dbo.IdempotencyKeys WITH (TABLOCKX)",
        "DELETE FROM dbo.Activity WITH (TABLOCKX)",
        "DELETE FROM dbo.WorkItemLines WITH (TABLOCKX)",
        "DELETE FROM dbo.WorkItems WITH (TABLOCKX)",
        "DELETE FROM dbo.Products WITH (TABLOCKX)",
        "DELETE FROM dbo.DatasetVersions",
    ]
    assert "RESEED, 0" in statements[6] and "RESEED, 0" in statements[7]
    engine.begin.return_value.__exit__.assert_called_once_with(None, None, None)


def test_existing_seed_without_reset_does_not_delete_mutated_rows() -> None:
    engine = seed_engine()
    result = seed_database(engine, rows=2)
    assert result["status"] == "already_seeded"
    assert "full_dataset_fingerprint" not in result
    engine.begin.return_value.__enter__.return_value.exec_driver_sql.assert_not_called()


def test_reset_seed_failure_exits_transaction_for_rollback() -> None:
    engine = seed_engine()
    connection = engine.begin.return_value.__enter__.return_value
    original_execute = connection.execute.side_effect

    def fail_on_insertion(statement, parameters=None):
        if str(statement).startswith("INSERT dbo.Products"):
            raise RuntimeError("Synthetic insertion failure.")
        return original_execute(statement, parameters)

    connection.execute.side_effect = fail_on_insertion
    with pytest.raises(RuntimeError, match="Synthetic insertion"):
        seed_database(engine, rows=2, reset=True, allow_destructive_tests=True, confirm_poc=True)
    assert any(
        call.args[0].startswith("DELETE FROM") for call in connection.exec_driver_sql.call_args_list
    )
    assert engine.begin.return_value.__exit__.call_args.args[0] is RuntimeError


def test_fingerprint_changes_with_inventory_or_new_writes() -> None:
    connection = MagicMock()
    result = connection.execute.return_value.mappings.return_value.one
    result.return_value = STATE
    original = dataset_state(connection)
    result.return_value = dict(reversed(list(STATE.items())))
    assert (
        dataset_state(connection)["dataset_state_fingerprint"]
        == original["dataset_state_fingerprint"]
    )
    for key in ("stock_units", "work_items", "idempotency_keys"):
        result.return_value = {**STATE, key: STATE[key] + 1}
        assert (
            dataset_state(connection)["dataset_state_fingerprint"]
            != original["dataset_state_fingerprint"]
        )
    assert original["dataset_fingerprint_scope"] == "aggregate_state_not_full_content"


def test_cli_reset_missing_approval_fails_before_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["manage", "seed", "--reset"])
    credential = MagicMock()
    monkeypatch.setattr(manage, "credential_for", credential)
    assert manage.main() == 1
    credential.assert_not_called()
    assert json.loads(capsys.readouterr().out)["code"] == "invalid_administration_request"


def test_cli_reset_requires_poc_mode_before_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POC_MODE", "false")
    monkeypatch.setattr(
        "sys.argv",
        ["manage", "seed", "--reset", "--allow-destructive-tests", "--confirm-poc"],
    )
    credential = MagicMock()
    monkeypatch.setattr(manage, "credential_for", credential)
    assert manage.main() == 1
    credential.assert_not_called()
