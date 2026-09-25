import json
from contextlib import contextmanager
from unittest.mock import Mock
from uuid import UUID

from src.experiments import evidence
from src.experiments.reporting import application_recovery
from src.experiments.runner import compact_evidence


def test_failed_first_then_stable_success_reports_measured_recovery(workdir):
    rows = [
        {
            "timestamp": f"2026-01-01T00:00:{second:02d}Z",
            "outcome": "API timeout" if second == 1 else "Completed normally",
            "elapsed_ms": 100,
        }
        for second in range(1, 10)
    ]
    (workdir / "requests.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    result = application_recovery(
        workdir,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:03Z",
        stable_requests=5,
    )
    assert result["failed_requests_after_start"] == 1
    assert result["stable_observed_utc"] == "2026-01-01T00:00:07Z"
    assert result["stable_observation_seconds_after_operation_end"] == 4
    assert result["measured_data_loss"] is None


def test_log_evidence_compacts_arrays_without_inventing_counts():
    result = compact_evidence({"attempts": [{"attempt": n} for n in range(100)]})
    assert result["attempts"]["record_count"] == 100
    assert len(result["attempts"]["first_records"]) == 3
    assert result["attempts"]["truncated_for_log"] is True


def test_kql_requires_verified_schema_columns(monkeypatch):
    from src.experiments import cloud_evidence

    commands = []

    def invoke(query, *args):
        commands.append(query)
        return [{"ColumnName": "TimeGenerated"}]

    @contextmanager
    def connection(settings):
        assert settings.credential == "azure-cli"
        yield Mock(query=invoke)

    monkeypatch.setattr(cloud_evidence, "connection", connection)
    result = evidence.collect_logs(
        {
            "workspace_id": str(UUID(int=1)),
            "subscription_id": str(UUID(int=2)),
            "resource_group": "rg-example",
            "sql_server": "example",
            "database": "example",
        },
        ["AppRequests"],
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:01:00Z",
        "run-local",
    )
    assert result["AppRequests"]["value"] is None
    assert len(commands) == 1


def test_workspace_log_counts_do_not_claim_run_correlation():
    from src.experiments.cloud_evidence import logs

    api = Mock()
    api.query.side_effect = [[{"ColumnName": "TimeGenerated"}], [{"observed_rows": 9}]]
    result = logs(
        api,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:01:00Z",
        "run-local",
        tables=["AzureDiagnostics"],
    )
    assert result["AzureDiagnostics"]["status"] == "measured"
    assert result["AzureDiagnostics"]["observed_rows"] == 9
    assert result["AzureDiagnostics"]["run_id_correlated"] is False
    assert "run-local" not in api.query.call_args.args[0]
