from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
NOT_DEMONSTRATED = "Not demonstrated by this POC run."
ARTIFACTS = (
    "manifest.json",
    "configuration.json",
    "workload-summary.json",
    "application-metrics.json",
    "azure-sql-metrics.json",
    "query-store-summary.json",
    "error-summary.json",
    "retry-summary.json",
    "cost-inputs.json",
    "observations.md",
    "executive-summary.md",
    "sanitization-report.json",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def command_json(args: list[str]) -> Any:
    executable = shutil.which(args[0])
    if executable is None:
        raise RuntimeError("Required external executable is not available")
    result = subprocess.run([executable, *args[1:]], capture_output=True, text=True, check=False)
    if result.returncode:
        # Tool stderr may contain deployment identifiers or authentication material.
        raise RuntimeError(f"External tool failed (exit {result.returncode}); inspect locally.")
    return json.loads(result.stdout)


def operation(name: str, config: Path, *args: str) -> Any:
    receipt = command_json(
        [
            sys.executable,
            "-m",
            "src.operations.cli",
            name,
            "--config",
            str(config),
            *args,
        ]
    )
    if isinstance(receipt, dict) and receipt.get("private_evidence"):
        directory = (ROOT / receipt["private_evidence"]).resolve()
        if not directory.is_relative_to(ROOT / "results" / "local-untracked-runs"):
            raise ValueError("Operation receipt points outside private run storage")
        if name == "price-inputs":
            return read_json(directory / "cost-inputs.json")
        operation_file = directory / f"{name.split('-test')[0]}-operation.json"
        if operation_file.exists():
            receipt["operation_evidence"] = read_json(operation_file)
    return receipt


def sql_resource_id(config: dict[str, Any]) -> str:
    return (
        f"/subscriptions/{config['subscription_id']}/resourceGroups/{config['resource_group']}"
        f"/providers/Microsoft.Sql/servers/{config['sql_server']}/databases/{config['database']}"
    )


def sql_configuration(config: dict[str, Any]) -> dict[str, Any]:
    value = command_json(
        ["az", "sql", "db", "show", "--ids", sql_resource_id(config), "-o", "json"]
    )
    if not isinstance(value, dict):
        raise ValueError("Azure CLI returned an invalid database configuration")
    return value


def numeric_header(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if 0 <= number < float("inf") else None


def safe_main(action: Callable[[], int]) -> int:
    try:
        return action()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "failure_category": type(exc).__name__,
                    "detail": "Operation failed. See local evidence; exception details withheld.",
                }
            ),
            file=sys.stderr,
        )
        return 1
