import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from src.experiments import sql_evidence
from src.experiments.common import NOT_DEMONSTRATED
from src.experiments.sanitize import sanitize_document

START = "2026-09-25T06:00:00Z"
END = "2026-09-25T06:01:00Z"
CONFIG = {"sql_server": "example", "database": "synthetic"}


@pytest.mark.parametrize("state", ["Paused", "Pausing", "Resuming", None])
def test_nononline_database_never_connects_or_resumes(state, monkeypatch):
    monkeypatch.setattr(sql_evidence, "sql_configuration", lambda _config: {"status": state})
    credential = MagicMock()
    monkeypatch.setattr(sql_evidence, "credential_for", credential)
    diagnostics, query_store = sql_evidence.collect_sql(CONFIG, START, END)
    assert diagnostics["status"] == NOT_DEMONSTRATED
    assert query_store["rows"] is None
    credential.assert_not_called()


def test_windowed_query_store_assets_use_bound_utc_and_no_text():
    for asset in ("top-queries", "waits"):
        query = sql_evidence.windowed_query(asset)
        assert "DECLARE @" not in query
        assert ":start_utc" in query and ":end_utc" in query
        assert "query_sql_text" not in query
        assert "SUM(" in query
    with pytest.raises(ValueError):
        sql_evidence.windowed_query("query-text-opt-in")


def test_rows_preserve_missing_zero_units_and_utc():
    connection = MagicMock()
    connection.execute.return_value.mappings.return_value.fetchmany.return_value = [
        {"average_ms": Decimal("0"), "missing": None, "sampled_utc": datetime(2026, 1, 1)}
    ]
    result = sql_evidence.read_rows(connection, "SELECT 0", {"start_utc": START})
    assert result["rows"][0]["average_ms"] == 0
    assert result["rows"][0]["missing"] is None
    assert result["rows"][0]["sampled_utc"].endswith("+00:00")
    connection.rollback.assert_called_once()


def test_permission_error_retains_unknown_and_never_copies_sql_or_message():
    connection = MagicMock()
    connection.execute.side_effect = OperationalError(
        "sensitive query", {}, Exception("private server and identity")
    )
    result = sql_evidence.read_rows(connection, "SELECT 0", {})
    assert result["status"] == NOT_DEMONSTRATED
    assert result["rows"] is None
    assert result["failure_category"] == "OperationalError"
    assert "sensitive" not in json.dumps(result)
    assert "private server" not in json.dumps(result)
    connection.rollback.assert_called_once()


def test_actual_collector_queries_catalog_dataset_and_store_then_disposes(monkeypatch):
    monkeypatch.setattr(sql_evidence, "sql_configuration", lambda _config: {"status": "Online"})
    monkeypatch.setattr(sql_evidence, "credential_for", MagicMock())
    monkeypatch.setattr(sql_evidence, "connection_creator", MagicMock())
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.fetchmany.return_value = []
    factory = MagicMock(return_value=engine)
    monkeypatch.setattr(sql_evidence, "make_engine", factory)
    monkeypatch.setattr(
        sql_evidence, "dataset_state", lambda _connection: {"dataset_state": {"products": 3}}
    )
    diagnostics, query_store = sql_evidence.collect_sql(CONFIG, START, END)
    assert diagnostics["schema"]["status"] == "measured"
    assert diagnostics["dataset"]["dataset_state"]["products"] == 3
    assert query_store["top_queries"]["rows"] == []
    assert query_store["top_queries"]["empty_rows_do_not_prove_zero_activity"]
    assert query_store["interval_overlap_may_include_out_of_window_executions"]
    factory.assert_called_once()
    assert factory.call_args.kwargs["pooled"] is False
    engine.dispose.assert_called_once()
    assert len(connection.execute.call_args_list) == 7
    for call in connection.execute.call_args_list:
        assert (
            call.args[1]["start_utc"] == datetime.fromisoformat(START).astimezone(UTC).isoformat()
        )


def test_window_and_parameter_validation():
    with pytest.raises(ValueError):
        sql_evidence.collect_sql(CONFIG, END, START)
    with pytest.raises(ValueError):
        sql_evidence.collect_sql(CONFIG, "2026-09-25T06:00:00", END)


def test_query_store_publication_retains_numeric_evidence_but_not_raw_sql():
    data = {
        "top_queries": {
            "status": "measured",
            "rows": [
                {
                    "query_id": 47,
                    "plan_id": 51,
                    "avg_duration_ms": 2.5,
                    "executions": 9,
                    "query_sql_text": "SELECT confidential FROM private_table",
                }
            ],
        },
        "interval_overlap_may_include_out_of_window_executions": True,
    }
    clean = sanitize_document("query-store-summary.json", data)
    row = clean["top_queries"]["rows"][0]
    assert row["query_id"].startswith("poc-")
    assert row["avg_duration_ms"] == 2.5
    assert row["executions"] == 9
    assert "query_sql_text" not in row


def test_cloud_observer_uses_supplied_identity_and_online_arm_state_without_cli(monkeypatch):
    monkeypatch.setattr(
        sql_evidence, "sql_configuration", lambda *a: pytest.fail("Azure CLI invoked")
    )
    monkeypatch.setattr(sql_evidence, "credential_for", lambda *a: pytest.fail("Identity fallback"))
    monkeypatch.setattr(sql_evidence, "dataset_state", lambda *a: pytest.fail("Application SELECT"))
    credential = MagicMock()
    creator = MagicMock()
    monkeypatch.setattr(sql_evidence, "connection_creator", creator)
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.fetchmany.return_value = []
    factory = MagicMock(return_value=engine)
    monkeypatch.setattr(sql_evidence, "make_engine", factory)
    diagnostics, query_store = sql_evidence.collect_sql(
        CONFIG,
        START,
        END,
        control={"status": "Online"},
        credential=credential,
        observer_only=True,
    )
    assert creator.call_args.args[1] is credential
    assert factory.call_args.kwargs["pooled"] is False
    assert diagnostics["resource_samples"]["status"] == "measured"
    assert diagnostics["schema_versions"]["rows"] is None
    assert query_store["top_queries"]["status"] == "measured"
    assert len(connection.execute.call_args_list) == 5
    engine.dispose.assert_called_once()
    credential.close.assert_not_called()


def test_cloud_paused_database_never_creates_sql_engine(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(sql_evidence, "make_engine", factory)
    diagnostics, query_store = sql_evidence.collect_sql(
        CONFIG,
        START,
        END,
        control={"status": "Paused"},
        credential=MagicMock(),
        observer_only=True,
    )
    assert diagnostics["status"] == query_store["status"] == NOT_DEMONSTRATED
    factory.assert_not_called()
