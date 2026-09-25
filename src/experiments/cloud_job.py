"""Control-plane profile launch, or the private runner job's environment entrypoint."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import yaml

from src.experiments.client import origin
from src.experiments.common import ROOT, read_json, safe_main, utc_now, write_json
from src.experiments.profiles import Profile, load_profile
from src.operations.azure import (
    AzureCLI,
    OperationError,
    load_config,
    output_directory,
    require_tags,
)

RAW = ROOT / "results" / "local-untracked-runs"


def runner_arguments(profile: Profile, host: str, allow_unsafe: bool) -> list[str]:
    """Both launch paths enter runner.main, which owns environment/SDK initialization."""
    args = [
        "-m",
        "src.experiments.runner",
        "--profile",
        profile.name,
        "--host",
        origin(host),
        "--users",
        str(profile.users),
        "--spawn-rate",
        str(profile.spawn_rate),
        "--rate",
        str(profile.rate),
        "--duration",
        str(profile.duration),
        "--write-ratio",
        str(profile.write_ratio),
        "--product-count",
        str(profile.product_count),
        "--collect-cloud",
        "--observe-dataset-state",
    ]
    if profile.scenario == "idle":
        raise OperationError("Idle control requires the Azure-CLI-equipped private operator path")
    if profile.scenario in {"storm", "slow", "cache"}:
        if not allow_unsafe:
            raise OperationError("Controlled cloud profiles require --allow-unsafe-test")
        args += ["--allow-unsafe-test", "--confirm-poc", "--allow-host", origin(host)]
    return args


def execution_template(
    job: dict[str, Any],
    profile: Profile,
    host: str,
    account: str,
    allow_unsafe: bool,
) -> dict[str, Any]:
    properties = job.get("properties", {})
    configuration = properties.get("configuration", {})
    if configuration.get("triggerType") != "Manual":
        raise OperationError("Only the manual POC runner job can be launched")
    manual = configuration.get("manualTriggerConfig", {})
    if manual.get("parallelism") != 1 or manual.get("replicaCompletionCount") != 1:
        raise OperationError("Runner job must use exactly one execution replica")
    if configuration.get("replicaRetryLimit") != 0:
        raise OperationError("Automatic job retries would change offered load; require zero")
    multiplier = 2 if profile.scenario in {"cache", "storm"} else 1
    if configuration.get("replicaTimeout", 0) < profile.duration * multiplier + 600:
        raise OperationError(
            "Job replica timeout must cover the workload plus upload/startup slack"
        )
    template: dict[str, Any] = copy.deepcopy(properties.get("template", {}))
    containers = template.get("containers", [])
    runners = [container for container in containers if container.get("name") == "runner"]
    if len(runners) != 1:
        raise OperationError("Expected exactly one existing container named runner")
    container = runners[0]
    if not container.get("image") or not container.get("resources"):
        raise OperationError("Existing runner image and resources must be observable")
    environment = {item["name"]: item for item in container.get("env", [])}
    if (
        not account
        or environment.get("EVIDENCE_STORAGE_ACCOUNT", {}).get("value") != account
        or environment.get("EVIDENCE_STORAGE_CONTAINER", {}).get("value") != "evidence"
    ):
        raise OperationError("Runner private evidence storage must match deployment outputs")
    token = environment.get("POC_INTERNAL_API_TOKEN", {})
    if not token.get("secretRef") or token.get("value"):
        raise OperationError("Runner internal API authentication must use an existing secretRef")
    container["command"] = ["python"]
    container["args"] = runner_arguments(profile, host, allow_unsafe)
    return template


class ReceiptUnavailable(OperationError):
    pass


def _stream_receipts(cli: AzureCLI, execution_name: str) -> list[dict[str, Any]]:
    args = [
        cli.executable,
        "containerapp",
        "job",
        "logs",
        "show",
        "--name",
        cli.config.runner_job,
        "--resource-group",
        cli.config.resource_group,
        "--execution",
        execution_name,
        "--container",
        "runner",
        "--format",
        "json",
        "--tail",
        "300",
        "--subscription",
        str(cli.config.subscription_id),
        "--only-show-errors",
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode:
        write_json(
            cli.output / "receipt-retrieval.json",
            {"status": "unavailable", "exit_code": result.returncode},
        )
        raise ReceiptUnavailable(
            "Exact execution logs unavailable; cloud evidence receipt unverified"
        )
    if len(result.stdout) > 4 * 1024**2:
        raise OperationError("Execution logs exceeded the bounded retrieval size")
    (cli.output / "job-console.jsonl").write_text(result.stdout, encoding="utf-8")
    return _parse_receipts(cli, result.stdout)


def _parse_receipts(cli: AzureCLI, text: str) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
            message = event.get("Log", event.get("Log_s", "")) if isinstance(event, dict) else ""
        except json.JSONDecodeError:
            message = line
        if not isinstance(message, str):
            continue
        if "private-evidence-persistence-failed" in message:
            raise OperationError("private-evidence-persistence-failed")
        marker = "POC_EVIDENCE_UPLOAD "
        if marker not in message:
            continue
        receipt = json.loads(message.split(marker, 1)[1])
        digest = receipt.get("manifest_sha256", "")
        prefix = receipt.get("blob_prefix", "")
        if (
            receipt.get("status") != "uploaded"
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or not re.fullmatch(
                r"runs/(?:run-\d{8}T\d{6}Z-[a-f0-9]{12}|bundle-[a-f0-9]{20})/[a-f0-9]{16}",
                prefix,
            )
            or not prefix.endswith(digest[:16])
            or receipt.get("manifest_blob") != prefix + "/archive-manifest.json"
            or not isinstance(receipt.get("artifact_count"), int)
            or receipt["artifact_count"] <= 0
        ):
            raise OperationError("Execution emitted an invalid evidence upload receipt")
        receipts.append(
            {
                key: receipt[key]
                for key in (
                    "status",
                    "blob_prefix",
                    "manifest_blob",
                    "manifest_sha256",
                    "artifact_count",
                    "total_bytes",
                    "verification",
                    "workload",
                )
                if key in receipt
            }
        )
    if not receipts:
        raise ReceiptUnavailable(
            "Execution ended without a retrievable private evidence upload receipt"
        )
    write_json(
        cli.output / "upload-receipts.json",
        {
            "status": "receipts-observed; Blob download and hashes not independently verified",
            "receipts": receipts,
        },
    )
    return receipts


def receipt_logs(cli: AzureCLI, execution_name: str) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[a-z0-9-]{1,150}", execution_name):
        raise OperationError("Receipt retrieval requires the exact returned execution name")
    try:
        return _stream_receipts(cli, execution_name)
    except (ReceiptUnavailable, subprocess.TimeoutExpired, OSError):
        return _loganalytics_receipts(cli, execution_name)


def _loganalytics_receipts(cli: AzureCLI, execution_name: str) -> list[dict[str, Any]]:
    try:
        workspace = str(UUID(cli.config.workspace_id))
    except (ValueError, AttributeError) as exc:
        raise ReceiptUnavailable(
            "Workspace customer GUID required for historical receipts"
        ) from exc
    deadline = time.monotonic() + 180
    schemas: dict[str, set[str]] = {}
    attempts: list[dict[str, Any]] = []
    for poll in range(6):
        for table in ("ContainerAppConsoleLogs_CL", "ContainerAppConsoleLogs"):
            remaining = deadline - time.monotonic()
            if remaining < 1:
                break
            try:
                if table not in schemas:
                    schema = cli.run(
                        "monitor",
                        "log-analytics",
                        "query",
                        "--workspace",
                        workspace,
                        "--analytics-query",
                        f"{table} | getschema | project ColumnName",
                        timeout=max(1, min(30, int(remaining))),
                    )
                    if not isinstance(schema, list):
                        raise ReceiptUnavailable("Unrecognized console table schema")
                    schemas[table] = {
                        item["ColumnName"]
                        for item in schema
                        if isinstance(item, dict) and isinstance(item.get("ColumnName"), str)
                    }
                columns = schemas[table]
                message = next((name for name in ("Log_s", "Log") if name in columns), None)
                execution = next(
                    (
                        name
                        for name in ("JobExecutionName_s", "JobExecutionName")
                        if name in columns
                    ),
                    None,
                )
                replica = next(
                    (
                        name
                        for name in ("ContainerGroupName_s", "ContainerGroupName")
                        if name in columns
                    ),
                    None,
                )
                container = next(
                    (name for name in ("ContainerName_s", "ContainerName") if name in columns), None
                )
                if "TimeGenerated" not in columns or not message or not (execution or replica):
                    raise ReceiptUnavailable("Console schema lacks exact execution correlation")
                condition = (
                    f"{execution} == '{execution_name}'"
                    if execution
                    else (
                        f"({replica} == '{execution_name}' or "
                        f"{replica} startswith '{execution_name}-')"
                    )
                )
                query = (
                    f"{table} | where TimeGenerated >= ago(48h) | where {condition}"
                    + (f" | where {container} == 'runner'" if container else "")
                    + f" | where {message} contains 'POC_EVIDENCE_UPLOAD '"
                    + f" or {message} contains 'private-evidence-persistence-failed'"
                    + f" | project TimeGenerated, Log=tostring({message})"
                    + " | order by TimeGenerated asc | take 300"
                )
                remaining = deadline - time.monotonic()
                if remaining < 1:
                    break
                rows = cli.run(
                    "monitor",
                    "log-analytics",
                    "query",
                    "--workspace",
                    workspace,
                    "--analytics-query",
                    query,
                    timeout=max(1, min(30, int(remaining))),
                )
                if not isinstance(rows, list) or len(rows) > 300:
                    raise ReceiptUnavailable("Unrecognized or oversized historical log response")
                text = "\n".join(json.dumps(row) for row in rows)
                if len(text) > 4 * 1024**2:
                    raise ReceiptUnavailable("Historical receipts exceed retrieval size limit")
            except (OperationError, subprocess.TimeoutExpired, OSError) as exc:
                attempts.append(
                    {"table": table, "poll": poll, "failure_category": type(exc).__name__}
                )
                continue
            # A reported persistence failure or invalid receipt must never become a retry/success.
            try:
                receipts = _parse_receipts(cli, text)
            except ReceiptUnavailable:
                attempts.append({"table": table, "poll": poll, "status": "not-yet-observed"})
                continue
            write_json(cli.output / "historical-receipts.json", rows)
            write_json(
                cli.output / "receipt-retrieval.json",
                {
                    "status": "receipts-observed",
                    "source": table,
                    "attempts": attempts,
                    "blob_download_independently_verified": False,
                },
            )
            return receipts
        remaining = deadline - time.monotonic()
        if poll < 5 and remaining > 0:
            time.sleep(min(15, remaining))
    write_json(
        cli.output / "receipt-retrieval.json",
        {"status": "unavailable", "source": "log-analytics", "attempts": attempts},
    )
    raise ReceiptUnavailable("Historical receipts unavailable within bounded ingestion wait")


def launch(
    cli: AzureCLI,
    profile: Profile,
    *,
    confirm_poc: bool,
    allow_unsafe: bool = False,
    wait_timeout: float = 14400,
    poll_interval: float = 10,
) -> list[dict[str, Any]]:
    if not confirm_poc:
        raise OperationError("Cloud workload execution requires --confirm-poc")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,99}", cli.config.runner_job):
        raise OperationError("Invalid or missing runner job name")
    host = origin(cli.config.app_url)
    if urlsplit(host).scheme != "https":
        raise OperationError("Cloud workload target must be HTTPS")
    cli.require_poc()
    app = cli.run(
        "containerapp",
        "show",
        "--name",
        cli.config.app_name,
        "--resource-group",
        cli.config.resource_group,
    )
    require_tags(app)
    fqdn = app.get("properties", {}).get("configuration", {}).get("ingress", {}).get("fqdn")
    if not fqdn or urlsplit(host).hostname != fqdn:
        raise OperationError("Configured app URL does not match the tagged deployed app")
    job = cli.run(
        "containerapp",
        "job",
        "show",
        "--name",
        cli.config.runner_job,
        "--resource-group",
        cli.config.resource_group,
    )
    require_tags(job)
    template = execution_template(
        job, profile, host, cli.config.evidence_storage_account, allow_unsafe
    )
    write_json(cli.output / "original-job-template.json", job["properties"]["template"])
    template_path = cli.output / "execution-template.yaml"
    template_path.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")
    write_json(
        cli.output / "cloud-launch.json",
        {
            "started_utc": utc_now(),
            "profile": profile.model_dump(),
            "profile_hash": profile.profile_hash,
            "persistent_job_template_modified": False,
            "evidence_status": "awaiting-execution",
        },
    )
    # CLI --yaml accepts the full execution template and handles the Start API's LRO.
    execution = cli.run(
        "containerapp",
        "job",
        "start",
        "--name",
        cli.config.runner_job,
        "--resource-group",
        cli.config.resource_group,
        "--yaml",
        str(template_path),
    )
    if not isinstance(execution, dict) or not re.fullmatch(
        r"[a-z0-9-]{1,150}", execution.get("name", "")
    ):
        raise OperationError("Start did not return an exact execution name; do not guess/restart")
    name = execution["name"]
    write_json(cli.output / "job-start.json", execution)
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        executions = cli.run(
            "containerapp",
            "job",
            "execution",
            "list",
            "--name",
            cli.config.runner_job,
            "--resource-group",
            cli.config.resource_group,
        )
        current = next((item for item in executions if item.get("name") == name), None)
        if current is not None:
            write_json(cli.output / "job-execution.json", current)
            status = current.get("properties", {}).get("status")
            if status == "Succeeded":
                receipts = receipt_logs(cli, name)
                require_verified_archives(receipts)
                if profile.name == "smoke":
                    require_smoke_evidence(profile, receipts)
                return receipts
            if status in {"Failed", "Stopped", "Degraded", "Canceled"}:
                try:
                    receipt_logs(cli, name)
                except (OperationError, subprocess.TimeoutExpired) as exc:
                    write_json(
                        cli.output / "receipt-retrieval.json",
                        {"status": "unavailable", "failure_category": type(exc).__name__},
                    )
                raise OperationError("Exact workload execution failed; inspect private evidence")
        time.sleep(poll_interval)
    raise OperationError("Wait timed out; execution may still run, inspect before starting another")


def require_verified_archives(receipts: list[dict[str, Any]]) -> None:
    if not receipts:
        raise OperationError("No private archive verification receipt")
    for receipt in receipts:
        proof = receipt.get("verification")
        if (
            not isinstance(proof, dict)
            or proof.get("status") != "verified"
            or proof.get("method") != "blob-readback-sha256"
            or proof.get("credential") != "managed-identity"
            or proof.get("manifest_sha256") != receipt.get("manifest_sha256")
            or type(receipt.get("artifact_count")) is not int
            or receipt["artifact_count"] <= 0
            or type(receipt.get("total_bytes")) is not int
            or receipt["total_bytes"] < 0
            or type(proof.get("artifact_count")) is not int
            or proof["artifact_count"] != receipt["artifact_count"]
            or type(proof.get("total_bytes")) is not int
            or proof["total_bytes"] != receipt["total_bytes"]
        ):
            raise OperationError("Private archive lacks complete managed-identity readback proof")


def require_smoke_evidence(profile: Profile, receipts: list[dict[str, Any]]) -> dict[str, Any]:
    if len(receipts) != 1:
        raise OperationError("Smoke must produce exactly one verified run archive")
    receipt = receipts[0]
    workload = receipt.get("workload")
    if (
        not isinstance(workload, dict)
        or workload.get("workload_profile") != "smoke"
        or workload.get("profile_hash") != profile.profile_hash
        or workload.get("status") != "completed"
        or workload.get("evidence_collection_status") not in {"measured", "measured-with-gaps"}
        or type(workload.get("sql_business_request_success_count")) is not int
        or workload["sql_business_request_success_count"] <= 0
        or not isinstance(workload.get("test_run_id"), str)
        or not receipt.get("blob_prefix", "").startswith(f"runs/{workload['test_run_id']}/")
    ):
        raise OperationError("Verified archive does not demonstrate successful SQL-backed smoke")
    return workload


def launch_smoke(
    cli: AzureCLI,
    *,
    confirm_poc: bool,
    duration: float | None = None,
    wait_timeout: float = 14400,
    poll_interval: float = 10,
) -> dict[str, Any]:
    """Verify exact cloud smoke execution, SQL business success and job-side Blob readback."""
    profile = load_profile("smoke", duration=duration)
    try:
        receipts = launch(
            cli,
            profile,
            confirm_poc=confirm_poc,
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
        )
        require_verified_archives(receipts)
        workload = require_smoke_evidence(profile, receipts)
        report = {
            "status": "verified",
            "execution_name": read_json(cli.output / "job-start.json")["name"],
            "workload_profile": "smoke",
            "profile_hash": profile.profile_hash,
            "sql_business_request_success_count": workload["sql_business_request_success_count"],
            "archive_verification": "runner-readback-confirmed",
            "operator_blob_download_verified": False,
            "receipts": receipts,
        }
        write_json(cli.output / "smoke-verification.json", report)
        return report
    except Exception as exc:
        write_json(
            cli.output / "smoke-verification.json",
            {"status": "failed", "failure_category": type(exc).__name__},
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Launch a private cloud workload or run inside its job"
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--profile", default="smoke")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--users", type=int)
    parser.add_argument("--spawn-rate", type=float)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--write-ratio", type=float)
    parser.add_argument("--product-count", type=int)
    parser.add_argument("--confirm-poc", action="store_true")
    parser.add_argument("--allow-unsafe-test", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--wait-timeout", type=float, default=14400)
    parser.add_argument("--poll-interval", type=float, default=10)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9-]+", args.profile):
        parser.error("--profile must be the name of a profile bundled in the image")
    if not 1 <= args.poll_interval <= 60 or not 30 <= args.wait_timeout <= 172800:
        parser.error("Poll interval must be 1..60 seconds; wait timeout 30..172800 seconds")
    profile = load_profile(
        args.profile,
        duration=args.duration,
        users=args.users,
        spawn_rate=args.spawn_rate,
        rate=args.rate,
        write_ratio=args.write_ratio,
        product_count=args.product_count,
    )
    if args.config is None:
        from src.experiments.runner import main as runner_main

        host = os.environ.get("POC_HOST")
        if not host or not os.environ.get("EVIDENCE_STORAGE_ACCOUNT"):
            parser.error("In-job mode requires POC_HOST and mandatory private evidence storage")
        if profile.scenario in {"storm", "slow", "cache"} and not args.confirm_poc:
            parser.error("Controlled in-job profiles require both safety confirmation flags")
        command = runner_arguments(profile, host, args.allow_unsafe_test)
        if args.output:
            command += ["--output", str(args.output)]
        return runner_main(command[2:])
    if not args.confirm_poc:
        parser.error("Control-plane launch requires --confirm-poc")
    config = load_config(args.config)
    output = args.output.resolve() if args.output else output_directory("cloud-profile")
    if not output.is_relative_to(RAW.resolve()):
        parser.error("Cloud launch output must stay under ignored results/local-untracked-runs")
    if args.output and output.exists() and any(output.iterdir()):
        parser.error("Cloud launch output must be new or empty; refusing stale receipts")
    cli = AzureCLI(config, output)
    try:
        receipts = launch(
            cli,
            profile,
            confirm_poc=args.confirm_poc,
            allow_unsafe=args.allow_unsafe_test,
            wait_timeout=args.wait_timeout,
            poll_interval=args.poll_interval,
        )
    except Exception as exc:
        write_json(
            output / "launch-outcome.json",
            {
                "status": "failed",
                "failure_category": type(exc).__name__,
                "remote_execution_may_continue": True,
                "automatic_restart_attempted": False,
            },
        )
        raise
    write_json(
        output / "launch-outcome.json",
        {
            "status": "execution-succeeded-receipts-observed",
            "upload_receipts": receipts,
            "blob_download_independently_verified": False,
            "private_download_required": True,
        },
    )
    print(
        json.dumps(
            {
                "status": "execution-succeeded-receipts-observed",
                "private_evidence": output.relative_to(ROOT).as_posix(),
                "profile_hash": profile.profile_hash,
                "upload_receipts": receipts,
                "blob_download_independently_verified": False,
                "private_download_required": True,
                "required_next_step": (
                    "VNet-connected operator must run src.experiments.storage with "
                    "--credential azure-cli and verify the complete private inventory"
                ),
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main))
