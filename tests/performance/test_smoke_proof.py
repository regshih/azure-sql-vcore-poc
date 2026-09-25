import json
from unittest.mock import Mock

import pytest

from src.experiments import cloud_evidence, runner
from src.experiments.common import read_json
from src.experiments.profiles import load_profile


def success(run_id="run-current"):
    return {
        "test_id": run_id,
        "operation": "point-lookup",
        "http_status": 200,
        "outcome": "Completed normally",
        "db_calls": 1,
        "elapsed_ms": 7,
        "write": False,
    }


@pytest.mark.parametrize(
    "override",
    [
        {"test_id": "another-run"},
        {"operation": "metadata"},
        {"operation": "slow-query"},
        {"http_status": 500},
        {"http_status": None},
        {"outcome": "Unknown and requiring investigation"},
        {"db_calls": None},
        {"db_calls": 0},
        {"db_calls": True},
        {"db_calls": float("nan")},
    ],
)
def test_cloud_smoke_cannot_substitute_status_or_cached_responses_for_sql_proof(workdir, override):
    path = workdir / "requests.jsonl"
    path.write_text(json.dumps({**success(), **override}) + "\n")
    assert runner.sql_business_successes(path, "run-current") == 0
    path.write_text(json.dumps(success()) + "\n")
    assert runner.sql_business_successes(path, "run-current") == 1


@pytest.mark.parametrize("successful", [False, True])
def test_cloud_smoke_requires_business_success_and_archives_final_failure(
    workdir, monkeypatch, successful
):
    monkeypatch.setattr(runner, "environment_configuration", lambda: {"region": "eastus"})
    monkeypatch.setattr(
        runner.client,
        "metadata",
        lambda *a, **k: {
            "repository_backend": "sql",
            "sql_adapter_configured": True,
            "instance_id": "app-one",
        },
    )
    monkeypatch.setattr(
        runner.fairness,
        "snapshot",
        lambda *a, **k: {
            "instance_id": "app-one",
            "database_validation": "metadata_query_succeeded",
        },
    )
    monkeypatch.setattr(runner.client, "snapshot", lambda *a: None)
    monkeypatch.setattr(
        cloud_evidence,
        "database_configuration",
        lambda: ({"sku": {"name": "GP_Gen5", "capacity": 2}}, {"status": "measured"}),
    )
    monkeypatch.setattr(runner, "MetricsSampler", lambda *a: Mock(samples=[], summary=lambda: {}))
    monkeypatch.setattr(runner, "collect", lambda *a, **k: None)
    monkeypatch.setattr(runner, "emit_evidence", lambda *a: None)
    archived = []
    monkeypatch.setattr(
        "src.experiments.storage.archive_if_configured",
        lambda path, *a: archived.append(read_json(path / "manifest.final.json")),
    )

    def workload(profile, host, directory, run_id):
        record = json.dumps(success(run_id)) + "\n" if successful else ""
        (directory / "requests.jsonl").write_text(record)
        return 0

    monkeypatch.setattr(runner, "invoke_locust", workload)
    if successful:
        runner.run(
            load_profile("smoke", duration=60),
            "http://localhost",
            output=workdir / "run",
            collect_cloud=True,
        )
    else:
        with pytest.raises(RuntimeError, match="no successful SQL-backed business"):
            runner.run(
                load_profile("smoke", duration=60),
                "http://localhost",
                output=workdir / "run",
                collect_cloud=True,
            )
    assert archived[0]["status"] == ("completed" if successful else "failed")
    assert archived[0]["sql_business_request_success_count"] == int(successful)
