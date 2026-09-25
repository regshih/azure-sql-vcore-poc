from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import zipfile
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
from src.experiments.evidence import METRICS
from src.experiments.outcomes import OUTCOMES, SERVER_OUTCOMES
from src.experiments.scan import scan_directory

SAFE_KEYS = {
    "sql_business_request_success_count",
    "native_outcome",
    "cloud_evidence_coverage",
    "evidence_collection_status",
    "required_metrics_missing",
    "correlated_log_rows_observed",
    "measured_metric_count",
    "measured_log_table_count",
    "database_configuration_observed",
    "sql_data_plane_attempted",
    "query_store_observer_required",
    "privileges_elevated",
    "request_attempts",
    "service",
    "transport",
    "collect_cloud",
    "cloud_rest",
    "repository_backend",
    "sql_adapter_configured",
    "work_item_count",
    "counts_source",
    "tuning_mode",
    "dataset_fairness",
    "before",
    "after",
    "reset_provenance",
    "reset_result",
    "parameters",
    "generator_sha256",
    "allow_destructive_tests",
    "confirm_single_instance",
    "admission_restored",
    "synthetic_marker_checked_by_admin_transaction",
    "reference_run_id",
    "dataset_state",
    "dataset_state_fingerprint",
    "dataset_fingerprint_scope",
    "dataset_state_requires_quiescent_workload",
    "metadata_observed_at",
    "instance_id",
    "products",
    "stock_units",
    "work_items",
    "last_work_item_id",
    "work_item_total_cents",
    "work_item_lines",
    "quantities",
    "activity",
    "last_activity_id",
    "idempotency_keys",
    "aggregate_prestate_matches_reference",
    "aggregate_state_changed",
    "same_application_process",
    "reset_before_run_verified",
    "paired_deterministic_reset_verified",
    "data_state_comparison_status",
    "fair_comparison_claim_allowed",
    "full_content_equivalence",
    "observe_dataset_state",
    "application_counter_delta",
    "start_snapshot",
    "top_queries",
    "waits",
    "options",
    "rows",
    "row_count",
    "truncated",
    "sampled_utc",
    "query_id",
    "plan_id",
    "executions",
    "total_cpu_ms",
    "total_duration_ms",
    "total_logical_reads",
    "avg_cpu_ms",
    "avg_duration_ms",
    "avg_logical_reads",
    "cpu_rank",
    "avg_duration_rank",
    "total_duration_rank",
    "executions_rank",
    "logical_reads_rank",
    "total_query_wait_time_ms",
    "actual_state_desc",
    "desired_state_desc",
    "readonly_reason",
    "current_storage_size_mb",
    "max_storage_size_mb",
    "interval_length_minutes",
    "interval_overlap_may_include_out_of_window_executions",
    "capture_flush_and_retention_may_omit_recent_executions",
    "no_rows_is_not_zero",
    "empty_rows_do_not_prove_zero_activity",
    "read_only_queries",
    "collection_after_workload",
    "run_exclusive",
    "sql_text_included",
    "status",
    "value",
    "start_utc",
    "end_utc",
    "test_run_id",
    "test_id",
    "correlation_id",
    "profile_hash",
    "workload_profile",
    "profile",
    "name",
    "users",
    "spawn_rate",
    "duration",
    "rate",
    "write_ratio",
    "seed",
    "product_count",
    "request_timeout",
    "equivalent_period_seconds",
    "target_daily_reads",
    "hot_fraction",
    "hot_probability",
    "scenario",
    "connection_mode",
    "phases",
    "fraction",
    "multiplier",
    "volume_model",
    "acceleration_factor",
    "scheduled_http_requests",
    "scheduled_read_requests",
    "modeled_daily_read_requests",
    "volume_fraction_of_target",
    "application_version",
    "schema_version",
    "schema_version_observed_utc",
    "schema_version_source",
    "wait_category_desc",
    "execution_type_desc",
    "dataset_version",
    "dataset_size",
    "duration_seconds",
    "wall_duration_seconds",
    "toggles",
    "allow_unsafe_test",
    "confirm_poc",
    "controlled",
    "confirm_no_other_sql_clients",
    "idle_after",
    "cache_mode",
    "compute_tier",
    "hardware_family",
    "provisioned_vcores",
    "serverless_min_vcores",
    "serverless_max_vcores",
    "auto_pause_delay",
    "zone_redundant",
    "backup_redundancy",
    "storage_bytes",
    "locust_exit_code",
    "request_count",
    "read_request_count",
    "write_request_count",
    "successful_request_count",
    "failed_request_count",
    "retried_request_count",
    "retry_observations",
    "retry_coverage",
    "timeout_count",
    "load_shed_count",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "throughput_rps",
    "error_rate",
    "timeout_rate",
    "retry_rate",
    "cache_hit_ratio",
    "database_calls",
    "outcomes",
    "requested_rate_rps",
    "requested_requests",
    "achieved_rate_rps",
    "missed_schedule_slots",
    "issued_requests",
    "schedule_deficit",
    "measurement_seconds",
    "sql_read_queries",
    "run_local_counts",
    "counts",
    "maximum_pool_utilization",
    "maximum_pool_size",
    "maximum_pool_checked_out",
    "maximum_active_requests",
    "maximum_queue_depth",
    "sample_count",
    "sampling_interval_seconds",
    "client_observations",
    "failed_operations",
    "retried_operations",
    "attempts",
    "attempt",
    "attempt_number",
    "error_category",
    "error_code",
    "retry_decision",
    "retry_delay_ms",
    "final_result",
    "elapsed_ms",
    "retry_count",
    "db_calls",
    "cache_hit",
    "pool_wait_ms",
    "dependency_ms",
    "operation",
    "timestamp",
    "http_status",
    "database_target_role",
    "metrics",
    "aggregations",
    "Total",
    "Average",
    "Maximum",
    "unit",
    "billed_compute_vcore_seconds",
    "allocated_vcores",
    "observations",
    "pause_observed_utc",
    "resume_observed_utc",
    "first_request",
    "idle_started_utc",
    "idle_duration_seconds",
    "restoration_failure",
    "currency",
    "region",
    "armRegionName",
    "location",
    "meterId",
    "productId",
    "skuId",
    "skuName",
    "meterName",
    "productName",
    "armSkuName",
    "retailPrice",
    "unitPrice",
    "unitOfMeasure",
    "effectiveStartDate",
    "price_retrieved_utc",
    "retrieved_at",
    "retail_price",
    "unit_price",
    "candidates",
    "paid_candidates",
    "retail_candidates",
    "retrieved_utc",
    "selected",
    "requires_selection",
    "active_hours",
    "idle_hours",
    "estimated_compute_cost",
    "estimated_storage_cost",
    "monitoring_cost",
    "application",
    "database",
    "cache_requests",
    "cache_hits",
    "cache_misses",
    "requests",
    "cache_enabled",
    "readonly",
    "version",
    "poc",
    "minCapacity",
    "autoPauseDelay",
    "maxSizeBytes",
    "zoneRedundant",
    "sku",
    "family",
    "capacity",
    "tier",
    "series",
    "timeseries",
    "data",
    "timeStamp",
    "average",
    "maximum",
    "minimum",
    "total",
    "count",
    *OUTCOMES,
    *METRICS,
}
SAFE_STRINGS = {
    *SERVER_OUTCOMES,
    *METRICS,
    "measured-with-gaps",
    "incomplete",
    "managed-identity-rest",
    "arm",
    "logs",
    "metric-definitions",
    "metric-values",
    "log-schema",
    "log-count",
    "database-configuration",
    "azure-monitor-resource-metrics-and-correlated-log-counts",
    "retrying",
    "received",
    "sql",
    "dataset_seed_ledger",
    "local_memory_initialization",
    "baseline",
    "index",
    "query",
    "both",
    "aggregate_state_not_full_content",
    "non-equivalent-or-unverified",
    "matched-reset-aggregate-state",
    "reset-verified",
    "READ_WRITE",
    "READ_ONLY",
    "OFF",
    "ERROR",
    "database-migration-ledger",
    "CPU",
    "Worker Thread",
    "Lock",
    "Buffer Latch",
    "Buffer IO",
    "Compilation",
    "Network IO",
    "Memory",
    "Parallelism",
    "Log Rate Governor",
    "Log",
    "Regular",
    "Aborted",
    "Exception",
    *OUTCOMES,
    NOT_DEMONSTRATED,
    "measured",
    "running",
    "completed",
    "failed",
    "completed-with-request-errors",
    "smoke",
    "expected",
    "business-hours",
    "peak",
    "spike-1-minute",
    "spike-5-minute",
    "spike-15-minute",
    "idle-resume",
    "variable-demand",
    "connection-storm",
    "slow-query",
    "cache-comparison",
    "failover",
    "normal",
    "idle",
    "storm",
    "slow",
    "cache",
    "pooled",
    "no-reuse",
    "none",
    "disabled",
    "memory",
    "redis",
    "Provisioned",
    "Serverless",
    "GeneralPurpose",
    "General Purpose",
    "Gen5",
    "GP_Gen5",
    "GP_S_Gen5",
    "Geo",
    "Zone",
    "Local",
    "GeoZone",
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CAD",
    "Count",
    "Percent",
    "Bytes",
    "Seconds",
    "CountPerSecond",
    "Cores",
    "vCore Seconds",
    "point-lookup",
    "filtered-lookup",
    "filtered-work-items",
    "paginated-lookup",
    "dashboard",
    "recent-activity",
    "transactional-write",
    "batch-read",
    "batch-work-items",
    "primary",
    "secondary",
    "unknown",
    "pending",
    "Online",
    "Paused",
    "Pausing",
    "Resuming",
    "1 Hour",
    "1/Hour",
    "1 GB/Month",
}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+]00:00)$")
VERSION = re.compile(r"^(?:v?\d+(?:\.\d+){1,3}|[a-f0-9]{40}|[a-f0-9]{64})$")
REGION = re.compile(
    r"^(?:eastus2?|westus[23]?|centralus|northcentralus|southcentralus|westcentralus|"
    r"eastus2euap|centraluseuap|westeurope|northeurope|uksouth|ukwest|"
    r"australiaeast|australiasoutheast|australiacentral2?|brazilsouth|brazilsoutheast|"
    r"canadacentral|canadaeast|centralindia|southindia|westindia|eastasia|southeastasia|"
    r"japaneast|japanwest|koreacentral|koreasouth|francecentral|francesouth|"
    r"germanywestcentral|germanynorth|norwayeast|norwaywest|swedencentral|swedensouth|"
    r"switzerlandnorth|switzerlandwest|uaenorth|uaecentral|southafricanorth|southafricawest)$"
)


def pseudonym(value: str) -> str:
    return "poc-" + hashlib.sha256(value.encode()).hexdigest()[:20]


def sanitize_value(value: Any, key: str = "", redactions: list[str] | None = None) -> Any:
    if key in {
        "test_run_id",
        "test_id",
        "correlation_id",
        "query_id",
        "plan_id",
        "reference_run_id",
        "instance_id",
    }:
        return pseudonym(str(value)) if value is not None else None
    if key in {
        "meterId",
        "productId",
        "skuId",
        "skuName",
        "meterName",
        "productName",
        "armSkuName",
    }:
        return pseudonym(str(value)) if value is not None else None
    if isinstance(value, dict):
        return {
            name: sanitize_value(item, name, redactions)
            for name, item in value.items()
            if name in SAFE_KEYS
        }
    if isinstance(value, list):
        return [sanitize_value(item, key, redactions) for item in value]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    if redactions and any(item and item.casefold() in value.casefold() for item in redactions):
        return "[REDACTED]"
    if value in SAFE_STRINGS or DATE.fullmatch(value):
        return value
    if key in {"region", "armRegionName", "location"} and REGION.fullmatch(value):
        return value
    if key in {"dataset_state_fingerprint", "generator_sha256"}:
        return value if re.fullmatch(r"[a-f0-9]{64}", value) else None
    if key in {"application_version", "schema_version", "dataset_version", "profile_hash"}:
        if key == "schema_version" and re.fullmatch(r"\d{1,8}", value):
            return value
        if key == "dataset_version" and re.fullmatch(
            r"synthetic-v\d+(?:-seed\d+|-s\d+-p\d+-w\d+)?", value
        ):
            return value
        return value if VERSION.fullmatch(value) else None
    if key == "error_code" and re.fullmatch(r"(?:\d{1,6}|[A-Z0-9]{5}|none)", value):
        return value
    return None


def sanitize_document(name: str, value: Any, redactions: list[str] | None = None) -> Any:
    if name not in ARTIFACTS and name not in {"idle-resume.json", "matrix-plan.json"}:
        raise ValueError("Artifact is not on the publication allowlist")
    return sanitize_value(value, redactions=redactions)


def sanitize(
    source: Path,
    output: Path,
    *,
    redactions: list[str] | None = None,
    confirm_no_customer_data: bool = False,
) -> Path:
    if not redactions and not confirm_no_customer_data:
        raise ValueError("Supply a local redaction list or --confirm-no-customer-data review")
    if source.resolve() == output.resolve() or output.exists():
        raise ValueError("Output must be a new directory distinct from the raw run")
    missing = [
        name for name in ARTIFACTS if not (source / name).is_file() or (source / name).is_symlink()
    ]
    if missing:
        raise ValueError("Run is incomplete: required artifacts are missing")
    output.mkdir(parents=True)
    archive = output.with_suffix(".zip")
    if archive.exists():
        output.rmdir()
        raise FileExistsError("Refusing to overwrite an existing shareable archive")
    try:
        for name in ARTIFACTS:
            if name.endswith(".json") and name != "sanitization-report.json":
                write_json(
                    output / name, sanitize_document(name, read_json(source / name), redactions)
                )
        summary = read_json(output / "workload-summary.json")
        markdown = (
            "# Sanitized measured evidence\n\n"
            f"- Request count: {summary.get('request_count')}\n"
            f"- p50 / p95 / p99 (ms): {summary.get('p50_ms')} / "
            f"{summary.get('p95_ms')} / {summary.get('p99_ms')}\n\n"
            "Free-form raw notes were deliberately excluded. Only allowlisted, typed evidence "
            "is published. Null is missing evidence, not zero.\n\n"
            f"Cost winner and sizing recommendation: {NOT_DEMONSTRATED}\n"
        )
        for name in ("observations.md", "executive-summary.md"):
            (output / name).write_text(markdown, encoding="utf-8")
        optional = source / "idle-resume.json"
        if optional.exists():
            write_json(
                output / optional.name,
                sanitize_document(
                    optional.name,
                    read_json(optional),
                    redactions,
                ),
            )
        write_json(
            output / "sanitization-report.json",
            {
                "status": "sanitized",
                "timestamp": utc_now(),
                "strategy": "recursive schema allowlist; free-form notes and raw logs excluded",
                "redaction_list_supplied": bool(redactions),
                "customer_data_review_confirmed": confirm_no_customer_data,
                "stable_correlation_pseudonyms": True,
                "raw_sql_headers_and_identifiers_excluded": True,
            },
        )
        findings = scan_directory(output, redactions)
        if findings:
            raise ValueError("Sanitized output failed publication scan; no bundle created")
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(output.iterdir()):
                bundle.write(path, arcname=path.name)
        return archive
    except Exception:
        if archive.exists():
            archive.unlink()
        shutil.rmtree(output)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed, allowlisted customer-shareable bundle"
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--redactions", type=Path)
    parser.add_argument("--confirm-no-customer-data", action="store_true")
    args = parser.parse_args(argv)
    redactions = read_json(args.redactions) if args.redactions else []
    if not isinstance(redactions, list) or not all(isinstance(item, str) for item in redactions):
        raise ValueError("Redactions must be a local JSON list of strings")
    sanitize(
        args.run_dir,
        args.output,
        redactions=redactions,
        confirm_no_customer_data=args.confirm_no_customer_data,
    )
    print(json.dumps({"status": "sanitized-and-scanned", "bundle_created": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main))
