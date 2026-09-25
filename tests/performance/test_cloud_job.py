import copy
import json
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
import yaml

from src.database.seed import PROFILES
from src.experiments import cloud_evidence, cloud_job, runner
from src.experiments.common import read_json
from src.experiments.profiles import load_profile
from src.operations.azure import OperationError


def job():
    return {
        "tags": {"poc": "sql-vcore", "environment": "poc"},
        "properties": {
            "configuration": {
                "triggerType": "Manual",
                "manualTriggerConfig": {"parallelism": 1, "replicaCompletionCount": 1},
                "replicaRetryLimit": 0,
                "replicaTimeout": 14400,
            },
            "template": {
                "containers": [
                    {
                        "name": "runner",
                        "image": "synthetic-image@sha256:" + "a" * 64,
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                        "command": ["python", "-m", "src.experiments.cloud_job"],
                        "args": ["--profile", "smoke"],
                        "env": [
                            {"name": "EVIDENCE_STORAGE_ACCOUNT", "value": "syntheticevidence"},
                            {"name": "EVIDENCE_STORAGE_CONTAINER", "value": "evidence"},
                            {"name": "POC_INTERNAL_API_TOKEN", "secretRef": "internal-api"},
                        ],
                    }
                ],
                "initContainers": [{"name": "init", "image": "synthetic-init"}],
            },
        },
    }


def test_template_preserves_entire_existing_container_except_command_arguments():
    original = job()
    snapshot = copy.deepcopy(original)
    profile = load_profile("peak", duration=60, users=3, rate=5)
    template = cloud_job.execution_template(
        original, profile, "https://example.invalid", "syntheticevidence", False
    )
    assert original == snapshot
    container = template["containers"][0]
    previous = original["properties"]["template"]["containers"][0]
    assert container["env"] == previous["env"]
    assert container["image"] == previous["image"]
    assert container["resources"] == previous["resources"]
    assert template["initContainers"] == snapshot["properties"]["template"]["initContainers"]
    assert container["command"] == ["python"]
    assert container["args"][:2] == ["-m", "src.experiments.runner"]
    assert container["args"][container["args"].index("--profile") + 1] == "peak"


@pytest.mark.parametrize("entrypoint", ["default-job", "operator-template"])
@pytest.mark.parametrize(
    "profile_name,successful",
    [("smoke", True), ("expected", True), ("peak", True), ("smoke", False)],
)
def test_both_cloud_entrypoints_initialize_sdk_collect_and_archive(
    workdir, monkeypatch, entrypoint, profile_name, successful
):
    subscription, workspace, identity = (str(UUID(int=n)) for n in (1, 2, 3))
    environment = {
        "AZURE_SUBSCRIPTION_ID": subscription,
        "AZURE_CLIENT_ID": identity,
        "LOG_ANALYTICS_WORKSPACE_ID": workspace,
        "SQL_RESOURCE_ID": f"/subscriptions/{subscription}/resourceGroups/rg-synthetic"
        "/providers/Microsoft.Sql/servers/synthetic-server/databases/poc",
        "SQL_SERVER": ".".join(("synthetic-server", "database.windows.net")),
        "SQL_DATABASE": "poc",
        "POC_RESOURCE_GROUP": "rg-synthetic",
        "POC_REGION": "eastus",
        "POC_ENVIRONMENT_NAME": "synthetic",
        "POC_HOST": "https://example.invalid",
        "POC_INTERNAL_API_TOKEN": "never-copy-the-secret",
        "EVIDENCE_STORAGE_ACCOUNT": "syntheticevidence",
        "EVIDENCE_STORAGE_CONTAINER": "evidence",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("CONTAINER_APP_JOB_NAME", raising=False)
    deployment = {
        "repository_backend": "sql",
        "sql_adapter_configured": True,
        "instance_id": "app-one",
    }
    monkeypatch.setattr(runner.client, "metadata", lambda *a, **k: deployment)
    monkeypatch.setattr(
        runner.fairness,
        "snapshot",
        lambda *a, **k: {
            **deployment,
            "database_validation": "metadata_query_succeeded",
            "product_count": 24,
        },
    )
    monkeypatch.setattr(runner.client, "snapshot", lambda *a: None)
    monkeypatch.setattr(runner, "MetricsSampler", lambda *a: Mock(samples=[], summary=lambda: {}))
    monkeypatch.setattr(runner, "emit_evidence", lambda *a: None)
    monkeypatch.setattr(
        cloud_job, "AzureCLI", Mock(side_effect=AssertionError("No operator CLI inside job"))
    )
    database = {
        "sku": {"name": "GP_Gen5_2", "capacity": 2, "family": "Gen5"},
        "computeModel": "Provisioned",
        "location": "eastus",
        "status": "Online",
    }
    sdk_settings = []

    @contextmanager
    def connection(settings):
        sdk_settings.append(settings)
        yield Mock(database=lambda: database, requests=[])

    monkeypatch.setattr(cloud_evidence, "connection", connection)
    collector, archive = Mock(), Mock()
    monkeypatch.setattr(cloud_evidence, "collect", collector)
    monkeypatch.setattr("src.experiments.storage.archive_if_configured", archive)

    def workload(profile, host, directory, run_id):
        row = {
            "test_id": run_id,
            "operation": "point-lookup",
            "http_status": 200,
            "outcome": "Completed normally",
            "db_calls": 1,
            "elapsed_ms": 7,
            "write": False,
        }
        (directory / "requests.jsonl").write_text(json.dumps(row) + "\n" if successful else "")
        return 0

    monkeypatch.setattr(runner, "invoke_locust", workload)
    directory = workdir / "run"
    profile = load_profile(profile_name, duration=60, product_count=24)

    def execute():
        if entrypoint == "default-job":
            return cloud_job.main(
                [
                    "--profile",
                    profile_name,
                    "--duration",
                    "60",
                    "--product-count",
                    "24",
                    "--output",
                    str(directory),
                ]
            )
        container = cloud_job.execution_template(
            job(), profile, environment["POC_HOST"], "syntheticevidence", False
        )["containers"][0]
        assert container["args"][:2] == ["-m", "src.experiments.runner"]
        return runner.main(container["args"][2:] + ["--output", str(directory)])

    if successful:
        assert execute() == 0
    else:
        with pytest.raises(RuntimeError, match="no successful SQL-backed business"):
            execute()
    manifest = read_json(directory / "manifest.final.json")
    config = read_json(directory / "cloud-configuration.json")
    assert manifest["status"] == ("completed" if successful else "failed")
    assert manifest["workload_profile"] == profile_name
    assert manifest["profile_hash"] == profile.profile_hash
    assert manifest["region"] == "eastus"
    assert manifest["compute_tier"] == "Provisioned"
    assert manifest["provisioned_vcores"] == 2
    assert manifest["toggles"]["collect_cloud"] is True
    assert manifest["toggles"]["cloud_rest"] is True
    assert config["credential"] == "managed-identity"
    assert config["sql_resource_id"] == environment["SQL_RESOURCE_ID"]
    assert "never-copy-the-secret" not in json.dumps(config)
    assert sdk_settings[0].client_id == identity
    assert sdk_settings[0].credential == "managed-identity"
    assert sdk_settings[0].resource_id == environment["SQL_RESOURCE_ID"]
    collector.assert_called_once_with(
        directory, config=None, skip_sql=False, include_query_store=True, tables=None
    )
    archive.assert_called_once_with(directory, None)
    if profile_name == "smoke":
        assert manifest["sql_business_request_success_count"] == int(successful)


@pytest.mark.parametrize("field,value", [("replicaRetryLimit", 1), ("replicaTimeout", 10)])
def test_job_template_rejects_retries_and_insufficient_upload_window(field, value):
    original = job()
    original["properties"]["configuration"][field] = value
    with pytest.raises(OperationError):
        cloud_job.execution_template(
            original, load_profile("smoke"), "https://example.invalid", "syntheticevidence", False
        )


def test_unsafe_profile_rejects_without_client_gate_and_idle_does_not_launch():
    with pytest.raises(OperationError, match="allow-unsafe"):
        cloud_job.runner_arguments(load_profile("slow-query"), "https://example.invalid", False)
    with pytest.raises(OperationError, match="private operator"):
        cloud_job.runner_arguments(load_profile("idle-resume"), "https://example.invalid", True)
    args = cloud_job.runner_arguments(
        load_profile("connection-storm"), "https://example.invalid", True
    )
    assert "--allow-unsafe-test" in args and "--confirm-poc" in args


def fake_cli(workdir, execution_name="runner-selected"):
    calls = []
    state = SimpleNamespace(polls=0, status="Succeeded", execution_name=execution_name)
    config = SimpleNamespace(
        runner_job="runner-job",
        app_name="synthetic-app",
        resource_group="rg-synthetic",
        app_url="https://example.invalid",
        evidence_storage_account="syntheticevidence",
        subscription_id="synthetic",
    )

    def run(*args):
        calls.append(args)
        if args[:2] == ("containerapp", "show"):
            return {
                "tags": {"poc": "sql-vcore", "environment": "poc"},
                "properties": {"configuration": {"ingress": {"fqdn": "example.invalid"}}},
            }
        if args[:3] == ("containerapp", "job", "show"):
            return job()
        if args[:3] == ("containerapp", "job", "start"):
            assert "--yaml" in args and "--args" not in args
            return {"name": state.execution_name}
        if args[:4] == ("containerapp", "job", "execution", "list"):
            state.polls += 1
            return [
                {"name": "unrelated-older", "properties": {"status": "Succeeded"}},
                {
                    "name": state.execution_name,
                    "properties": {"status": "Running" if state.polls == 1 else state.status},
                },
            ]
        raise AssertionError(args)

    cli = SimpleNamespace(
        config=config, output=workdir, run=run, require_poc=Mock(), executable="az", calls=calls
    )
    return cli, state


def verified_receipt():
    digest = "a" * 64
    run_id = "run-20260925T060000Z-" + "b" * 12
    prefix = f"runs/{run_id}/{digest[:16]}"
    return {
        "status": "uploaded",
        "blob_prefix": prefix,
        "manifest_sha256": digest,
        "manifest_blob": prefix + "/archive-manifest.json",
        "artifact_count": 3,
        "total_bytes": 700,
        "verification": {
            "status": "verified",
            "method": "blob-readback-sha256",
            "credential": "managed-identity",
            "manifest_sha256": digest,
            "artifact_count": 3,
            "total_bytes": 700,
            "operator_download_verified": False,
        },
        "workload": {
            "test_run_id": run_id,
            "workload_profile": "smoke",
            "profile_hash": load_profile("smoke").profile_hash,
            "status": "completed",
            "evidence_collection_status": "measured",
            "sql_business_request_success_count": 1,
        },
    }


def test_launch_waits_only_exact_returned_execution_and_never_updates_job(workdir, monkeypatch):
    cli, state = fake_cli(workdir)
    receipt = verified_receipt()
    logs = Mock(return_value=[receipt])
    monkeypatch.setattr(cloud_job, "receipt_logs", logs)
    monkeypatch.setattr(cloud_job.time, "sleep", lambda _seconds: None)
    receipts = cloud_job.launch(cli, load_profile("expected"), confirm_poc=True)
    assert receipts == [receipt]
    assert state.polls == 2
    logs.assert_called_once_with(cli, "runner-selected")
    assert not any("update" in command for command in cli.calls)
    template = yaml.safe_load((workdir / "execution-template.yaml").read_text())
    assert template["containers"][0]["args"][3] == "expected"
    cli.require_poc.assert_called_once()


def test_public_smoke_helper_requires_exact_execution_and_remote_archive_proof(
    workdir, monkeypatch
):
    cli, state = fake_cli(workdir)
    receipt = verified_receipt()
    parsed = cloud_job._parse_receipts(cli, "POC_EVIDENCE_UPLOAD " + json.dumps(receipt))
    assert parsed == [receipt]
    monkeypatch.setattr(cloud_job, "receipt_logs", Mock(return_value=parsed))
    monkeypatch.setattr(cloud_job.time, "sleep", lambda _: None)
    report = cloud_job.launch_smoke(cli, confirm_poc=True)
    assert report["status"] == "verified"
    assert report["execution_name"] == state.execution_name
    assert report["sql_business_request_success_count"] == 1
    assert report["archive_verification"] == "runner-readback-confirmed"
    assert report["operator_blob_download_verified"] is False
    assert read_json(workdir / "smoke-verification.json") == report


@pytest.mark.parametrize("duration", [1, 15, 59.999])
def test_subminute_cloud_runs_fail_before_control_plane_or_workload_calls(
    workdir, monkeypatch, duration
):
    profile = load_profile("smoke", duration=duration)
    cli, _ = fake_cli(workdir)
    metadata = Mock(side_effect=AssertionError("No API request before duration validation"))
    monkeypatch.setattr(runner.client, "metadata", metadata)
    with pytest.raises(ValueError, match="at least 60 seconds"):
        cloud_job.launch(cli, profile, confirm_poc=True)
    assert cli.calls == []
    cli.require_poc.assert_not_called()
    with pytest.raises(ValueError, match="at least 60 seconds"):
        cloud_job.runner_arguments(profile, "https://example.invalid", False)
    with pytest.raises(ValueError, match="at least 60 seconds"):
        runner.run(profile, "https://example.invalid", collect_cloud=True)
    metadata.assert_not_called()


def test_default_smoke_and_exact_minute_fit_monitor_window():
    assert load_profile("smoke").duration == 90
    profile = load_profile("smoke", duration=60)
    arguments = cloud_job.runner_arguments(profile, "https://example.invalid", False)
    assert arguments[arguments.index("--duration") + 1] == "60.0"


def test_generic_smoke_launcher_also_rejects_empty_workload(workdir, monkeypatch):
    cli, _ = fake_cli(workdir)
    receipt = verified_receipt()
    receipt["workload"]["sql_business_request_success_count"] = 0
    monkeypatch.setattr(cloud_job, "receipt_logs", Mock(return_value=[receipt]))
    monkeypatch.setattr(cloud_job.time, "sleep", lambda _: None)
    with pytest.raises(OperationError, match="SQL-backed smoke"):
        cloud_job.launch(cli, load_profile("smoke"), confirm_poc=True)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("verification", "status", "uploaded-only"),
        ("verification", "manifest_sha256", "f" * 64),
        ("verification", "artifact_count", 2),
        ("verification", "credential", "azure-cli"),
        ("workload", "sql_business_request_success_count", 0),
        ("workload", "sql_business_request_success_count", True),
        ("workload", "status", "failed"),
        ("workload", "evidence_collection_status", "incomplete"),
        ("workload", "profile_hash", "f" * 64),
        ("workload", "workload_profile", "peak"),
        ("workload", "test_run_id", "run-mismatch"),
    ],
)
def test_succeeded_job_is_not_smoke_success_without_complete_proof(
    workdir, monkeypatch, section, key, value
):
    cli, _ = fake_cli(workdir)
    receipt = verified_receipt()
    receipt[section][key] = value
    monkeypatch.setattr(cloud_job, "receipt_logs", Mock(return_value=[receipt]))
    monkeypatch.setattr(cloud_job.time, "sleep", lambda _: None)
    with pytest.raises(OperationError, match="readback proof|SQL-backed smoke"):
        cloud_job.launch_smoke(cli, confirm_poc=True)
    assert read_json(workdir / "smoke-verification.json")["status"] == "failed"


def test_failed_execution_not_confused_with_older_success(workdir, monkeypatch):
    cli, state = fake_cli(workdir)
    state.status = "Failed"
    monkeypatch.setattr(cloud_job, "receipt_logs", Mock(side_effect=OperationError("missing")))
    monkeypatch.setattr(cloud_job.time, "sleep", lambda _seconds: None)
    with pytest.raises(OperationError, match="execution failed"):
        cloud_job.launch(cli, load_profile("smoke"), confirm_poc=True)


def test_no_execution_name_never_guesses_from_latest_execution(workdir, monkeypatch):
    cli, state = fake_cli(workdir, execution_name="")
    with pytest.raises(OperationError, match="exact execution name"):
        cloud_job.launch(cli, load_profile("smoke"), confirm_poc=True)
    assert state.polls == 0


@pytest.mark.parametrize("formatting", ["text", "json"])
def test_receipt_logs_request_exact_execution_and_parse_only_verified_shape(
    workdir, monkeypatch, formatting
):
    cli, _ = fake_cli(workdir)
    digest = "a" * 64
    prefix = "runs/run-20260925T060000Z-" + "b" * 12 + "/" + digest[:16]
    receipt = {
        "status": "uploaded",
        "blob_prefix": prefix,
        "manifest_sha256": digest,
        "manifest_blob": prefix + "/archive-manifest.json",
        "artifact_count": 12,
        "total_bytes": 70,
    }
    message = "POC_EVIDENCE_UPLOAD " + json.dumps(receipt)
    output = (
        "2026-09-25T06:00:00Z stdout F " + message
        if formatting == "text"
        else json.dumps({"Log": message})
    )
    execute = Mock(return_value=subprocess.CompletedProcess([], 0, output))
    monkeypatch.setattr(cloud_job.subprocess, "run", execute)
    assert cloud_job.receipt_logs(cli, "runner-selected") == [receipt]
    args = execute.call_args.args[0]
    assert args[args.index("--execution") + 1] == "runner-selected"
    assert args[args.index("--format") + 1] == "text"


def test_in_job_mode_uses_env_and_same_runner_not_another_job(workdir, monkeypatch):
    monkeypatch.setenv("POC_HOST", "https://example.invalid")
    monkeypatch.setenv("EVIDENCE_STORAGE_ACCOUNT", "syntheticevidence")
    main = Mock(return_value=0)
    monkeypatch.setattr("src.experiments.runner.main", main)
    assert cloud_job.main(["--profile", "peak", "--users", "3", "--duration", "60"]) == 0
    args = main.call_args.args[0]
    assert args[:2] == ["--profile", "peak"]
    assert args[args.index("--host") + 1] == "https://example.invalid"


def test_default_smoke_job_fits_small_bootstrap_and_requires_no_azure_cli(monkeypatch):
    monkeypatch.setenv("POC_HOST", "https://example.invalid")
    monkeypatch.setenv("EVIDENCE_STORAGE_ACCOUNT", "syntheticevidence")
    runner = Mock(return_value=0)
    operator = Mock(side_effect=AssertionError("Azure CLI must not run inside the job"))
    monkeypatch.setattr("src.experiments.runner.main", runner)
    monkeypatch.setattr(cloud_job, "AzureCLI", operator)
    assert cloud_job.main(["--profile", "smoke"]) == 0
    arguments = runner.call_args.args[0]
    product_count = int(arguments[arguments.index("--product-count") + 1])
    assert product_count == PROFILES["small"][1] == 24
    assert "--collect-cloud" in arguments
    assert "--observe-dataset-state" in arguments
    operator.assert_not_called()


@pytest.mark.parametrize("result", ["receipt", "missing", "failed"])
def test_completed_job_uses_bounded_exact_execution_historical_receipts(
    workdir, monkeypatch, result
):
    cli, _ = fake_cli(workdir)
    cli.config.workspace_id = str(UUID(int=10))
    monkeypatch.setattr(
        cloud_job.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 1, "", "stream unavailable")),
    )
    monkeypatch.setattr(cloud_job.time, "sleep", lambda *a: None)
    queries = []
    digest = "a" * 64
    prefix = "runs/bundle-" + "b" * 20 + "/" + digest[:16]
    receipt = {
        "status": "uploaded",
        "blob_prefix": prefix,
        "manifest_sha256": digest,
        "manifest_blob": prefix + "/archive-manifest.json",
        "artifact_count": 3,
    }

    def query(*args, **kwargs):
        assert 1 <= kwargs["timeout"] <= 30
        kql = args[args.index("--analytics-query") + 1]
        if "getschema" in kql:
            return [
                {"ColumnName": value}
                for value in (
                    "TimeGenerated",
                    "Log_s",
                    "ContainerName_s",
                    "ContainerGroupName_s",
                )
            ]
        assert "TimeGenerated >= ago(48h)" in kql
        assert "ContainerGroupName_s == 'runner-selected'" in kql
        assert "ContainerGroupName_s startswith 'runner-selected-'" in kql
        assert "ContainerName_s == 'runner'" in kql
        assert "take 300" in kql
        queries.append(kql)
        if result == "missing":
            return []
        message = (
            "private-evidence-persistence-failed"
            if result == "failed"
            else "POC_EVIDENCE_UPLOAD " + json.dumps(receipt)
        )
        return [{"Log": message}]

    cli.run = query
    if result == "receipt":
        assert cloud_job.receipt_logs(cli, "runner-selected") == [receipt]
        assert (workdir / "historical-receipts.json").is_file()
        report = json.loads((workdir / "receipt-retrieval.json").read_text())
        assert report["blob_download_independently_verified"] is False
    else:
        with pytest.raises(OperationError, match="unavailable|persistence-failed"):
            cloud_job.receipt_logs(cli, "runner-selected")
        assert len(queries) <= 12


def test_in_job_controlled_profile_requires_both_confirmations(monkeypatch):
    monkeypatch.setenv("POC_HOST", "https://example.invalid")
    monkeypatch.setenv("EVIDENCE_STORAGE_ACCOUNT", "syntheticevidence")
    with pytest.raises(SystemExit) as error:
        cloud_job.main(["--profile", "slow-query", "--allow-unsafe-test"])
    assert error.value.code == 2
