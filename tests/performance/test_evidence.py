from contextlib import contextmanager
from unittest.mock import Mock
from uuid import UUID

import pytest

from src.experiments import evidence, matrix
from src.experiments.common import write_json
from src.experiments.evidence import counter_delta, import_attempts, metric_summary


def test_missing_vs_zero_and_billed_vcore_second_sum():
    def payload(values):
        return {"value": [{"timeseries": [{"data": [{"total": item} for item in values]}]}]}

    assert metric_summary(payload([None]), "Total") is None
    assert metric_summary(payload([0]), "Total") == 0
    assert metric_summary(payload([0, 4, 8]), "Total") == 12


def test_collector_discovers_definitions_and_uses_correct_aggregation(monkeypatch):
    from src.experiments import cloud_evidence

    commands = []

    def request(service, path, operation, **kwargs):
        commands.append((path, kwargs))
        if path.endswith("metricDefinitions"):
            return {
                "value": [
                    {
                        "name": {"value": "app_cpu_billed"},
                        "unit": "Count",
                        "supportedAggregationTypes": ["Total"],
                    },
                    {
                        "name": {"value": "cpu_percent"},
                        "unit": "Percent",
                        "supportedAggregationTypes": ["Average", "Maximum"],
                    },
                ]
            }
        agg = kwargs["parameters"]["aggregation"]
        return {
            "value": [{"timeseries": [{"data": [{name.lower(): 0 for name in agg.split(",")}]}]}]
        }

    @contextmanager
    def connection(settings):
        yield Mock(request=request, settings=settings)

    monkeypatch.setattr(cloud_evidence, "connection", connection)
    config = {
        "subscription_id": str(UUID(int=1)),
        "workspace_id": str(UUID(int=2)),
        "resource_group": "rg-example",
        "sql_server": "example",
        "database": "example",
    }
    result = evidence.collect_metrics(config, "2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z")
    assert commands[0][0].endswith("metricDefinitions")
    assert result["billed_compute_vcore_seconds"] == 0
    assert result["metrics"]["workers_percent"]["value"] is None
    assert result["allocated_vcores"] is None
    assert result["metrics"]["cpu_percent"]["aggregations"]["Maximum"]["value"] == 0
    assert result["metrics"]["cpu_percent"]["aggregations"]["Average"]["value"] == 0
    assert len(commands) == 3


def test_counter_deltas_cannot_claim_run_local_totals():
    result = counter_delta({"counts": {"requests": 20}}, {"counts": {"requests": 27}})
    assert result["counts"] == {"requests": 7}
    assert result["run_local_counts"] is None
    assert counter_delta(None, {"counts": {"requests": 40}})["counts"] is None
    assert counter_delta({"counts": {"requests": 8}}, {"counts": {"requests": 1}})["counts"] is None


def test_attempt_telemetry_filters_run_and_unsafe_fields(workdir):
    import json

    path = workdir / "attempts.jsonl"
    events = [
        {
            "event": "operation_attempt",
            "test_run_id": "run-local",
            "attempt": 2,
            "retry_decision": True,
            "raw_sql": "select private",
            "headers": {"x": "private"},
        },
        {"event": "operation_attempt", "test_run_id": "other", "attempt": 1},
    ]
    path.write_text("\n".join(json.dumps(event) for event in events))
    result = import_attempts(path, "run-local")
    assert len(result) == 1
    assert result[0]["attempt"] == 2
    assert "raw_sql" not in result[0] and "headers" not in result[0]


def test_matrix_restores_all_components_when_workload_fails(workdir, monkeypatch):
    config = workdir / "config.json"
    write_json(config, {})
    monkeypatch.setattr(
        matrix.client,
        "metadata",
        lambda _: {
            "cache_mode": "disabled",
            "repository_backend": "sql",
            "sql_adapter_configured": True,
            "instance_id": "matrix-instance",
        },
    )
    monkeypatch.setattr(
        matrix.fairness,
        "snapshot",
        lambda *a, **k: {
            "instance_id": "matrix-instance",
            "database_validation": "metadata_query_succeeded",
        },
    )
    monkeypatch.setattr(matrix.client, "guard_unsafe", lambda *args: None)
    monkeypatch.setattr(
        matrix,
        "sql_configuration",
        lambda _: {"sku": {"tier": "GeneralPurpose", "capacity": 2, "name": "GP_Gen5"}},
    )
    monkeypatch.setattr(matrix, "switch", lambda *args: {})
    tune = Mock()
    cache = Mock()
    restore = Mock()
    monkeypatch.setattr(matrix, "tune", tune)
    monkeypatch.setattr(matrix.client, "set_cache", cache)
    monkeypatch.setattr(matrix, "restore_database", restore)
    monkeypatch.setattr(matrix, "run", Mock(side_effect=RuntimeError("synthetic failure")))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        matrix.execute(
            config,
            "http://localhost",
            workdir / "matrix",
            confirm_poc=True,
            allow_unsafe=True,
            original_tuning="index",
            allowed_hosts=[],
            minimum=0.5,
            maximum=4,
            auto_pause_delay=15,
            selected=[1],
        )
    restore.assert_called_once()
    assert tune.call_args.args[1] == "index"
    assert cache.call_args.args[1] == "disabled"
    assert (workdir / "matrix" / "restoration.json").exists()


def test_matrix_restoration_failure_is_not_swallowed(workdir, monkeypatch):
    config = workdir / "config.json"
    write_json(config, {})
    monkeypatch.setattr(
        matrix.client,
        "metadata",
        lambda _: {
            "cache_mode": "disabled",
            "repository_backend": "sql",
            "sql_adapter_configured": True,
            "instance_id": "matrix-instance",
        },
    )
    monkeypatch.setattr(
        matrix.fairness,
        "snapshot",
        lambda *a, **k: {
            "instance_id": "matrix-instance",
            "database_validation": "metadata_query_succeeded",
        },
    )
    monkeypatch.setattr(matrix.client, "guard_unsafe", lambda *args: None)
    monkeypatch.setattr(
        matrix,
        "sql_configuration",
        lambda _: {"sku": {"tier": "GeneralPurpose", "capacity": 2, "name": "GP_Gen5"}},
    )
    monkeypatch.setattr(matrix, "switch", Mock(side_effect=RuntimeError("operation")))
    monkeypatch.setattr(matrix, "tune", Mock())
    monkeypatch.setattr(matrix.client, "set_cache", Mock())
    monkeypatch.setattr(matrix, "restore_database", Mock(side_effect=RuntimeError("restore")))
    with pytest.raises(RuntimeError, match="restoration failed"):
        matrix.execute(
            config,
            "http://localhost",
            workdir / "matrix",
            confirm_poc=True,
            allow_unsafe=True,
            original_tuning="baseline",
            allowed_hosts=[],
            minimum=0.5,
            maximum=4,
            auto_pause_delay=15,
            selected=[1],
        )


def test_retail_prices_exclude_free_and_require_unique_explicit_selection():
    payload = {
        "retail_candidates": [
            {"meterId": "free-meter", "skuName": "Free", "retailPrice": 0},
            {"meterId": "paid-a", "skuName": "Compute", "retailPrice": 0.3},
            {"meterId": "paid-b", "skuName": "Compute", "retailPrice": 0.4},
        ]
    }
    unknown = evidence.retail_inputs(payload)
    assert unknown["requires_selection"] is True
    assert len(unknown["paid_candidates"]) == 2
    selected = evidence.retail_inputs(payload, {"meterId": "paid-a"})
    assert selected["selected"]["retailPrice"] == 0.3
    assert selected["estimated_compute_cost"] is None
    assert not selected["requires_selection"]


def test_external_json_command_resolves_windows_command_shims(monkeypatch):
    import subprocess

    from src.experiments import common

    resolved = str(common.ROOT / "tools" / "az.cmd")
    invoked = []
    monkeypatch.setattr(common.shutil, "which", lambda _name: resolved)

    def run_command(args, **kwargs):
        invoked.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"status": "ok"}')

    monkeypatch.setattr(common.subprocess, "run", run_command)
    assert common.command_json(["az", "version", "-o", "json"]) == {"status": "ok"}
    assert invoked == [[resolved, "version", "-o", "json"]]
