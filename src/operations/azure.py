from __future__ import annotations

import json
import math
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "results" / "local-untracked-runs"
SQL_API = "2023-08-01"
POC_TAGS = {"poc": "sql-vcore", "environment": "poc"}


class OperationError(RuntimeError):
    """A safely printable operator error; raw diagnostics stay in ignored files."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


class DeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: UUID
    resource_group: str = Field(pattern=r"^rg-[a-z0-9-]{3,55}$")
    environment_name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,18}[a-z0-9]$")
    region: str = Field(pattern=r"^[a-z0-9]+$")
    deployment_profile: Literal["secure", "evaluation"] = "secure"
    allow_evaluation_public_access: bool = False
    evaluation_ip: str = ""
    sql_server: str = ""
    database: str = ""
    app_name: str = ""
    app_url: str = ""
    runner_job: str = ""
    init_job: str = ""
    workspace_id: str = ""
    workspace_resource_id: str = ""
    registry_name: str = ""
    registry_login_server: str = ""
    bootstrap_client_id: str = ""
    runtime_client_id: str = ""
    runtime_object_id: str = ""
    evidence_storage_account: str = ""
    evidence_storage_container: str = ""
    sql_compute_tier: Literal["Provisioned", "Serverless"] = "Provisioned"
    sql_vcores: Literal[2, 4] = 2
    sql_min_vcores: float = Field(default=0.5, ge=0.5, le=4)
    sql_auto_pause_delay: int = -1
    sql_max_size_gb: int = Field(default=5, ge=1, le=32)
    sql_zone_redundant: bool = False
    sql_backup_redundancy: Literal["Local", "Zone", "Geo", "GeoZone"] = "Local"
    enable_dr: bool = False
    enable_business_critical: bool = False
    enable_legacy_redis: bool = False
    enable_sql_diagnostics: bool = False
    enable_alerts: bool = False
    alert_action_group_ids: list[str] = Field(default_factory=list)
    alert_owner: str = "TBD"
    alert_runbook_base_url: str = ""
    alert_thresholds: dict[str, float] = Field(default_factory=dict)
    secondary_location: str = ""
    secondary_server: str = ""
    failover_group: str = ""
    image: str = ""

    @field_validator("evaluation_ip")
    @classmethod
    def exact_ip(cls, value: str) -> str:
        from ipaddress import IPv4Address

        if value:
            address = IPv4Address(value)
            if not address.is_global:
                raise ValueError("Evaluation requires an exact public IPv4 address, not a CIDR.")
        return value

    @model_validator(mode="after")
    def validate_profile(self) -> DeploymentConfig:
        if self.enable_alerts and (
            not self.alert_action_group_ids
            or self.alert_owner == "TBD"
            or not self.alert_runbook_base_url.startswith("https://")
        ):
            raise ValueError("Enabling alerts requires an owner, action group and HTTPS runbook.")
        supported_thresholds = {
            "cpu",
            "dataIo",
            "logIo",
            "workers",
            "sessions",
            "failedConnections",
            "deadlocks",
            "storage",
            "serverlessCpu",
            "p95Milliseconds",
            "errorPercent",
            "retryPercent",
            "minimumRequests",
        }
        if self.alert_thresholds.keys() - supported_thresholds or any(
            not math.isfinite(value) or value < 0 for value in self.alert_thresholds.values()
        ):
            raise ValueError("Alert thresholds must be recognized, nonnegative signal values.")
        percentages = {
            "cpu",
            "dataIo",
            "logIo",
            "workers",
            "sessions",
            "storage",
            "serverlessCpu",
            "errorPercent",
            "retryPercent",
        }
        if any(self.alert_thresholds.get(key, 0) > 100 for key in percentages):
            raise ValueError("Percentage alert thresholds cannot exceed 100.")
        if self.alert_thresholds.get("minimumRequests", 100) < 1:
            raise ValueError("Alert minimumRequests must be at least one.")
        if self.enable_business_critical and self.sql_compute_tier != "Provisioned":
            raise ValueError("The optional Business Critical extension is provisioned only.")
        if self.deployment_profile == "evaluation" and (
            not self.allow_evaluation_public_access or not self.evaluation_ip
        ):
            raise ValueError("Evaluation public networking requires opt-in and one caller IPv4.")
        if self.deployment_profile == "secure" and (
            self.allow_evaluation_public_access or self.evaluation_ip
        ):
            raise ValueError("Secure deployment must not include public-access settings.")
        if self.enable_dr and (
            not self.secondary_location or self.secondary_location == self.region
        ):
            raise ValueError("DR requires a distinct explicit secondary region.")
        if self.enable_dr and self.sql_auto_pause_delay != -1:
            raise ValueError("Failover groups are incompatible with serverless auto-pause.")
        if self.sql_compute_tier == "Serverless" and self.sql_vcores != 4:
            raise ValueError("This comparison uses serverless maximum 4 vCores.")
        if self.sql_min_vcores > self.sql_vcores:
            raise ValueError("Minimum vCores must not exceed maximum.")
        if self.sql_auto_pause_delay != -1 and self.sql_auto_pause_delay <= 0:
            raise ValueError("Auto-pause delay must be -1 or a positive supported duration.")
        return self

    def require_database(self) -> None:
        if not self.sql_server or not self.database:
            raise OperationError(
                "Run deployment first; SQL server and database outputs are missing."
            )

    @property
    def database_id(self) -> str:
        self.require_database()
        return (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.Sql/servers/{self.sql_server}/databases/{self.database}"
        )

    def sql_args(self, server: str | None = None) -> list[str]:
        self.require_database()
        return [
            "--resource-group",
            self.resource_group,
            "--server",
            server or self.sql_server,
            "--name",
            self.database,
        ]


def load_config(path: Path) -> DeploymentConfig:
    path = path.resolve()
    # Deployment outputs contain identifiers; enforce the same boundary on reads and writes.
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if ignored.returncode != 0 or path.suffix != ".json":
        raise OperationError(
            "Config must be an ignored local JSON file, e.g. deployment.local.json."
        )
    try:
        return DeploymentConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OperationError(
            "Invalid local deployment configuration. Compare keys and types with the example."
        ) from exc


class AzureCLI:
    def __init__(self, config: DeploymentConfig, output: Path) -> None:
        executable = shutil.which("az")
        if not executable:
            raise OperationError("Azure CLI is required; install it and run az login.")
        self.executable = executable
        self.config = config
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.sequence = 0
        self.redactions: list[str] = []

    def redact(self, value: str) -> str:
        for secret in self.redactions:
            value = value.replace(secret, "[REDACTED]")
        return value

    def run(self, *args: str, timeout: int = 3600) -> Any:
        self.sequence += 1
        command = [
            self.executable,
            *args,
            "--subscription",
            str(self.config.subscription_id),
            "--only-show-errors",
            "--output",
            "json",
        ]
        started = utc_now()
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            write_json(
                self.output / f"cli-{self.sequence:03}-timeout.json",
                {
                    "command": [self.redact(arg) for arg in args],
                    "started_utc": started,
                    "timeout_seconds": timeout,
                    "outcome": "client_timeout",
                    "remote_operation_may_continue": True,
                },
            )
            raise OperationError(
                "Azure CLI timed out; inspect Azure operation status before retrying."
            ) from exc
        write_json(
            self.output / f"cli-{self.sequence:03}.json",
            {
                "command": [self.redact(arg) for arg in args],
                "started_utc": started,
                "ended_utc": utc_now(),
                "exit_code": completed.returncode,
                "stdout": self.redact(completed.stdout),
                "stderr": self.redact(completed.stderr),
            },
        )
        if completed.returncode:
            raise OperationError(
                f"Azure CLI operation failed (exit {completed.returncode}); "
                f"private diagnostic record cli-{self.sequence:03}.json."
            )
        if not completed.stdout.strip():
            return None
        try:
            return json.loads(self.redact(completed.stdout))
        except json.JSONDecodeError as exc:
            raise OperationError(
                "Azure CLI returned invalid JSON; inspect the private record."
            ) from exc

    def rest(self, method: str, resource: str, *, body: Path | None = None) -> Any:
        args = ["rest", "--method", method, "--url", resource]
        if body:
            args += ["--body", f"@{body}"]
        return self.run(*args)

    def require_poc(self, *, database: bool = True) -> None:
        group = self.run("group", "show", "--name", self.config.resource_group)
        require_tags(group)
        if database:
            require_tags(self.run("sql", "db", "show", *self.config.sql_args()))


def require_tags(resource: dict[str, Any]) -> None:
    tags = resource.get("tags") or {}
    if any(tags.get(key) != value for key, value in POC_TAGS.items()):
        raise OperationError(
            "Refusing operation: exact poc=sql-vcore and environment=poc tags required."
        )


def capability_options(
    data: dict[str, Any], edition_name: str = "GeneralPurpose"
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for version in data.get("supportedServerVersions", []):
        if version.get("name") != "12.0":
            continue
        for edition in version.get("supportedEditions", []):
            if edition.get("name") == edition_name:
                options.extend(edition.get("supportedServiceLevelObjectives", []))
    return options


def validate_capability(
    data: dict[str, Any],
    tier: str,
    vcores: int,
    minimum: float,
    pause: int,
    zone_redundant: bool = False,
    edition: str = "GeneralPurpose",
) -> dict[str, Any]:
    prefix = "BC" if edition == "BusinessCritical" else "GP"
    name = f"{prefix}_{'S_' if tier == 'Serverless' else ''}Gen5_{vcores}"
    candidates = [item for item in capability_options(data, edition) if item.get("name") == name]
    usable = [item for item in candidates if item.get("status") in {"Available", "Default"}]
    if not usable:
        raise OperationError(f"{name} is not available in this subscription/region.")
    selected = usable[0]
    if zone_redundant and selected.get("zoneRedundant") is not True:
        raise OperationError(
            "Zone redundancy is not advertised for the selected compute configuration."
        )
    if tier == "Serverless":
        minima = selected.get("supportedMinCapacities", [])
        if not any(
            float(item.get("value", -1)) == minimum
            and item.get("status", "Available") in {"Available", "Default"}
            for item in minima
        ):
            raise OperationError("The requested serverless minimum is not supported.")
        if pause != -1:
            delays = selected.get("supportedAutoPauseDelay", {})
            if not delays or not delays.get("minValue", 0) <= pause <= delays.get("maxValue", -1):
                raise OperationError("The requested auto-pause delay is outside advertised limits.")
    return selected


def check_capabilities(
    cli: AzureCLI,
    tier: str,
    vcores: int,
    minimum: float,
    pause: int,
) -> dict[str, Any]:
    config = cli.config
    data = cli.rest(
        "get",
        f"https://management.azure.com/subscriptions/{config.subscription_id}"
        f"/providers/Microsoft.Sql/locations/{config.region}/capabilities?api-version={SQL_API}",
    )
    selected = validate_capability(
        data,
        tier,
        vcores,
        minimum,
        pause,
        config.sql_zone_redundant,
        "BusinessCritical" if config.enable_business_critical else "GeneralPurpose",
    )
    write_json(cli.output / "selected-capability.json", selected)
    return selected


def wait_database(cli: AzureCLI, expected: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    deadline = time.monotonic() + 3600
    observations = []
    while time.monotonic() < deadline:
        database = cli.run("sql", "db", "show", *cli.config.sql_args())
        observations.append({"utc": utc_now(), "database": database})
        write_json(cli.output / "database-observations.json", observations)
        if expected(database):
            return dict(database)
        time.sleep(15)
    raise OperationError("Database did not reach the requested state within 60 minutes.")


def change_compute(
    cli: AzureCLI,
    *,
    tier: str,
    vcores: int,
    minimum: float,
    pause: int,
) -> dict[str, Any]:
    if tier not in {"Provisioned", "Serverless"} or vcores not in {2, 4}:
        raise OperationError(
            "Only the GP provisioned 2/4 and serverless max-4 comparisons are allowed."
        )
    if tier == "Serverless" and (vcores != 4 or not 0.5 <= minimum <= vcores):
        raise OperationError("Serverless requires max 4 and a supported minimum no greater than 4.")
    if tier == "Provisioned" and pause != -1:
        raise OperationError("Provisioned compute does not support auto-pause.")
    if cli.config.enable_business_critical:
        raise OperationError(
            "Standard comparison operations are General Purpose only. "
            "Disable the explicit Business Critical extension and redeploy first."
        )
    cli.require_poc()
    config = cli.config
    check_capabilities(cli, tier, vcores, minimum, pause)
    if pause != -1:
        groups = cli.run(
            "sql",
            "failover-group",
            "list",
            "-g",
            config.resource_group,
            "-s",
            config.sql_server,
        )
        if any(
            config.database_id.lower()
            in {str(database).lower() for database in group.get("databases", [])}
            for group in groups
        ):
            raise OperationError("Disable/remove geo-replication before enabling auto-pause.")
        links = cli.run("sql", "db", "replica", "list-links", *config.sql_args())
        if links:
            raise OperationError("Geo-replication links prevent auto-pause.")
        retention = cli.run("sql", "db", "ltr-policy", "show", *config.sql_args())
        if any(
            retention.get(key) not in {None, "", "PT0S", "P0W", "P0M", "P0Y"}
            for key in ("weeklyRetention", "monthlyRetention", "yearlyRetention")
        ):
            raise OperationError("Long-term retention must be disabled before auto-pause.")
    before = cli.run("sql", "db", "show", *config.sql_args())
    write_json(cli.output / "compute-before.json", before)
    args = [
        "sql",
        "db",
        "update",
        *config.sql_args(),
        "--edition",
        "GeneralPurpose",
        "--family",
        "Gen5",
        "--capacity",
        str(vcores),
        "--compute-model",
        tier,
    ]
    if tier == "Serverless":
        args += ["--min-capacity", str(minimum), "--auto-pause-delay", str(pause)]
    started = utc_now()
    cli.run(*args)
    after = wait_database(
        cli,
        lambda db: (
            db.get("status") == "Online"
            and db.get("sku", {}).get("capacity") == vcores
            and db.get("currentServiceObjectiveName")
            == (f"GP_{'S_' if tier == 'Serverless' else ''}Gen5_{vcores}")
            and (
                tier != "Serverless"
                or (db.get("minCapacity") == minimum and db.get("autoPauseDelay") == pause)
            )
        ),
    )
    result = {"started_utc": started, "ended_utc": utc_now(), "before": before, "after": after}
    write_json(cli.output / "compute-change.json", result)
    return result


def start_job(cli: AzureCLI, name: str, *, wait: bool = True) -> dict[str, Any]:
    if not name:
        raise OperationError("Job name missing from deployment outputs.")
    require_tags(
        cli.run("containerapp", "job", "show", "-g", cli.config.resource_group, "-n", name)
    )
    execution = cli.run(
        "containerapp",
        "job",
        "start",
        "-g",
        cli.config.resource_group,
        "-n",
        name,
    )
    write_json(cli.output / "job-start.json", execution)
    if not wait:
        return dict(execution)
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        executions = cli.run(
            "containerapp",
            "job",
            "execution",
            "list",
            "-g",
            cli.config.resource_group,
            "-n",
            name,
        )
        for current in executions:
            if current.get("name") != execution["name"]:
                continue
            status = current.get("properties", {}).get("status")
            write_json(cli.output / "job-execution.json", current)
            if status == "Succeeded":
                return dict(current)
            if status in {"Failed", "Stopped", "Degraded"}:
                raise OperationError(
                    f"Container Apps job ended with {status}; inspect its private logs."
                )
        time.sleep(10)
    raise OperationError(
        "Job wait exceeded 30 minutes. Job may still run; inspect before restarting."
    )


def output_directory(operation: str) -> Path:
    directory = RAW / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{operation}-{uuid4().hex[:8]}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory
