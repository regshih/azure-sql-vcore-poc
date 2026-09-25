import json
import time
from contextlib import contextmanager
from uuid import UUID

import httpx
import pytest
from azure.core.credentials import AccessToken

from src.experiments import cloud_evidence as cloud
from src.experiments import evidence, runner
from src.experiments.common import read_json, write_json
from src.experiments.profiles import load_profile

START, END = "2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"


def settings():
    subscription, workspace, identity = (str(UUID(int=n)) for n in (1, 2, 3))
    return cloud.Settings(
        f"/subscriptions/{subscription}/resourceGroups/rg-synthetic"
        "/providers/Microsoft.Sql/servers/synthetic-server/databases/synthetic-db",
        subscription,
        workspace,
        identity,
        wait_seconds=0,
    )


class Credential:
    def __init__(self):
        self.scopes = []

    def get_token(self, *scopes, **kwargs):
        self.scopes.extend(scopes)
        return AccessToken("synthetic-test-value", int(time.time()) + 60)


def handler(*, empty=False, logs_count=2, forbidden=False, partial=False):
    def respond(request):
        if request.url.host == "prices.azure.com":
            assert "Authorization" not in request.headers
            return httpx.Response(
                200,
                json={
                    "Items": [
                        {
                            "retailPrice": 0.4,
                            "skuName": "Paid test compute",
                            "meterName": "vCore",
                            "unitOfMeasure": "1 Hour",
                        }
                    ],
                    "NextPageLink": None,
                },
            )
        if forbidden:
            return httpx.Response(403, json={"error": {"message": "not disclosed"}})
        if request.url.path.endswith("metricDefinitions"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "name": {"value": name},
                            "supportedAggregationTypes": ["Total"]
                            if kind == "count"
                            else ["Average", "Maximum"],
                            "unit": "Count" if kind == "count" else "Percent",
                        }
                        for name, kind in evidence.METRICS.items()
                    ]
                },
            )
        if request.url.path.endswith("/metrics"):
            name = request.url.params["metricnames"]
            assert request.url.params["timespan"] == START + "/" + END
            assert request.url.params["api-version"] == "2023-10-01"
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "name": {"value": name},
                            "errorCode": "Success",
                            "timeseries": [
                                {
                                    "data": []
                                    if empty
                                    else [
                                        {
                                            "timeStamp": START,
                                            "maximum": 10,
                                            "average": 5,
                                            "total": 3,
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                },
            )
        if request.url.path.endswith("/query"):
            body = json.loads(request.content)
            assert body["timespan"] == START + "/" + END
            query = body["query"]
            if "getschema" in query:
                field = "Log_s" if query.startswith("Container") else "Properties"
                columns, rows = ["ColumnName"], [["TimeGenerated"], [field]]
            else:
                assert "run-synthetic" in query and "summarize observed_rows=count()" in query
                columns, rows = ["observed_rows"], [[logs_count]]
            payload = {
                "tables": [
                    {
                        "name": "PrimaryResult",
                        "columns": [{"name": name} for name in columns],
                        "rows": rows,
                    }
                ]
            }
            if partial:
                payload["error"] = {"code": "PartialError", "message": "not disclosed"}
            return httpx.Response(200, json=payload)
        return httpx.Response(
            200,
            json={
                "sku": {"name": "GP_Gen5", "capacity": 2},
                "properties": {"status": "Online"},
                "location": "eastus",
            },
        )

    return respond


def setup_collection(workdir, monkeypatch, responder):
    evidence.initialize(workdir)
    write_json(
        workdir / "manifest.json",
        {
            "test_run_id": "run-synthetic",
            "start_utc": START,
            "end_utc": END,
            "compute_tier": "Serverless",
        },
    )
    write_json(workdir / "configuration.json", {"database": {"sku": {"name": "GP_S_Gen5"}}})
    write_json(
        workdir / "cloud-configuration.json",
        {
            "sql_server": "synthetic-server",
            "database": "synthetic-db",
            "region": "eastus",
            "managed_identity_client_id": settings().client_id,
        },
    )
    credential = Credential()
    monkeypatch.setattr(cloud.Settings, "environment", lambda: settings())
    clients = []

    @contextmanager
    def connect(config):
        with httpx.Client(transport=httpx.MockTransport(responder)) as http:
            api = cloud.API(config, credential, http)
            clients.append(api)
            yield api

    monkeypatch.setattr(cloud, "connection", connect)
    monkeypatch.setattr(
        "src.experiments.common.command_json", lambda *a: pytest.fail("Azure CLI used")
    )

    def observer(config, start, end, **kwargs):
        assert kwargs["control"]["status"] == "Online"
        assert kwargs["observer_only"] is True
        assert kwargs["credential"] is credential
        credential.get_token("https://database.windows.net/.default")
        section = {"status": "measured", "rows": [], "empty_rows_do_not_prove_zero_activity": True}
        return (
            {"resource_samples": section, "storage": section},
            {"options": section, "top_queries": section, "waits": section},
        )

    monkeypatch.setattr("src.experiments.sql_evidence.collect_sql", observer)
    return credential, clients


def test_rest_collector_uses_correct_scopes_and_actual_samples_without_cli(workdir, monkeypatch):
    credential, clients = setup_collection(workdir, monkeypatch, handler())
    coverage = cloud.collect(workdir)
    assert coverage["status"] == "measured"
    assert coverage["required_metrics_missing"] == []
    assert coverage["correlated_log_rows_observed"] is True
    assert coverage["sql_data_plane_attempted"] is True
    assert set(credential.scopes) == {
        cloud.ARM + "/.default",
        cloud.LOG_SCOPE,
        "https://database.windows.net/.default",
    }
    metrics = read_json(workdir / "azure-sql-metrics.json")
    assert metrics["metrics"]["cpu_percent"]["aggregations"]["Maximum"]["value"] == 10
    assert metrics["billed_compute_vcore_seconds"] == 3
    assert metrics["allocated_vcores"] is None
    assert read_json(workdir / "query-store-summary.json")["top_queries"]["status"] == "measured"
    assert read_json(workdir / "cost-inputs.json")["paid_candidates"][0]["retailPrice"] == 0.4
    encoded = json.dumps(coverage)
    assert "Authorization" not in encoded and "synthetic-test-value" not in encoded
    assert settings().resource_id not in encoded
    assert all(item["http_status"] == 200 for item in clients[0].requests)


def test_optional_metric_gap_is_explicit_not_a_full_evidence_success(workdir, monkeypatch):
    base = handler()

    def response(request):
        value = base(request)
        if request.url.path.endswith("metricDefinitions"):
            payload = value.json()
            payload["value"] = [
                item for item in payload["value"] if item["name"]["value"] != "availability"
            ]
            return httpx.Response(200, json=payload)
        return value

    setup_collection(workdir, monkeypatch, response)
    coverage = cloud.collect(workdir)
    assert coverage["status"] == "measured-with-gaps"
    assert coverage["scope"] == "azure-monitor-and-read-only-sql-observer"
    assert coverage["query_store_observer_required"] is True
    assert coverage["sql_data_plane_attempted"] is True
    assert read_json(workdir / "azure-sql-metrics.json")["metrics"]["availability"]["value"] is None


@pytest.mark.parametrize("kind", ["empty", "no-logs", "forbidden", "partial"])
def test_unmeasured_or_failed_cloud_collection_is_nonzero_with_persisted_coverage(
    workdir, monkeypatch, kind
):
    options = {
        "empty": {"empty": True},
        "no-logs": {"logs_count": 0},
        "forbidden": {"forbidden": True},
        "partial": {"partial": True},
    }
    setup_collection(workdir, monkeypatch, handler(**options[kind]))
    with pytest.raises(cloud.CollectionError, match="incomplete"):
        cloud.collect(workdir)
    coverage = read_json(workdir / "collection-coverage.json")
    assert coverage["status"] == "incomplete"
    assert read_json(workdir / "manifest.json")["evidence_collection_status"] == "incomplete"
    assert (workdir / "azure-sql-metrics.json").exists()
    assert "not disclosed" not in json.dumps(coverage)


def test_missing_environment_is_failure_not_default_success(workdir, monkeypatch):
    evidence.initialize(workdir)
    write_json(
        workdir / "manifest.json",
        {
            "test_run_id": "run-synthetic",
            "start_utc": START,
            "end_utc": END,
        },
    )
    for name in (
        "SQL_RESOURCE_ID",
        "AZURE_SUBSCRIPTION_ID",
        "LOG_ANALYTICS_WORKSPACE_ID",
        "AZURE_CLIENT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(cloud.CollectionError, match="incomplete"):
        cloud.collect(workdir)
    assert read_json(workdir / "collection-coverage.json")["failure_category"] == "ValueError"
    with pytest.raises(ValueError, match="No evidence source"):
        evidence.collect(workdir)


def test_unbounded_log_window_is_rejected_before_any_azure_request(workdir, monkeypatch):
    credential, clients = setup_collection(workdir, monkeypatch, handler())
    manifest = read_json(workdir / "manifest.json")
    manifest["start_utc"] = "2025-01-01T00:00:00Z"
    write_json(workdir / "manifest.json", manifest)
    with pytest.raises(cloud.CollectionError, match="incomplete"):
        cloud.collect(workdir)
    assert clients == []
    assert credential.scopes == []


def test_rest_auth_does_not_follow_redirects_or_disclose_errors():
    credential = Credential()
    seen = []

    def redirect(request):
        seen.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://example.invalid/stolen"})

    with httpx.Client(transport=httpx.MockTransport(redirect)) as http:
        api = cloud.API(settings(), credential, http)
        with pytest.raises(cloud.CollectionError):
            api.database()
    assert seen == ["management.azure.com"]
    assert "example.invalid" not in json.dumps(api.requests)


def test_settings_reject_arbitrary_urls_and_cross_subscription_resource_ids():
    current = settings()
    for resource in ("https://example.invalid/resource", current.resource_id + "?query=unsafe"):
        with pytest.raises(ValueError):
            cloud.Settings(
                resource, current.subscription_id, current.workspace_id, current.client_id
            )
    with pytest.raises(ValueError):
        cloud.Settings(
            current.resource_id, str(UUID(int=4)), current.workspace_id, current.client_id
        )


def test_retry_is_bounded_and_failure_receipts_never_contain_response_text(monkeypatch):
    monkeypatch.setattr(cloud.time, "sleep", lambda *a: None)
    calls = []

    def unavailable(request):
        calls.append(1)
        return httpx.Response(503, json={"error": {"message": "not disclosed"}})

    with httpx.Client(transport=httpx.MockTransport(unavailable)) as http:
        api = cloud.API(settings(), Credential(), http)
        with pytest.raises(cloud.CollectionError):
            api.database()
    assert len(calls) == len(api.requests) == 3
    assert "not disclosed" not in json.dumps(api.requests)


def test_managed_identity_factory_excludes_cli_and_secret_credential_fallback(monkeypatch):
    captured = {}

    @contextmanager
    def identity(**kwargs):
        captured.update(kwargs)
        yield Credential()

    monkeypatch.setattr(cloud, "ManagedIdentityCredential", identity)
    monkeypatch.setattr(cloud, "AzureCliCredential", lambda **k: pytest.fail("CLI fallback used"))
    with cloud.connection(settings()) as api:
        assert api.settings == settings()
    assert captured["client_id"] == settings().client_id


def test_exhausted_deadline_never_issues_another_request():
    credential = Credential()
    with httpx.Client(transport=httpx.MockTransport(handler())) as http:
        api = cloud.API(settings(), credential, http)
        api.deadline = time.monotonic() - 1
        with pytest.raises(cloud.CollectionError, match="deadline"):
            api.database()
    assert credential.scopes == []
    assert api.requests == []


def test_observer_permission_failure_prevents_cloud_collection_success(workdir, monkeypatch):
    setup_collection(workdir, monkeypatch, handler())
    monkeypatch.setattr(
        "src.experiments.sql_evidence.collect_sql",
        lambda *a, **k: ({"status": "unavailable"}, {"status": "unavailable"}),
    )
    with pytest.raises(cloud.CollectionError, match="incomplete"):
        cloud.collect(workdir)
    coverage = read_json(workdir / "collection-coverage.json")
    assert coverage["query_store_measured"] is False
    assert coverage["sql_data_plane_attempted"] is True


def test_idle_collection_never_probes_sql_even_when_control_plane_is_online(workdir, monkeypatch):
    setup_collection(workdir, monkeypatch, handler())
    manifest = read_json(workdir / "manifest.json")
    manifest["profile"] = {"scenario": "idle"}
    write_json(workdir / "manifest.json", manifest)
    monkeypatch.setattr(
        "src.experiments.sql_evidence.collect_sql", lambda *a, **k: pytest.fail("SQL during idle")
    )
    coverage = cloud.collect(workdir)
    assert coverage["sql_data_plane_attempted"] is False
    assert coverage["sql_collection_skipped_for_idle"] is True


def test_operator_http_collector_selects_azure_cli_identity_not_managed_identity(monkeypatch):
    captured = {}

    @contextmanager
    def identity(**kwargs):
        captured.update(kwargs)
        yield Credential()

    monkeypatch.setattr(cloud, "AzureCliCredential", identity)
    monkeypatch.setattr(cloud, "ManagedIdentityCredential", lambda **k: pytest.fail("MI selected"))
    config = {
        "subscription_id": settings().subscription_id,
        "resource_group": "rg-synthetic",
        "sql_server": "synthetic-server",
        "database": "synthetic-db",
        "workspace_id": settings().workspace_id,
    }
    operator = cloud.Settings.from_config(config)
    with cloud.connection(operator):
        pass
    assert operator.credential == "azure-cli"
    assert captured["process_timeout"] == 30


def test_runner_archives_failed_cloud_collection_and_seals_failure_manifest(workdir, monkeypatch):
    monkeypatch.setattr(runner, "environment_configuration", lambda: {"region": "eastus"})
    monkeypatch.setattr(
        runner.client,
        "metadata",
        lambda *a: {
            "repository_backend": "sql",
            "sql_adapter_configured": True,
            "instance_id": "cloud-runner-instance",
        },
    )
    monkeypatch.setattr(
        runner.fairness,
        "snapshot",
        lambda *a, **k: {
            "instance_id": "cloud-runner-instance",
            "database_validation": "metadata_query_succeeded",
        },
    )
    monkeypatch.setattr(runner.client, "snapshot", lambda *a: None)
    monkeypatch.setattr(
        cloud,
        "database_configuration",
        lambda: (
            {"sku": {"name": "GP_Gen5", "capacity": 2}},
            {"status": "measured"},
        ),
    )
    archived = []
    monkeypatch.setattr(
        "src.experiments.storage.archive_if_configured",
        lambda directory, *a: archived.append(read_json(directory / "manifest.final.json")),
    )
    monkeypatch.setattr(runner, "emit_evidence", lambda *a: None)

    def workload(profile, host, directory, run_id):
        (directory / "requests.jsonl").write_text("")
        return 0

    def fail_collect(directory, config, **kwargs):
        assert kwargs["cloud_rest"] is True
        write_json(directory / "collection-coverage.json", {"status": "incomplete"})
        raise cloud.CollectionError("incomplete")

    monkeypatch.setattr(runner, "invoke_locust", workload)
    monkeypatch.setattr(runner, "collect", fail_collect)
    with pytest.raises(cloud.CollectionError):
        runner.run(
            load_profile("smoke", duration=60),
            "http://localhost",
            output=workdir / "run",
            collect_cloud=True,
        )
    assert archived[0]["evidence_collection_status"] == "failed"
    assert (workdir / "run" / "collection-coverage.json").exists()
