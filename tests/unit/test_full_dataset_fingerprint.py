from copy import deepcopy
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.database import manage
from src.database.dataset_state import BUSINESS_QUERIES, full_dataset_fingerprint

ROWS = {
    "Products": [(1, "SYN-1", "Synthetic product", "operations", 123, 99)],
    "WorkItems": [(1, "Synthetic work item", "open", datetime(2025, 1, 1), 123)],
    "WorkItemLines": [(1, 1, 1, 123, 0)],
    "Activity": [(1, 1, "work_item_created", datetime(2025, 1, 1))],
    "IdempotencyKeys": [("synthetic-key", b"\x01" * 32, 1, datetime(2025, 1, 1))],
}


def fingerprint_rows(rows: dict) -> dict:
    connection = MagicMock()

    def execute(statement):
        query = str(statement)
        table = next(name for name, sql in BUSINESS_QUERIES.items() if sql == query)
        result = MagicMock()
        result.partitions.side_effect = lambda batch_size: iter([rows[table]])
        assert "ORDER BY" in query
        assert query.startswith("SELECT")
        return result

    connection.execute.side_effect = execute
    output = full_dataset_fingerprint(connection)
    assert connection.execute.call_count == len(BUSINESS_QUERIES)
    return output


def test_full_fingerprint_reproducible_and_includes_all_business_tables() -> None:
    first = fingerprint_rows(ROWS)
    assert first == fingerprint_rows(deepcopy(ROWS))
    assert len(first["full_dataset_fingerprint"]) == 64
    assert first["full_dataset_row_counts"] == dict.fromkeys(ROWS, 1)
    assert first["full_dataset_fingerprint_scope"] == "ordered_business_rows_v1"
    assert "synthetic-key" not in str(first)
    assert "Synthetic product" not in str(first)


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("Products", 2, "Changed synthetic name"),
        ("Products", 5, 98),
        ("WorkItems", 1, "Changed synthetic title"),
        ("WorkItems", 3, datetime(2025, 1, 2)),
        ("WorkItemLines", 2, 2),
        ("Activity", 3, datetime(2025, 1, 2)),
        ("IdempotencyKeys", 0, "synthetic-key-two"),
        ("IdempotencyKeys", 1, b"\x02" * 32),
    ],
)
def test_full_content_changes_detected_without_row_count_changes(
    table: str, column: int, value: object
) -> None:
    before = fingerprint_rows(ROWS)
    rows = deepcopy(ROWS)
    changed = list(rows[table][0])
    changed[column] = value
    rows[table][0] = tuple(changed)
    after = fingerprint_rows(rows)
    assert after["full_dataset_fingerprint"] != before["full_dataset_fingerprint"]
    assert after["full_dataset_row_counts"] == before["full_dataset_row_counts"]


def test_fingerprint_cli_uses_serializable_read_transaction_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.execution_options.return_value.__enter__.return_value
    monkeypatch.setattr(manage, "dataset_state", lambda value: {"dataset_state": {}})
    monkeypatch.setattr(
        manage,
        "full_dataset_fingerprint",
        lambda value: {"full_dataset_fingerprint": "0" * 64},
    )
    assert manage.fingerprint(engine)["status"] == "fingerprinted"
    engine.connect.return_value.execution_options.assert_called_once_with(
        isolation_level="SERIALIZABLE"
    )
    connection.begin.assert_called_once()
    connection.exec_driver_sql.assert_not_called()
