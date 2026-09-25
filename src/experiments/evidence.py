from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.experiments.common import (
    ARTIFACTS,
    NOT_DEMONSTRATED,
    read_json,
    safe_main,
    utc_now,
    write_json,
)
from src.experiments.outcomes import OUTCOMES, summarize

METRICS = {
    "cpu_percent": "gauge",
    "physical_data_read_percent": "gauge",
    "log_write_percent": "gauge",
    "workers_percent": "gauge",
    "sessions_percent": "gauge",
    "connection_successful": "count",
    "connection_failed": "count",
    "deadlock": "count",
    "storage": "gauge",
    "storage_percent": "gauge",
    "availability": "gauge",
    "app_cpu_percent": "gauge",
    "app_cpu_billed": "count",
}
TABLES = {
    "AppRequests",
    "AppDependencies",
    "AppTraces",
    "AzureMetrics",
    "AzureDiagnostics",
    "AzureActivity",
    "ContainerAppConsoleLogs_CL",
}
ATTEMPT_FIELDS = {
    "test_run_id",
    "correlation_id",
    "operation",
    "timestamp",
    "attempt",
    "error_category",
    "error_code",
    "retry_decision",
    "retry_delay_ms",
    "final_result",
    "elapsed_ms",
    "database_target_role",
    "retry_count",
    "dependency_ms",
    "db_calls",
    "pool_wait_ms",
    "cache_hit",
    "event",
}


def initialize(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in ARTIFACTS:
        path = directory / name
        if path.exists():
            continue
        if name.endswith(".json"):
            write_json(path, {"status": NOT_DEMONSTRATED, "value": None})
        else:
            path.write_text(f"# {name[:-3]}\n\n{NOT_DEMONSTRATED}\n", encoding="utf-8")


def metric_summary(payload: dict[str, Any], aggregation: str) -> float | None:
    values = [
        float(point[aggregation.lower()])
        for metric in payload.get("value", [])
        for series in metric.get("timeseries", [])
        for point in series.get("data", [])
        if isinstance(point.get(aggregation.lower()), (float, int))
    ]
    if not values:
        return None
    if aggregation == "Total":
        return sum(values)
    if aggregation == "Maximum":
        return max(values)
    return sum(values) / len(values)


def collect_metrics(config: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    from src.experiments.cloud_evidence import Settings, connection, metrics

    with connection(Settings.from_config(config)) as api:
        return metrics(api, start, end)


def counter_delta(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scope": "process-wide window delta; not attributed exclusively to the test-run ID",
        "run_local_counts": None,
        "counts": None,
        "maximum_pool_utilization": None,
        "status": NOT_DEMONSTRATED,
    }
    if before is None or after is None:
        return result
    if before.get("instance_id") != after.get("instance_id"):
        result["status"] = "different application processes; delta unavailable"
        return result
    result["start_snapshot"] = before
    left, right = before.get("counts", {}), after.get("counts", {})
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError("Invalid counter snapshots")
    if any(right.get(key, 0) < value for key, value in left.items()):
        result["status"] = "counter reset; delta unavailable"
        return result
    result["counts"] = {key: value - left.get(key, 0) for key, value in right.items()}
    result["status"] = "measured"
    result["end_snapshot"] = after
    return result


def import_attempts(path: Path, run_id: str) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError("Attempt telemetry must contain JSON objects")
        if event.get("test_run_id") == run_id and event.get("event") == "operation_attempt":
            attempts.append({key: value for key, value in event.items() if key in ATTEMPT_FIELDS})
    return attempts


def collect_logs(
    config: dict[str, Any],
    tables: list[str],
    start: str,
    end: str,
    run_id: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", run_id):
        raise ValueError("Unsafe test-run identifier in manifest")
    for timestamp in (start, end):
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        offset = parsed.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("Evidence window must be UTC")
    for table in tables:
        if table not in TABLES:
            raise ValueError("Unsupported monitoring table")
    from src.experiments.cloud_evidence import Settings, connection, logs

    with connection(Settings.from_config(config)) as api:
        return logs(api, start, end, run_id, tables=tables)


def retail_inputs(
    payload: dict[str, Any], selection: dict[str, str] | None = None
) -> dict[str, Any]:
    rows = payload.get("retail_candidates", [])
    paid = [
        row
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("retailPrice"), (int, float))
        and row["retailPrice"] > 0
        and "free" not in str(row.get("skuName", "")).lower()
        and "free" not in str(row.get("meterName", "")).lower()
    ]
    chosen = [
        row
        for row in paid
        if selection and all(str(row.get(key)) == value for key, value in selection.items())
    ]
    return {
        **payload,
        "paid_candidates": paid,
        "selected": chosen[0] if len(chosen) == 1 else None,
        "requires_selection": len(chosen) != 1,
        "selection_status": "selected" if len(chosen) == 1 else "ambiguous or not selected",
        "estimated_compute_cost": None,
        "estimated_storage_cost": None,
        "monitoring_cost": None,
        "price_notice": "Retail estimates are planning inputs and are not the customer's final "
        "contracted price.",
    }


def finalize(
    directory: Path,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = read_json(directory / "manifest.json")
    requests_path = directory / "requests.jsonl"
    events = (
        [
            json.loads(line)
            for line in requests_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if requests_path.exists()
        else []
    )
    schedule_path = directory / "schedule.json"
    schedule = read_json(schedule_path) if schedule_path.exists() else {}
    elapsed = schedule.get("measurement_seconds", 0)
    summary = summarize(events, elapsed)
    summary.update(
        {
            "requested_rate_rps": manifest["profile"]["rate"],
            "requested_requests": manifest["volume_model"]["scheduled_http_requests"],
            "achieved_rate_rps": summary["throughput_rps"],
            "missed_schedule_slots": schedule.get("missed_schedule_slots"),
            "schedule_deficit": max(
                0,
                manifest["volume_model"]["scheduled_http_requests"] - len(events),
            ),
            "measurement_seconds": elapsed,
            "sql_read_queries": None,
            "limitations": [
                "Finite clients cannot maintain offered rate after concurrency is exhausted.",
                "Missed arrivals are not retried; latency percentiles exclude unsent requests.",
                "Coordinated omission can understate latency; inspect schedule deficit "
                "and achieved rate.",
                "Accelerated traffic does not reproduce a full day of TTLs, background "
                "jobs or idle time.",
                "HTTP read requests are not SQL read query counts.",
            ],
        }
    )
    write_json(directory / "workload-summary.json", summary)
    application = counter_delta(before, after)
    application["client_observations"] = summary
    application["test_run_id"] = manifest["test_run_id"]
    write_json(directory / "application-metrics.json", application)
    write_json(
        directory / "error-summary.json",
        {
            "outcomes": summary["outcomes"],
            "failed_operations": [
                event for event in events if event["outcome"] not in OUTCOMES[:2]
            ],
        },
    )
    write_json(
        directory / "retry-summary.json",
        {
            "retried_request_count": summary["retried_request_count"],
            "retry_coverage": summary["retry_coverage"],
            "attempts": None,
            "attempt_status": NOT_DEMONSTRATED,
            "retried_operations": [event for event in events if event.get("retry_count")],
        },
    )
    observations = (
        "# Measured results\n\n"
        f"- Requests: {summary['request_count']}\n"
        f"- Throughput (requests/s): {summary['throughput_rps']}\n"
        f"- p50/p95/p99 (ms): {summary['p50_ms']} / {summary['p95_ms']} / {summary['p99_ms']}\n"
        f"- Failed requests: {summary['failed_request_count']}\n\n"
        "## Remaining unknowns\n\n"
        f"SQL throttling, allocated vCores, tuning benefit and cost winner: {NOT_DEMONSTRATED}\n\n"
        "## Limitations\n\n"
        + "\n".join(f"- {item}" for item in summary["limitations"])
        + "\n\n## Estimated cost\n\nRetail estimates are planning inputs and are not the "
        "customer's final contracted price. See cost-inputs.json.\n\n"
        "## Product documentation\n\n"
        "https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview\n\n"
        "## General guidance\n\nCompare identical profile hashes and inspect all signals.\n\n"
        "## Recommendation\n\nMore testing required; no automatic sizing recommendation.\n"
    )
    (directory / "observations.md").write_text(observations, encoding="utf-8")
    (directory / "executive-summary.md").write_text(
        "# Executive summary\n\nMeasured results are in workload-summary.json.\n\n"
        "Recommendation: More testing required.\n\n"
        f"Customer response-time objective, RTO and RPO: TBD. Cost winner: {NOT_DEMONSTRATED}\n",
        encoding="utf-8",
    )
    return summary


def collect(
    directory: Path,
    config_path: Path | None = None,
    attempts_path: Path | None = None,
    query_store_path: Path | None = None,
    tables: list[str] | None = None,
    skip_sql: bool = False,
    cloud_rest: bool = False,
) -> None:
    initialize(directory)
    manifest = read_json(directory / "manifest.json")
    if cloud_rest or config_path is not None or os.environ.get("SQL_RESOURCE_ID"):
        from src.experiments.cloud_evidence import collect as collect_cloud_rest

        collect_cloud_rest(
            directory,
            config=read_json(config_path) if config_path else None,
            skip_sql=skip_sql,
            include_query_store=query_store_path is None,
            tables=tables or None,
        )
    elif attempts_path is None and query_store_path is None:
        raise ValueError(
            "No evidence source configured; supply cloud environment, config or imports"
        )
    if attempts_path:
        retry = read_json(directory / "retry-summary.json")
        retry["attempts"] = import_attempts(attempts_path, manifest["test_run_id"])
        retry["attempt_status"] = "imported; completeness not independently verified"
        write_json(directory / "retry-summary.json", retry)
    if query_store_path:
        write_json(
            directory / "query-store-summary.json",
            {
                "status": "operator-provided; window alignment requires review",
                "start_utc": manifest["start_utc"],
                "end_utc": manifest["end_utc"],
                "summary": read_json(query_store_path),
            },
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect real evidence for an existing UTC run window"
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--attempts", type=Path)
    parser.add_argument("--query-store", type=Path)
    parser.add_argument("--skip-sql", action="store_true")
    parser.add_argument(
        "--cloud-rest",
        action="store_true",
        help="Use managed-identity REST and post-workload read-only SQL observer; "
        "SQL is omitted for idle windows or --skip-sql",
    )
    parser.add_argument("--verified-table", action="append", choices=sorted(TABLES), default=[])
    args = parser.parse_args(argv)
    from src.experiments.storage import archive_if_configured

    try:
        collect(
            args.run_dir,
            args.config,
            args.attempts,
            args.query_store,
            args.verified_table,
            args.skip_sql,
            args.cloud_rest,
        )
    finally:
        archive_if_configured(args.run_dir, args.config)
    coverage_path = args.run_dir / "collection-coverage.json"
    status = read_json(coverage_path)["status"] if coverage_path.exists() else "collected"
    print(json.dumps({"status": status, "timestamp": utc_now()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main))
