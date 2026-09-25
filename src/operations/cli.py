from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from azure.core.exceptions import AzureError
from azure.identity import AzureCliCredential
from pydantic import ValidationError

from src.experiments.cloud_job import launch_smoke
from src.operations.azure import (
    ROOT,
    SQL_API,
    AzureCLI,
    DeploymentConfig,
    OperationError,
    change_compute,
    check_capabilities,
    load_config,
    output_directory,
    require_tags,
    start_job,
    utc_now,
    wait_database,
    write_json,
)


def bicep_parameters(config: DeploymentConfig, application: bool) -> dict[str, Any]:
    values: dict[str, Any] = {
        "resourceGroupName": config.resource_group,
        "environmentName": config.environment_name,
        "location": config.region,
        "deploymentProfile": config.deployment_profile,
        "allowEvaluationPublicAccess": config.allow_evaluation_public_access,
        "evaluationIp": config.evaluation_ip,
        "deployApplication": application,
        "image": config.image,
        "sqlComputeTier": config.sql_compute_tier,
        "sqlVcores": config.sql_vcores,
        "sqlMinVcores": str(config.sql_min_vcores),
        "sqlAutoPauseDelay": config.sql_auto_pause_delay,
        "sqlMaxSizeGb": config.sql_max_size_gb,
        "sqlZoneRedundant": config.sql_zone_redundant,
        "sqlBackupRedundancy": config.sql_backup_redundancy,
        "enableDr": config.enable_dr,
        "enableBusinessCritical": config.enable_business_critical,
        "enableLegacyRedis": config.enable_legacy_redis,
        "enableSqlDiagnostics": config.enable_sql_diagnostics,
        "enableAlerts": config.enable_alerts,
        "alertActionGroupIds": config.alert_action_group_ids,
        "alertOwner": config.alert_owner,
        "alertRunbookBaseUrl": config.alert_runbook_base_url,
        "alertThresholds": config.alert_thresholds,
        "secondaryLocation": config.secondary_location,
    }
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {key: {"value": value} for key, value in values.items()},
    }


def deploy_phase(cli: AzureCLI, template: Path, application: bool, *, what_if_only: bool) -> Any:
    parameters = bicep_parameters(cli.config, application)
    name = f"sql-poc-{'app' if application else 'shared'}-{uuid4().hex[:8]}"
    write_json(cli.output / f"{name}-parameters.json", parameters)
    token = secrets.token_urlsafe(32) if application else ""
    if token:
        parameters["parameters"]["internalApiToken"] = {"value": token}
        cli.redactions.append(token)
    try:
        # ARM secure parameters are supplied through an ephemeral file, never argv,
        # committed configuration, or retained run artifacts.
        with tempfile.TemporaryDirectory(prefix="sql-poc-secure-") as directory:
            path = Path(directory) / "parameters.json"
            write_json(path, parameters)
            common = [
                "--name",
                name,
                "--location",
                cli.config.region,
                "--template-file",
                str(template),
                "--parameters",
                f"@{path}",
                "--no-prompt",
            ]
            cli.run("deployment", "sub", "validate", *common)
            changes = cli.run("deployment", "sub", "what-if", *common, "--no-pretty-print")
            write_json(cli.output / f"{name}-what-if.json", changes)
            if what_if_only:
                return None
            result = cli.run("deployment", "sub", "create", *common)
            write_json(cli.output / f"{name}-deployment.json", result)
            return result
    finally:
        if token:
            cli.redactions.remove(token)


def deploy(cli: AzureCLI, config_path: Path, *, what_if_only: bool) -> None:
    config = cli.config
    if cli.run("group", "exists", "--name", config.resource_group):
        cli.require_poc(database=False)
    check_capabilities(
        cli,
        config.sql_compute_tier,
        config.sql_vcores,
        config.sql_min_vcores,
        config.sql_auto_pause_delay,
    )
    template = ROOT / "infra" / "bicep" / "main.bicep"
    cli.run(
        "bicep",
        "build",
        "--file",
        str(template),
        "--outfile",
        str(cli.output / "compiled-template.json"),
    )
    cli.run("bicep", "lint", "--file", str(template))
    for application in (False, True):
        result = deploy_phase(cli, template, application, what_if_only=what_if_only)
        if what_if_only:
            return
        outputs = result["properties"]["outputs"]["deployment"]["value"]
        config = DeploymentConfig.model_validate(config.model_dump() | outputs)
        cli.config = config
        write_json(config_path, config.model_dump(mode="json"))
        if not application:
            if not config.registry_name:
                raise OperationError("Registry output missing; refusing to build/push.")
            revision = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            # Timestamp avoids replacing an existing tag even in an uncommitted POC checkout.
            digest = hashlib.sha256((ROOT / "pyproject.toml").read_bytes()).hexdigest()[:12]
            tag = f"poc:{datetime.now(UTC):%Y%m%d%H%M%S}-{digest}"
            write_json(
                cli.output / "image-source.json",
                {
                    "git_commit": revision.stdout.strip() if revision.returncode == 0 else None,
                    "manifest_sha256_prefix": digest,
                    "image_tag": tag,
                    "uncommitted_source_possible": True,
                },
            )
            cli.run(
                "acr",
                "build",
                "--registry",
                config.registry_name,
                "--image",
                tag,
                "--file",
                str(ROOT / "Dockerfile.azure"),
                str(ROOT),
                "--no-logs",
            )
            image_digest = cli.run(
                "acr",
                "repository",
                "show",
                "--name",
                config.registry_name,
                "--image",
                tag,
                "--query",
                "digest",
            )
            if not isinstance(image_digest, str) or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", image_digest
            ):
                raise OperationError("ACR did not return an immutable image digest.")
            config.image = f"{config.registry_login_server}/poc@{image_digest}"
            write_json(
                cli.output / "image-digest.json",
                {
                    "tag": tag,
                    "digest": image_digest,
                    "image": config.image,
                },
            )
            write_json(config_path, config.model_dump(mode="json"))
    start_job(cli, config.init_job)
    smoke = launch_smoke(cli, confirm_poc=True)
    write_json(
        cli.output / "deployment-verification.json",
        {
            "utc": utc_now(),
            "bootstrap_job": "Succeeded",
            "smoke": smoke,
            "performance_sizing": "Not demonstrated by this POC run.",
        },
    )


def failover(cli: AzureCLI, args: argparse.Namespace) -> None:
    cli.require_poc()
    config = cli.config
    before = cli.run("sql", "db", "show", *config.sql_args())
    started = utc_now()
    if args.geo:
        if not config.enable_dr or not config.secondary_server or not config.failover_group:
            raise OperationError("Deploy optional DR and save partner/listener outputs first.")
        target = config.sql_server if args.failback else config.secondary_server
        require_tags(
            cli.run(
                "sql",
                "server",
                "show",
                "-g",
                config.resource_group,
                "-n",
                target,
            )
        )
        group = cli.run(
            "sql",
            "failover-group",
            "show",
            "-g",
            config.resource_group,
            "-s",
            target,
            "-n",
            config.failover_group,
        )
        if group.get("replicationRole") != "Secondary":
            raise OperationError(
                "Target server is not the current secondary; refusing no-op failover."
            )
        if config.database_id.lower() not in {
            str(value).lower() for value in group.get("databases", [])
        }:
            # After one failover the IDs refer to the other server.
            if not any(
                str(value).lower().endswith(f"/databases/{config.database.lower()}")
                for value in group.get("databases", [])
            ):
                raise OperationError("POC database is not in the configured failover group.")
        operation = [
            "sql",
            "failover-group",
            "set-primary",
            "-g",
            config.resource_group,
            "-s",
            target,
            "-n",
            config.failover_group,
        ]
        if args.allow_data_loss:
            if not args.allow_destructive_tests:
                raise OperationError(
                    "Forced failover requires --allow-destructive-tests AND --allow-data-loss."
                )
            operation.append("--allow-data-loss")
        cli.run(*operation)
        after = cli.run(
            "sql",
            "failover-group",
            "show",
            "-g",
            config.resource_group,
            "-s",
            target,
            "-n",
            config.failover_group,
        )
        if after.get("replicationRole") != "Primary":
            raise OperationError("Failover did not report target Primary.")
    else:
        if args.allow_data_loss or args.failback:
            raise OperationError("Data-loss and failback options apply only to --geo.")
        local_failover(cli)
        after = wait_database(cli, lambda db: db.get("status") == "Online")
    write_json(
        cli.output / "failover-operation.json",
        {
            "started_utc": started,
            "ended_utc": utc_now(),
            "geo": args.geo,
            "forced": args.allow_data_loss,
            "before": before,
            "after": after,
            "client_recovery_rto": None,
            "data_loss_rpo": None,
            "measurement_note": (
                "Control-plane completion is not application RTO/RPO. "
                "Correlate concurrent failover workload and SQL consistency evidence. "
                "Not demonstrated by this POC run."
            ),
        },
    )


def local_failover(cli: AzureCLI) -> None:
    resource = f"https://management.azure.com{cli.config.database_id}/failover"
    credential = AzureCliCredential(subscription=str(cli.config.subscription_id))
    deadline = time.monotonic() + 1800
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            token = credential.get_token("https://management.azure.com/.default").token
            response = client.post(
                resource,
                params={"api-version": SQL_API},
                headers={"Authorization": f"Bearer {token}"},
            )
            write_json(
                cli.output / "local-failover-accepted.json",
                {
                    "utc": utc_now(),
                    "status_code": response.status_code,
                },
            )
            response.raise_for_status()
            if response.status_code == 200:
                return
            async_status = response.headers.get("Azure-AsyncOperation")
            poll_url = async_status or response.headers.get("Location")
            if response.status_code != 202 or not poll_url:
                raise OperationError(
                    "Failover returned no usable long-running-operation status URL."
                )
            parsed = httpx.URL(poll_url)
            if parsed.scheme != "https" or parsed.host != "management.azure.com":
                raise OperationError(
                    "Unexpected failover polling origin; refusing credential forwarding."
                )
            while time.monotonic() < deadline:
                time.sleep(10)
                token = credential.get_token("https://management.azure.com/.default").token
                response = client.get(poll_url, headers={"Authorization": f"Bearer {token}"})
                response.raise_for_status()
                if response.status_code == 204:
                    return
                try:
                    payload = response.json() if response.content else {}
                except ValueError as exc:
                    raise OperationError("Failover polling returned invalid JSON.") from exc
                if not isinstance(payload, dict):
                    raise OperationError("Failover polling returned an unexpected response shape.")
                write_json(
                    cli.output / "local-failover-poll.json",
                    {
                        "utc": utc_now(),
                        "status_code": response.status_code,
                        "response": payload,
                    },
                )
                status = payload.get("status", payload.get("properties", {}).get("status"))
                if status == "Succeeded" or (
                    not async_status and response.status_code == 200 and not payload
                ):
                    return
                if status in {"Failed", "Canceled", "Cancelled"}:
                    raise OperationError(
                        "Local failover operation failed; inspect the private record."
                    )
                if status not in {"Accepted", "Running", "InProgress", "Queued"}:
                    raise OperationError(
                        "Failover polling returned an unrecognized operation state."
                    )
    finally:
        credential.close()
    raise OperationError("Failover polling timed out; remote operation may still be in progress.")


def restore(cli: AzureCLI, args: argparse.Namespace) -> None:
    cli.require_poc()
    if not args.restore_time:
        raise OperationError("Supply --restore-time UTC from within the database retention window.")
    try:
        point = datetime.fromisoformat(args.restore_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationError("Restore time must be a valid ISO-8601 UTC timestamp.") from exc
    if point.tzinfo is None or point.utcoffset() != UTC.utcoffset(point):
        raise OperationError("Restore timestamp must explicitly use UTC (Z or +00:00).")
    source = cli.run("sql", "db", "show", *cli.config.sql_args())
    earliest = datetime.fromisoformat(source["earliestRestoreDate"].replace("Z", "+00:00"))
    if not earliest <= point < datetime.now(UTC):
        raise OperationError("Restore timestamp must be between earliestRestoreDate and now.")
    destination = f"poc-restore-{uuid4().hex[:12]}"
    started = utc_now()
    restored = cli.run(
        "sql",
        "db",
        "restore",
        *cli.config.sql_args(),
        "--dest-name",
        destination,
        "--time",
        point.strftime("%Y-%m-%dT%H:%M:%S"),
        "--edition",
        "GeneralPurpose",
        "--family",
        "Gen5",
        "--capacity",
        "2",
        "--compute-model",
        "Provisioned",
        "--tags",
        "poc=sql-vcore",
        "environment=poc",
        "purpose=restore-validation",
    )
    write_json(
        cli.output / "restore-operation.json",
        {
            "started_utc": started,
            "ended_utc": utc_now(),
            "restored": restored,
            "restore_time": point.isoformat(),
            "original_database_unchanged": True,
            "consistency_validation": "Not demonstrated by this POC run.",
            "next_step": "Use sql/restore-validation/validate.sql against the restored database.",
            "cleanup": (
                "destroy --restore-database <destination> --confirm-poc --allow-destructive-tests"
            ),
        },
    )


def price_inputs(cli: AzureCLI) -> None:
    query = (
        f"armRegionName eq '{cli.config.region}' and priceType eq 'Consumption' "
        "and (serviceName eq 'SQL Database' or serviceName eq 'Azure Container Apps' "
        "or serviceName eq 'Container Registry' or serviceName eq 'Azure Monitor' "
        "or serviceName eq 'Log Analytics' or serviceName eq 'Storage' "
        "or serviceName eq 'Virtual Network')"
    )
    rows = []
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        url = "https://prices.azure.com/api/retail/prices"
        params: dict[str, str] | None = {"$filter": query, "currencyCode": "USD"}
        for _ in range(100):
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload["Items"])
            next_url = payload.get("NextPageLink")
            if not next_url:
                break
            try:
                next_page = httpx.URL(next_url)
            except (httpx.InvalidURL, TypeError) as exc:
                raise OperationError("Invalid retail-price pagination URL.") from exc
            if (
                next_page.scheme != "https"
                or next_page.host != "prices.azure.com"
                or next_page.port not in {None, 443}
                or next_page.userinfo
                or next_page.fragment
                or next_page.path != "/api/retail/prices"
            ):
                raise OperationError("Unexpected retail-price pagination origin.")
            url, params = str(next_page), None
        else:
            raise OperationError("Retail-price pagination exceeded the safety limit.")
    if not rows:
        raise OperationError(
            "No retail price candidates were returned; cost inputs are unavailable."
        )
    write_json(
        cli.output / "cost-inputs.json",
        {
            "retrieved_utc": utc_now(),
            "currency": "USD",
            "region": cli.config.region,
            "service_tier": "GeneralPurpose",
            "compute_tier": cli.config.sql_compute_tier,
            "vcore_maximum": cli.config.sql_vcores,
            "vcore_minimum": (
                cli.config.sql_min_vcores if cli.config.sql_compute_tier == "Serverless" else None
            ),
            "auto_pause_delay_minutes": cli.config.sql_auto_pause_delay,
            "storage_cap_gb": cli.config.sql_max_size_gb,
            "backup_storage_redundancy": cli.config.sql_backup_redundancy,
            "zone_redundancy": cli.config.sql_zone_redundant,
            "disaster_recovery_enabled": cli.config.enable_dr,
            "active_hours": None,
            "idle_hours": None,
            "backup_retention_days": None,
            "monitoring_retention_days": None,
            "retail_candidates": rows,
            "measured_cost": None,
            "instructions": (
                "Retail estimates are planning inputs and are not the customer's final contracted "
                "price. Null usage/retention inputs must be supplied before estimating. "
                "Select exact paid SKU/meter/product/date; do not sum duplicate or Free rows. "
                "Provisioned SQL SKU rate already includes SKU vCore count. "
                "Serverless app_cpu_billed Total is vCore-seconds: divide by 3600 "
                "then multiply by selected paid vCore-hour price. Include storage, backups, "
                "logs, private endpoints, builds, jobs and app compute separately. "
                "Contract discounts and actual billing are not inferred."
            ),
        },
    )


def destroy(cli: AzureCLI, args: argparse.Namespace) -> None:
    if not args.allow_destructive_tests:
        raise OperationError("Deletion requires --confirm-poc AND --allow-destructive-tests.")
    cli.require_poc(database=False)
    if args.restore_database:
        if not args.restore_database.startswith("poc-restore-"):
            raise OperationError("Only generated poc-restore-* destinations can be deleted here.")
        resource = cli.run(
            "sql",
            "db",
            "show",
            "-g",
            cli.config.resource_group,
            "-s",
            cli.config.sql_server,
            "-n",
            args.restore_database,
        )
        require_tags(resource)
        if resource.get("tags", {}).get("purpose") != "restore-validation":
            raise OperationError("Restore-validation purpose tag missing.")
        cli.run(
            "sql",
            "db",
            "delete",
            "-g",
            cli.config.resource_group,
            "-s",
            cli.config.sql_server,
            "-n",
            args.restore_database,
            "--yes",
        )
    else:
        resources = cli.run("resource", "list", "-g", cli.config.resource_group)
        for resource in resources:
            # Untagged child resources can be template-generated, but an untagged
            # independently billable top-level resource must never be silently removed.
            if str(resource.get("type", "")).count("/") == 1:
                require_tags(resource)
        write_json(cli.output / "destroy-inventory.json", resources)
        cli.run("group", "delete", "--name", cli.config.resource_group, "--yes")
        if cli.run("group", "exists", "--name", cli.config.resource_group):
            raise OperationError("Resource group still exists after delete returned.")
    write_json(cli.output / "destroy-result.json", {"utc": utc_now(), "verified_deleted": True})


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Guarded Azure SQL POC operations; never a production tool."
    )
    commands = root.add_subparsers(dest="command", required=True)
    for name in (
        "deploy",
        "bootstrap",
        "smoke",
        "scale",
        "switch-compute-tier",
        "failover-test",
        "restore-test",
        "destroy",
        "capabilities",
        "price-inputs",
    ):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True, type=Path)
        command.add_argument("--confirm-poc", action="store_true")
        if name == "deploy":
            command.add_argument("--what-if-only", action="store_true")
        if name in {"scale", "switch-compute-tier"}:
            command.add_argument("--vcores", type=int, choices=[2, 4], default=2)
            command.add_argument(
                "--compute-tier",
                choices=["Provisioned", "Serverless"],
                default="Provisioned" if name == "scale" else "Serverless",
            )
            command.add_argument("--min-vcores", type=float, default=0.5)
            command.add_argument("--max-vcores", type=int, choices=[4], default=4)
            command.add_argument("--auto-pause-delay", type=int, default=-1)
        if name in {"failover-test", "destroy"}:
            command.add_argument("--allow-destructive-tests", action="store_true")
        if name == "failover-test":
            command.add_argument("--geo", action="store_true")
            command.add_argument("--failback", action="store_true")
            command.add_argument("--allow-data-loss", action="store_true")
        if name == "restore-test":
            command.add_argument("--restore-time")
        if name == "destroy":
            command.add_argument("--restore-database")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    output = output_directory(args.command)
    try:
        read_only = args.command in {"capabilities", "price-inputs"} or (
            args.command == "deploy" and args.what_if_only
        )
        if not read_only and not args.confirm_poc:
            raise OperationError(
                "Mutations require --confirm-poc; use a disposable tagged POC only."
            )
        config = load_config(args.config)
        cli = AzureCLI(config, output)
        if args.command == "deploy":
            deploy(cli, args.config, what_if_only=args.what_if_only)
        elif args.command == "bootstrap":
            cli.require_poc()
            start_job(cli, config.init_job)
        elif args.command == "smoke":
            launch_smoke(cli, confirm_poc=args.confirm_poc)
        elif args.command in {"scale", "switch-compute-tier"}:
            vcores = args.max_vcores if args.compute_tier == "Serverless" else args.vcores
            change_compute(
                cli,
                tier=args.compute_tier,
                vcores=vcores,
                minimum=args.min_vcores,
                pause=args.auto_pause_delay,
            )
            config.sql_compute_tier = args.compute_tier
            config.sql_vcores = vcores
            config.sql_min_vcores = args.min_vcores
            config.sql_auto_pause_delay = args.auto_pause_delay
            write_json(args.config, config.model_dump(mode="json"))
        elif args.command == "failover-test":
            failover(cli, args)
        elif args.command == "restore-test":
            restore(cli, args)
        elif args.command == "destroy":
            destroy(cli, args)
        elif args.command == "capabilities":
            check_capabilities(
                cli,
                config.sql_compute_tier,
                config.sql_vcores,
                config.sql_min_vcores,
                config.sql_auto_pause_delay,
            )
        elif args.command == "price-inputs":
            price_inputs(cli)
    except (OperationError, httpx.HTTPError, AzureError, ValidationError, OSError) as exc:
        message = (
            str(exc)
            if isinstance(exc, OperationError)
            else (f"Operation failed ({type(exc).__name__}); no success result was generated.")
        )
        write_json(output / "operation-failure.json", {"utc": utc_now(), "error": message})
        print(message, file=sys.stderr)
        print(f"Private evidence: {output.relative_to(ROOT)}", file=sys.stderr)
        return 1
    write_json(
        output / "operation-result.json",
        {
            "utc": utc_now(),
            "command": args.command,
            "status": "completed",
        },
    )
    print(json.dumps({"status": "completed", "private_evidence": str(output.relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
