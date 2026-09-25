from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.experiments.common import NOT_DEMONSTRATED, read_json, write_json
from src.experiments.outcomes import OUTCOMES


def application_recovery(
    directory: Path,
    operation_start: str,
    operation_end: str,
    stable_requests: int = 5,
) -> dict[str, Any]:
    start = datetime.fromisoformat(operation_start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(operation_end.replace("Z", "+00:00"))
    events = [
        json.loads(line)
        for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events.sort(key=lambda item: item["timestamp"])
    after = [
        event
        for event in events
        if datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")) >= start
    ]
    failure_count = sum(event["outcome"] not in OUTCOMES[:2] for event in after)
    consecutive = 0
    stable_at: str | None = None
    for event in after:
        if datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")) < end:
            continue
        consecutive = consecutive + 1 if event["outcome"] in OUTCOMES[:2] else 0
        if consecutive >= stable_requests:
            stable_at = event["timestamp"]
            break
    result: dict[str, Any] = {
        "operation_start_utc": operation_start,
        "operation_end_utc": operation_end,
        "failed_requests_after_start": failure_count,
        "last_request_completed_utc": (
            max(
                datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
                + timedelta(milliseconds=event["elapsed_ms"])
                for event in events
            ).isoformat()
            if events
            else None
        ),
        "stable_successes_required": stable_requests,
        "stable_observed_utc": stable_at,
        "stable_observation_seconds_after_operation_end": (
            (datetime.fromisoformat(stable_at.replace("Z", "+00:00")) - end).total_seconds()
            if stable_at
            else None
        ),
        "customer_rto": None,
        "customer_rpo": None,
        "measured_data_loss": None,
        "assumption": "POC assumption, not a confirmed customer requirement.",
        "limitations": (
            "This is sampled application stability, not a contractual RTO or RPO. "
            "No failures observed does not prove zero interruption."
        ),
    }
    write_json(directory / "failover-application.json", result)
    return result


def serverless_report(directory: Path) -> None:
    rows: list[str] = []
    for case in sorted(directory.glob("test-*")):
        manifest_path = case / "manifest.final.json"
        if not manifest_path.exists():
            manifest_path = case / "manifest.json"
        summary_path = case / "workload-summary.json"
        if not manifest_path.exists() or not summary_path.exists():
            continue
        manifest, summary = read_json(manifest_path), read_json(summary_path)
        idle_path = case / "idle-resume.json"
        idle = read_json(idle_path) if idle_path.exists() else {}
        first = idle.get("first_request") or {}
        dataset_status = manifest.get("dataset_fairness", {}).get(
            "data_state_comparison_status", "non-equivalent-or-unverified"
        )
        rows.append(
            f"| {case.name} | {manifest.get('compute_tier')} | "
            f"{manifest.get('profile_hash')} | {summary.get('p95_ms')} | "
            f"{summary.get('p99_ms')} | {summary.get('retry_rate')} | "
            f"{summary.get('timeout_rate')} | {first.get('elapsed_ms')} | "
            f"{dataset_status} |"
        )
    text = (
        "# Serverless comparison: measured evidence\n\n"
        "| Test | Tier | Profile hash | p95 ms | p99 ms | Retry rate | Timeout rate | "
        "First request ms | Dataset comparison status |\n|---|---|---|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\nNull/None is missing evidence, never zero. Identical profile hashes alone do not "
        "establish fairness. Write-mix runs mutate inventory, work items and idempotency state. "
        "Without approved deterministic resets before EACH compared run, data states are "
        "non-equivalent or unverified; fair-comparison claims are refused. Review immutable "
        "manifest.initial.json/manifest.final.json, before/after aggregate fingerprints, counter "
        "deltas and reset provenance. Matching aggregate state is not full-content proof.\n\n"
        "## Estimated cost\n\nUse selected paid pricing inputs and measured app_cpu_billed "
        "Total vCore-seconds. Storage, backup, monitoring, application and network charges remain "
        "separate. Do not infer allocated compute from app CPU alone.\n\n"
        "## Remaining unknowns\n\n"
        f"Resume-latency objectives and cost winner: {NOT_DEMONSTRATED}\n"
        "Inspect idle-resume.json for sampled pause/resume timing and first-request failures. "
        "Inspect azure-sql-metrics.json for observed utilization; allocated vCores remain unknown "
        "unless directly measured. Minimum-compute and memory-billing effects require review.\n\n"
        "## Recommendation\n\nMore testing required. Neither traffic spikes nor auto-pause alone "
        "justify serverless. Review active/idle hours, variability, operational simplicity, "
        "probe interference, configured ceilings and actual pricing before selecting a tier.\n"
    )
    (directory / "serverless-comparison.md").write_text(text, encoding="utf-8")
