from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from src.experiments import client, fairness
from src.experiments.cloud_config import environment_configuration
from src.experiments.common import (
    ARTIFACTS,
    NOT_DEMONSTRATED,
    ROOT,
    command_json,
    numeric_header,
    read_json,
    safe_main,
    sql_configuration,
    utc_now,
    write_json,
)
from src.experiments.evidence import collect, counter_delta, finalize, initialize
from src.experiments.outcomes import classify, native_outcome
from src.experiments.profiles import Profile, load_profile
from src.experiments.sampling import MetricsSampler


def invoke_locust(profile: Profile, host: str, directory: Path, run_id: str) -> int:
    profile_path = directory / "profile.json"
    write_json(profile_path, profile.model_dump())
    env = {
        **os.environ,
        "POC_PROFILE_FILE": str(profile_path.resolve()),
        "POC_RUN_DIRECTORY": str(directory.resolve()),
        "POC_RUN_ID": run_id,
    }
    command = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(ROOT / "load-tests" / "locustfile.py"),
        "--headless",
        "--host",
        client.origin(host),
        "--users",
        str(profile.users),
        "--spawn-rate",
        str(profile.spawn_rate),
        "--run-time",
        f"{math.ceil(profile.duration)}s",
        "--stop-timeout",
        str(profile.request_timeout + 5),
        "--csv",
        str(directory / "locust"),
        "--csv-full-history",
        "--exit-code-on-error",
        "1",
        "--only-summary",
        "--loglevel",
        "CRITICAL",
    ]
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=profile.duration + profile.request_timeout + 120,
        check=False,
    )
    return process.returncode


def observe_idle(
    host: str,
    profile: Profile,
    directory: Path,
    config: dict[str, Any],
    *,
    timeout: float,
    interval: float,
    slack: float,
    no_other_clients: bool,
    run_id: str,
) -> dict[str, Any]:
    if not no_other_clients:
        raise ValueError("Idle test requires --confirm-no-other-sql-clients")
    database = sql_configuration(config)
    sku = database.get("sku", {}).get("name", "")
    if database.get("computeModel") != "Serverless" and "_S_" not in sku:
        raise ValueError("Idle test requires verified Serverless compute")
    delay = database.get("autoPauseDelay")
    if not isinstance(delay, (int, float)) or delay <= 0:
        raise ValueError("Idle test requires auto-pause enabled in the live target configuration")
    if timeout <= delay * 60 + slack:
        raise ValueError("Pause timeout must exceed actual auto-pause delay plus platform slack")
    links = command_json(
        [
            "az",
            "sql",
            "db",
            "replica",
            "list-links",
            "--subscription",
            config["subscription_id"],
            "--resource-group",
            config["resource_group"],
            "--server",
            config["sql_server"],
            "--name",
            config["database"],
            "-o",
            "json",
        ]
    )
    if links or config.get("geo_enabled") or database.get("failoverGroupId"):
        raise ValueError("Auto-pause experiment is incompatible with configured geo-replication")
    if database.get("status") != "Online":
        raise ValueError("Idle test must begin with an Online database")
    warmup = Profile.model_validate(
        {
            **profile.model_dump(),
            "scenario": "normal",
            "duration": min(15, profile.duration),
        }
    )
    warmup_dir = directory / "warmup"
    warmup_dir.mkdir()
    if invoke_locust(warmup, host, warmup_dir, run_id + "-warmup"):
        raise RuntimeError("Idle test warmup failed")
    paused = False
    evidence: dict[str, Any] = {
        "observations": [],
        "pause_observed_utc": None,
        "resume_observed_utc": None,
        "timestamp_precision": "sampled control-plane observations, not exact platform event times",
        "first_request": None,
        "status": NOT_DEMONSTRATED,
        "idle_started_utc": utc_now(),
    }
    entered = False
    start = time.monotonic()
    try:
        state = client.maintenance(host, "idle")
        entered = True
        if state.get("pool_disposed") is not True or state.get("readiness_mode") != "process":
            raise RuntimeError("Cannot verify SQL probes stopped and the pool disposed")
        while time.monotonic() - start < timeout:
            status = sql_configuration(config).get("status")
            evidence["observations"].append({"timestamp": utc_now(), "status": status})
            if status == "Paused":
                paused = True
                evidence["pause_observed_utc"] = utc_now()
                break
            time.sleep(interval)
        evidence["idle_duration_seconds"] = time.monotonic() - start
        if not paused:
            raise TimeoutError("Auto-pause was not observed within the bounded control-plane wait")
    finally:
        try:
            if entered:
                client.maintenance(host, "resume")
        except Exception:
            evidence["restoration_failure"] = True
            raise
        finally:
            write_json(directory / "idle-resume.json", evidence)
    began = time.monotonic()
    timestamp = utc_now()
    status_code: int | None = None
    outcome_header: str | None = None
    retry: float | None = None
    timeout_occurred = False
    try:
        response = httpx.get(
            client.origin(host) + "/api/products/1",
            timeout=profile.request_timeout,
            headers={
                "X-Test-Run-Id": run_id,
                "X-Workload-Profile": profile.name,
                "X-Correlation-ID": run_id + "-resume-first",
            },
            follow_redirects=False,
        )
        status_code = response.status_code
        outcome_header = response.headers.get("X-POC-Outcome")
        retry = numeric_header(response.headers.get("X-Retry-Count"))
    except httpx.TimeoutException:
        timeout_occurred = True
    except httpx.TransportError:
        outcome_header = None
    evidence["first_request"] = {
        "timestamp": timestamp,
        "correlation_id": run_id + "-resume-first",
        "elapsed_ms": (time.monotonic() - began) * 1000,
        "outcome": classify(status_code, outcome_header, retry, timeout_occurred),
        "native_outcome": native_outcome(outcome_header),
        "http_status": status_code,
        "retry_count": retry,
    }
    evidence["status"] = "measured"
    evidence["resume_sample_after_first_request"] = sql_configuration(config).get("status")
    if evidence["resume_sample_after_first_request"] == "Online":
        evidence["resume_observed_utc"] = utc_now()
    write_json(directory / "idle-resume.json", evidence)
    return evidence


def emit_evidence(directory: Path) -> None:
    for name in ARTIFACTS:
        path = directory / name
        if not path.exists():
            continue
        print(
            "POC_EVIDENCE "
            + json.dumps(
                {
                    "artifact": name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                    "status": "local-artifact-persisted",
                    "artifact_contents_in_logs": False,
                },
                separators=(",", ":"),
                allow_nan=False,
            ),
            flush=True,
        )


def compact_evidence(value: Any) -> Any:
    if isinstance(value, list):
        if len(value) > 10:
            return {
                "record_count": len(value),
                "truncated_for_log": True,
                "first_records": [compact_evidence(item) for item in value[:3]],
            }
        return [compact_evidence(item) for item in value]
    if isinstance(value, dict):
        return {key: compact_evidence(item) for key, item in value.items()}
    return value


def sql_business_successes(path: Path, run_id: str) -> int:
    operations = {
        "point-lookup",
        "filtered-work-items",
        "filtered-lookup",
        "paginated-lookup",
        "dashboard",
        "recent-activity",
        "batch-work-items",
        "batch-read",
        "transactional-write",
    }
    count = 0
    if not path.is_file():
        return count
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            calls, status = event.get("db_calls"), event.get("http_status")
            if (
                event.get("test_id") == run_id
                and event.get("operation") in operations
                and event.get("outcome") in {"Completed normally", "Completed after retry"}
                and isinstance(status, int)
                and not isinstance(status, bool)
                and 200 <= status < 400
                and isinstance(calls, (int, float))
                and not isinstance(calls, bool)
                and math.isfinite(calls)
                and calls > 0
            ):
                count += 1
    return count


def run(
    profile: Profile,
    host: str,
    *,
    output: Path | None = None,
    config_path: Path | None = None,
    allow_unsafe: bool = False,
    confirm_poc: bool = False,
    allowed_hosts: list[str] | None = None,
    pause_timeout: float = 7200,
    pause_interval: float = 30,
    pause_slack: float = 600,
    no_other_clients: bool = False,
    collect_cloud: bool = False,
    idle_after: bool = False,
    observe_dataset_state: bool = False,
    reset_provenance: dict[str, Any] | None = None,
    comparison_baseline: dict[str, Any] | None = None,
) -> Path:
    collect_cloud = collect_cloud or bool(os.environ.get("CONTAINER_APP_JOB_NAME"))
    if collect_cloud:
        profile.require_cloud_duration()
    host = client.origin(host)
    deployment = client.metadata(host)
    controlled = profile.scenario in {"storm", "slow", "idle", "cache"} or idle_after
    guarded_profile = (
        profile
        if not idle_after
        else Profile.model_validate(
            {
                **profile.model_dump(),
                "scenario": "idle",
            }
        )
    )
    client.guard_unsafe(
        host,
        guarded_profile,
        allow_unsafe,
        confirm_poc,
        allowed_hosts or [],
        deployment,
    )
    run_id = "run-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid4().hex[:12]
    directory = output or ROOT / "results" / "local-untracked-runs" / run_id
    directory = directory.resolve()
    if (directory / "manifest.json").exists():
        raise FileExistsError("Run directory already contains a manifest; refusing to overwrite")
    initialize(directory)
    config = (
        read_json(config_path)
        if config_path
        else (environment_configuration() if collect_cloud else None)
    )
    if collect_cloud and config_path is None:
        write_json(directory / "cloud-configuration.json", config)
    needs_sql_validation = controlled or config_path is not None or collect_cloud
    observe_dataset_state = observe_dataset_state or needs_sql_validation
    cloud_rest = collect_cloud
    database_collection: dict[str, Any] | None = None
    if cloud_rest or config is not None:
        from src.experiments.cloud_evidence import database_configuration

        database, database_collection = (
            database_configuration(config) if config_path else database_configuration()
        )
    else:
        database = None
    sku = database.get("sku", {}) if database else {}
    tier = database.get("computeModel") if database else None
    if tier is None and sku.get("name", "").startswith("GP_"):
        tier = "Serverless" if "_S_" in sku["name"] else "Provisioned"
    dataset_before = fairness.snapshot(host, enabled=observe_dataset_state)
    count_metadata = (
        dataset_before if dataset_before.get("product_count") is not None else deployment
    )
    product_count = count_metadata.get("product_count")
    dataset_after: dict[str, Any] = {
        "status": NOT_DEMONSTRATED,
        "dataset_state_fingerprint": None,
    }
    manifest: dict[str, Any] = {
        "test_run_id": run_id,
        "start_utc": utc_now(),
        "end_utc": None,
        "profile_hash": profile.profile_hash,
        "profile": profile.model_dump(),
        "workload_profile": profile.name,
        "volume_model": profile.volume_model(),
        "application_version": deployment.get("application_version"),
        "schema_version": dataset_before.get("schema_version") or deployment.get("schema_version"),
        "dataset_version": dataset_before.get("dataset_version")
        or deployment.get("dataset_version"),
        "dataset_size": {
            "product_count": product_count,
            "work_item_count": count_metadata.get("work_item_count"),
            "counts_source": count_metadata.get("counts_source", "unknown"),
        },
        "repository_backend": deployment.get("repository_backend"),
        "sql_adapter_configured": deployment.get("sql_adapter_configured"),
        "tuning_mode": dataset_before.get("tuning_mode") or deployment.get("tuning_mode"),
        "duration_seconds": profile.duration,
        "status": "running",
        "idempotency_key_scope": "unique-run-id-user-sequence; never replayed across runs",
        "dataset_fairness": fairness.assessment(
            dataset_before,
            dataset_after,
            reset_provenance,
            comparison_baseline,
            profile.write_ratio,
        ),
        "toggles": {
            "allow_unsafe_test": allow_unsafe,
            "confirm_poc": confirm_poc,
            "controlled": controlled,
            "confirm_no_other_sql_clients": no_other_clients,
            "idle_after": idle_after,
            "connection_mode": profile.connection_mode,
            "cache_mode": deployment.get("cache_mode"),
            "observe_dataset_state": observe_dataset_state,
            "collect_cloud": collect_cloud,
            "cloud_rest": cloud_rest,
        },
        "region": config.get("region")
        if config
        else database.get("location")
        if database
        else None,
        "compute_tier": tier,
        "hardware_family": database.get("sku", {}).get("family") if database else None,
        "provisioned_vcores": sku.get("capacity") if tier == "Provisioned" else None,
        "serverless_max_vcores": sku.get("capacity") if tier == "Serverless" else None,
        "serverless_min_vcores": database.get("minCapacity")
        if database and tier == "Serverless"
        else None,
        "auto_pause_delay": database.get("autoPauseDelay") if database else None,
        "zone_redundant": database.get("zoneRedundant") if database else None,
        "backup_redundancy": database.get("currentBackupStorageRedundancy") if database else None,
        "storage_bytes": database.get("maxSizeBytes") if database else None,
        "missing_measurement_status": NOT_DEMONSTRATED,
    }
    write_json(
        directory / "configuration.json",
        {
            "database": database,
            "database_collection": database_collection,
            "application": deployment,
            "profile": profile.model_dump(),
        },
    )
    write_json(directory / "manifest.json", manifest)
    fairness.write_once(directory / "manifest.initial.json", manifest)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    sampler = MetricsSampler(host)
    began = time.monotonic()
    try:
        if needs_sql_validation:
            client.require_sql_observation(deployment, dataset_before)
        if (
            deployment.get("sql_adapter_configured") is True
            and profile.scenario not in {"slow", "storm"}
            and isinstance(product_count, int)
            and not isinstance(product_count, bool)
            and profile.product_count > product_count
        ):
            raise ValueError(
                "Profile product count exceeds observed seed bounds; explicitly set --product-count"
            )
        before = client.snapshot(host)
        if profile.scenario == "idle":
            if config is None:
                raise ValueError("Idle tests require --config")
            observe_idle(
                host,
                profile,
                directory,
                config,
                timeout=pause_timeout,
                interval=pause_interval,
                slack=pause_slack,
                no_other_clients=no_other_clients,
                run_id=run_id,
            )
        sampler.start()
        try:
            exit_code = invoke_locust(profile, host, directory, run_id)
        finally:
            sampler.stop()
            write_json(
                directory / "application-samples.json",
                {
                    "samples": sampler.samples,
                    "summary": sampler.summary(),
                },
            )
        manifest["locust_exit_code"] = exit_code
        if collect_cloud and profile.name == "smoke":
            manifest["sql_business_request_success_count"] = sql_business_successes(
                directory / "requests.jsonl", run_id
            )
            if manifest["sql_business_request_success_count"] == 0:
                manifest["failure_reason"] = "no-successful-sql-business-requests"
                raise RuntimeError(
                    "Cloud smoke demonstrated no successful SQL-backed business requests"
                )
        after = client.snapshot(host)
        if idle_after:
            if config is None:
                raise ValueError("Business-hours followed by idle requires --config")
            idle_profile = load_profile("idle-resume")
            observe_idle(
                host,
                idle_profile,
                directory,
                config,
                timeout=pause_timeout,
                interval=pause_interval,
                slack=pause_slack,
                no_other_clients=no_other_clients,
                run_id=run_id,
            )
        manifest["status"] = "completed" if exit_code == 0 else "completed-with-request-errors"
        if exit_code not in {0, 1} or not (directory / "requests.jsonl").exists():
            raise RuntimeError(f"Locust did not complete successfully (exit {exit_code})")
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failure_category"] = type(exc).__name__
        raise
    finally:
        manifest["end_utc"] = utc_now()
        manifest["wall_duration_seconds"] = time.monotonic() - began
        dataset_after = fairness.snapshot(host, enabled=observe_dataset_state)
        manifest["dataset_fairness"] = fairness.assessment(
            dataset_before,
            dataset_after,
            reset_provenance,
            comparison_baseline,
            profile.write_ratio,
        )
        manifest["application_counter_delta"] = counter_delta(before, after)
        write_json(directory / "manifest.json", manifest)
        finalize(directory, before=before, after=after)
        app_metrics = read_json(directory / "application-metrics.json")
        app_metrics.update(sampler.summary())
        write_json(directory / "application-metrics.json", app_metrics)
        try:
            if collect_cloud:
                collect(directory, config_path, cloud_rest=cloud_rest)
        except Exception as exc:
            manifest = read_json(directory / "manifest.json")
            manifest["evidence_collection_status"] = "failed"
            manifest["evidence_collection_failure_category"] = type(exc).__name__
            write_json(directory / "manifest.json", manifest)
            raise
        finally:
            fairness.write_once(
                directory / "manifest.final.json", read_json(directory / "manifest.json")
            )
            emit_evidence(directory)
            from src.experiments.storage import archive_if_configured

            archive_if_configured(directory, config_path)
    return directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded, measured headless Locust workload")
    parser.add_argument("--profile", default="smoke")
    parser.add_argument("--host", required=True)
    parser.add_argument("--users", type=int)
    parser.add_argument("--spawn-rate", type=float)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--duration", type=float, help="Seconds")
    parser.add_argument("--write-ratio", type=float)
    parser.add_argument("--product-count", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--allow-unsafe-test", action="store_true")
    parser.add_argument("--confirm-poc", action="store_true")
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--confirm-no-other-sql-clients", action="store_true")
    parser.add_argument("--pause-timeout", type=float, default=7200)
    parser.add_argument("--pause-interval", type=float, default=30)
    parser.add_argument("--pause-slack", type=float, default=600)
    parser.add_argument("--collect-cloud", action="store_true")
    parser.add_argument(
        "--observe-dataset-state",
        action="store_true",
        help="Refresh SQL aggregate state before/after traffic, never during controlled idle",
    )
    parser.add_argument("--idle-after", action="store_true")
    parser.add_argument(
        "--cache-modes",
        help="Disabled plus the existing backend; defaults to disabled,<configured-backend>",
    )
    parser.add_argument("--connection-mode", choices=["pooled", "no-reuse"])
    parser.add_argument("--compare-tuning", action="store_true")
    parser.add_argument("--original-tuning", choices=["baseline", "index", "query", "both"])
    args = parser.parse_args(argv)
    if args.pause_interval <= 0 or args.pause_slack < 0:
        parser.error("Pause interval must be positive and slack nonnegative")
    profile = load_profile(
        args.profile,
        users=args.users,
        spawn_rate=args.spawn_rate,
        rate=args.rate,
        duration=args.duration,
        write_ratio=args.write_ratio,
        product_count=args.product_count,
        connection_mode=args.connection_mode,
    )
    kwargs: dict[str, Any] = {
        "config_path": args.config,
        "allow_unsafe": args.allow_unsafe_test,
        "confirm_poc": args.confirm_poc,
        "allowed_hosts": args.allow_host,
        "pause_timeout": args.pause_timeout,
        "pause_interval": args.pause_interval,
        "pause_slack": args.pause_slack,
        "no_other_clients": args.confirm_no_other_sql_clients,
        "collect_cloud": args.collect_cloud,
        "idle_after": args.idle_after,
        "observe_dataset_state": args.observe_dataset_state,
    }
    request_failures = False
    if args.compare_tuning:
        from src.experiments.comparisons import slow_query_comparison

        if not args.config:
            parser.error("--compare-tuning needs --config")
        slow_query_comparison(
            profile,
            args.host,
            args.output
            or ROOT / "results" / "local-untracked-runs" / ("tuning-" + uuid4().hex[:12]),
            args.config,
            args.original_tuning,
            kwargs,
        )
    elif profile.scenario == "cache":
        deployment = client.metadata(args.host)
        client.guard_unsafe(
            args.host,
            profile,
            args.allow_unsafe_test,
            args.confirm_poc,
            args.allow_host,
            deployment,
        )
        client.require_sql_backend(deployment)
        original = deployment.get("cache_mode")
        modes = client.comparison_cache_modes(deployment, args.cache_modes)
        if original not in {"disabled", "memory", "redis"}:
            raise ValueError("Original cache state must be observable")
        comparison_output = args.output or ROOT / "results" / "local-untracked-runs" / (
            "cache-" + uuid4().hex[:12]
        )
        comparison_output.mkdir(parents=True, exist_ok=False)
        try:
            cache_results = []
            for mode in modes:
                client.set_cache(args.host, mode)
                directory = run(
                    profile,
                    args.host,
                    output=comparison_output / mode,
                    **kwargs,
                )
                cache_results.append(
                    {
                        "cache_mode": mode,
                        "profile_hash": profile.profile_hash,
                        "summary": read_json(directory / "workload-summary.json"),
                        "stale_data_window_measured_seconds": None,
                        "cache_memory_usage_bytes": None,
                    }
                )
                request_failures |= bool(cache_results[-1]["summary"]["failed_request_count"])
                write_json(comparison_output / "cache-comparison.json", cache_results)
        finally:
            try:
                client.set_cache(args.host, original)
                write_json(comparison_output / "restoration.json", {"status": "restored"})
            except Exception as exc:
                write_json(
                    comparison_output / "restoration.json",
                    {"status": "restoration_failed", "failure_category": type(exc).__name__},
                )
                raise
            finally:
                from src.experiments.storage import archive_if_configured

                archive_if_configured(comparison_output, args.config)
    elif profile.scenario == "storm" and args.connection_mode is None:
        comparison_output = args.output or ROOT / "results" / "local-untracked-runs" / (
            "connections-" + uuid4().hex[:12]
        )
        comparison_output.mkdir(parents=True, exist_ok=False)
        storm_results = []
        try:
            for mode in ["pooled", "no-reuse"]:
                variant = Profile.model_validate({**profile.model_dump(), "connection_mode": mode})
                directory = run(
                    variant,
                    args.host,
                    output=comparison_output / mode,
                    **kwargs,
                )
                storm_results.append(
                    {
                        "connection_mode": mode,
                        "profile_hash": variant.profile_hash,
                        "summary": read_json(directory / "workload-summary.json"),
                    }
                )
                request_failures |= bool(storm_results[-1]["summary"]["failed_request_count"])
                write_json(comparison_output / "connection-comparison.json", storm_results)
        finally:
            from src.experiments.storage import archive_if_configured

            archive_if_configured(comparison_output, args.config)
    else:
        directory = run(profile, args.host, output=args.output, **kwargs)
        request_failures = bool(
            read_json(
                directory / "workload-summary.json",
            )["failed_request_count"]
        )
    return 1 if request_failures else 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main))
