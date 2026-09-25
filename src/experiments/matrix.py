from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.experiments import client, fairness
from src.experiments.common import (
    ROOT,
    command_json,
    operation,
    read_json,
    safe_main,
    sql_configuration,
    utc_now,
    write_json,
)
from src.experiments.profiles import load_profile
from src.experiments.reporting import application_recovery, serverless_report
from src.experiments.runner import run


@dataclass(frozen=True)
class Case:
    test: int
    compute_tier: str
    vcores: int
    profile: str
    auto_pause: bool = False
    tuning: str = "baseline"
    cache: str = "disabled"
    idle_after: bool = False
    failover: bool = False
    geo: bool = False


CASES = (
    Case(1, "Provisioned", 2, "expected"),
    Case(2, "Provisioned", 2, "business-hours"),
    Case(3, "Provisioned", 2, "peak"),
    Case(4, "Provisioned", 2, "spike-1-minute"),
    Case(5, "Provisioned", 4, "peak"),
    Case(6, "Provisioned", 4, "spike-1-minute"),
    Case(7, "Provisioned", 2, "peak", tuning="both"),
    Case(8, "Provisioned", 2, "peak", cache="configured-backend"),
    Case(9, "Serverless", 4, "expected"),
    Case(10, "Serverless", 4, "variable-demand"),
    Case(11, "Serverless", 4, "spike-1-minute"),
    Case(12, "Serverless", 4, "idle-resume", auto_pause=True),
    Case(13, "Serverless", 4, "business-hours", auto_pause=True, idle_after=True),
    Case(14, "Provisioned", 2, "failover", failover=True),
    Case(15, "Provisioned", 2, "failover", failover=True, geo=True),
)


def plan(overrides: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [
        {
            **asdict(case),
            "profile_hash": load_profile(case.profile, **(overrides or {})).profile_hash,
            "profile_configuration": load_profile(case.profile, **(overrides or {})).model_dump(),
            "execution": "optional; explicit --include-geo" if case.geo else "planned",
            "dataset_state_policy": (
                "No automatic reset. Identical profile hashes do not establish fair comparisons. "
                "Write-mix runs without individually approved resets are "
                "non-equivalent or unverified."
            ),
        }
        for case in CASES
    ]


def tune(config: dict[str, Any], mode: str) -> None:
    server = str(config["sql_server"])
    env = {
        **os.environ,
        "SQL_SERVER": server if "." in server else server + ".database.windows.net",
        "SQL_DATABASE": str(config["database"]),
        "REPOSITORY_BACKEND": "sql",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.database.manage",
            "tune",
            "--mode",
            mode,
            "--allow-unsafe-test",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"SQL tuning operation failed (exit {result.returncode})")
    receipt = json.loads(result.stdout)
    if receipt.get("mode") != mode or receipt.get("status") != "tuned":
        raise RuntimeError("SQL tuning command did not acknowledge requested mode")


def switch(
    config_path: Path,
    tier: str,
    vcores: float,
    minimum: float,
    auto_pause_delay: int,
) -> Any:
    args = ["--compute-tier", tier, "--confirm-poc"]
    if tier == "Serverless":
        args += [
            "--min-vcores",
            str(minimum),
            "--max-vcores",
            f"{vcores:g}",
            "--auto-pause-delay",
            str(auto_pause_delay),
        ]
    else:
        args += ["--vcores", f"{vcores:g}"]
    return operation("switch-compute-tier", config_path, *args)


def restorable_database_tier(original: dict[str, Any]) -> str:
    sku = original.get("sku", {})
    tier = original.get("computeModel")
    if tier not in {"Serverless", "Provisioned"}:
        tier = "Serverless" if "_S_" in str(sku.get("name")) else "Provisioned"
    base = "GP_S_Gen5" if tier == "Serverless" else "GP_Gen5"
    if (
        sku.get("tier") != "GeneralPurpose"
        or sku.get("capacity") not in {2, 4}
        or sku.get("family") not in {None, "Gen5"}
        or sku.get("name") not in {base, f"{base}_{sku.get('capacity')}"}
    ):
        raise ValueError("Original SQL SKU must be restorable General Purpose Gen5 2/4 vCores")
    if tier == "Serverless" and (
        not isinstance(original.get("minCapacity"), (int, float))
        or isinstance(original.get("minCapacity"), bool)
        or not isinstance(original.get("autoPauseDelay"), int)
        or isinstance(original.get("autoPauseDelay"), bool)
    ):
        raise ValueError("Original Serverless minimum and auto-pause delay must be observed")
    return str(tier)


def restore_database(config_path: Path, original: dict[str, Any]) -> None:
    tier = restorable_database_tier(original)
    sku = original["sku"]
    switch(
        config_path,
        tier,
        float(sku["capacity"]),
        float(original["minCapacity"]) if tier == "Serverless" else 0.5,
        int(original["autoPauseDelay"]) if tier == "Serverless" else -1,
    )
    restored = sql_configuration(read_json(config_path))
    checks: tuple[bool, ...] = (
        restored.get("sku") == sku,
        restored.get("maxSizeBytes") == original.get("maxSizeBytes"),
        restored.get("zoneRedundant") == original.get("zoneRedundant"),
        restored.get("readScale") == original.get("readScale"),
        restored.get("licenseType") == original.get("licenseType"),
        restored.get("requestedBackupStorageRedundancy")
        == original.get("requestedBackupStorageRedundancy"),
    )
    if tier == "Serverless":
        checks += (
            restored.get("minCapacity") == original.get("minCapacity"),
            restored.get("autoPauseDelay") == original.get("autoPauseDelay"),
        )
    if not all(checks):
        raise RuntimeError("Restored SQL configuration differs from the captured original")


def restore_geo(config_path: Path) -> None:
    config = read_json(config_path)
    state = command_json(
        [
            "az",
            "sql",
            "failover-group",
            "show",
            "--subscription",
            config["subscription_id"],
            "--resource-group",
            config["resource_group"],
            "--server",
            config["sql_server"],
            "--name",
            config["failover_group"],
            "-o",
            "json",
        ]
    )
    if state.get("replicationRole") == "Primary":
        return
    if state.get("replicationRole") != "Secondary":
        raise RuntimeError("Cannot verify primary role for safe geo failback")
    operation("failover-test", config_path, "--geo", "--failback", "--confirm-poc")


def execute(
    config_path: Path,
    host: str,
    output: Path,
    *,
    confirm_poc: bool,
    allow_unsafe: bool,
    original_tuning: str | None,
    allowed_hosts: list[str],
    minimum: float,
    maximum: int,
    auto_pause_delay: int,
    include_geo: bool = False,
    selected: list[int] | None = None,
    overrides: dict[str, Any] | None = None,
    no_other_clients: bool = False,
    pause_timeout: float = 7200,
    failover_delay: float = 30,
    cache_backend: str | None = None,
    reset_dataset: bool = False,
    allow_destructive: bool = False,
    single_instance: bool = False,
) -> None:
    if not confirm_poc or not allow_unsafe:
        raise ValueError("Execution requires --confirm-poc and --allow-unsafe-test")
    if auto_pause_delay <= 0:
        raise ValueError("Specify a supported positive auto-pause delay for C2 tests")
    if reset_dataset and not (
        allow_destructive and confirm_poc and no_other_clients and single_instance
    ):
        raise ValueError(
            "--reset-dataset requires --allow-destructive-tests --confirm-poc "
            "--confirm-no-other-sql-clients --confirm-single-instance"
        )
    deployment = client.metadata(host)
    client.guard_unsafe(
        host,
        load_profile("cache-comparison"),
        allow_unsafe,
        confirm_poc,
        allowed_hosts,
        deployment,
    )
    client.require_sql_backend(deployment)
    configured_backend = "disabled"
    if any(case.cache != "disabled" and (not selected or case.test in selected) for case in CASES):
        configured_backend = client.configured_cache_backend(deployment)
        if cache_backend is not None and cache_backend != configured_backend:
            raise ValueError(
                "--cache-backend must match the already configured application backend"
            )
    original_cache = deployment.get("cache_mode")
    if original_cache not in {"disabled", "memory", "redis"}:
        raise ValueError("Original cache configuration cannot be verified")
    config = read_json(config_path)
    original = sql_configuration(config)
    restorable_database_tier(original)
    original_dataset = fairness.snapshot(host, enabled=True)
    client.require_sql_observation(deployment, original_dataset)
    original_tuning = client.original_tuning_mode(
        original_dataset.get("tuning_mode"), original_tuning
    )
    seed_parameters = fairness.seed_parameters(original_dataset) if reset_dataset else None
    product_count = (
        seed_parameters["products"] if seed_parameters else original_dataset.get("product_count")
    )
    if isinstance(product_count, int) and not isinstance(product_count, bool):
        for item in CASES:
            if selected and item.test not in selected:
                continue
            if load_profile(item.profile, **(overrides or {})).product_count > product_count:
                raise ValueError(
                    "Profile product count exceeds the seed dataset; set --product-count explicitly"
                )
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "matrix-plan.json", plan(overrides))
    write_json(
        output / "original-configuration.json",
        {
            "database": original,
            "cache_mode": original_cache,
            "tuning": original_tuning,
            "dataset": original_dataset,
            "reset_dataset_requested": reset_dataset,
            "original_data_not_restored_after_approved_synthetic_reset": reset_dataset,
        },
    )
    results: list[dict[str, Any]] = []
    restoration: list[dict[str, Any]] = []
    geo_changed = False
    baselines: dict[str, dict[str, Any]] = {}
    try:
        for case in CASES:
            if selected and case.test not in selected:
                results.append({"test": case.test, "status": "skipped; not selected"})
                continue
            if case.geo and not include_geo:
                results.append({"test": case.test, "status": "skipped; optional geo not enabled"})
                continue
            record: dict[str, Any] = {
                "test": case.test,
                "start_utc": utc_now(),
                "status": "running",
            }
            results.append(record)
            write_json(output / "matrix-results.json", results)
            case_output = output / f"test-{case.test:02d}"
            record["configuration_operation"] = switch(
                config_path,
                case.compute_tier,
                maximum if case.compute_tier == "Serverless" else case.vcores,
                minimum,
                auto_pause_delay if case.auto_pause else -1,
            )
            tune(config, case.tuning)
            client.set_cache(host, configured_backend if case.cache != "disabled" else "disabled")
            profile = load_profile(case.profile, **(overrides or {}))
            reset = (
                fairness.reset_dataset(
                    host,
                    config,
                    seed_parameters,
                    output / f"reset-provenance-test-{case.test:02d}.json",
                    allow_destructive=allow_destructive,
                    confirm_poc=confirm_poc,
                    no_other_clients=no_other_clients,
                    single_instance=single_instance,
                )
                if seed_parameters
                else None
            )
            run_kwargs: dict[str, Any] = {
                "output": case_output,
                "config_path": config_path,
                "allow_unsafe": allow_unsafe,
                "confirm_poc": confirm_poc,
                "allowed_hosts": allowed_hosts,
                "no_other_clients": no_other_clients,
                "pause_timeout": pause_timeout,
                "idle_after": case.idle_after,
                "collect_cloud": True,
                "observe_dataset_state": True,
                "reset_provenance": reset,
                "comparison_baseline": baselines.get(profile.profile_hash),
            }
            if case.failover:
                if profile.duration <= failover_delay + 30:
                    raise ValueError("Failover traffic must extend beyond the configured trigger")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run, profile, host, **run_kwargs)
                    requests_path = case_output / "requests.jsonl"
                    startup_deadline = time.monotonic() + 120
                    while not requests_path.exists() or requests_path.stat().st_size == 0:
                        if future.done():
                            future.result()
                            raise RuntimeError("No traffic observed before failover")
                        if time.monotonic() >= startup_deadline:
                            raise TimeoutError("Workload startup deadline exceeded before failover")
                        time.sleep(0.1)
                    time.sleep(failover_delay)
                    if future.done():
                        future.result()
                        raise RuntimeError("Workload ended before failover could start")
                    record["failover_start_utc"] = utc_now()
                    extra = ["--geo"] if case.geo else []
                    geo_changed = case.geo
                    record["failover_operation"] = operation(
                        "failover-test",
                        config_path,
                        "--confirm-poc",
                        *extra,
                    )
                    record["failover_end_utc"] = utc_now()
                    if future.done():
                        record["continuous_traffic_coverage"] = False
                        future.result()
                        raise RuntimeError("Workload ended before failover completion")
                    future.result()
                    record["application_recovery"] = application_recovery(
                        case_output,
                        record["failover_start_utc"],
                        record["failover_end_utc"],
                    )
                    finished = record["application_recovery"]["last_request_completed_utc"]
                    if finished is None or datetime.fromisoformat(
                        finished
                    ) < datetime.fromisoformat(
                        record["failover_end_utc"],
                    ):
                        record["continuous_traffic_coverage"] = False
                        raise RuntimeError(
                            "Measured request window ended before failover completion"
                        )
                    record["continuous_traffic_coverage"] = True
            else:
                run(profile, host, **run_kwargs)
            immutable_manifest = case_output / "manifest.final.json"
            run_manifest = read_json(immutable_manifest)
            record["manifest_sha256"] = hashlib.sha256(immutable_manifest.read_bytes()).hexdigest()
            record["dataset_fairness"] = run_manifest["dataset_fairness"]
            baselines.setdefault(
                profile.profile_hash,
                {
                    "test_run_id": run_manifest["test_run_id"],
                    "before": run_manifest["dataset_fairness"]["before"],
                    "reset_provenance": reset,
                },
            )
            record["status"] = "executed; inspect evidence, not an automatic pass"
            record["end_utc"] = utc_now()
            record["profile_hash"] = profile.profile_hash
            write_json(output / "matrix-results.json", results)
    except Exception as exc:
        if results and results[-1]["status"] == "running":
            results[-1]["status"] = "failed"
            results[-1]["failure_category"] = type(exc).__name__
        raise
    finally:
        actions: list[tuple[str, Callable[[], Any]]] = [
            ("sql_configuration", lambda: restore_database(config_path, original)),
            ("tuning", lambda: tune(config, original_tuning)),
            ("cache", lambda: client.set_cache(host, original_cache)),
        ]
        if geo_changed:
            actions.insert(
                0,
                (
                    "geo_failback",
                    lambda: restore_geo(config_path),
                ),
            )
        for name, restore in actions:
            try:
                restore()
                restoration.append({"component": name, "status": "restored"})
            except Exception as exc:
                restoration.append(
                    {
                        "component": name,
                        "status": "restoration_failed",
                        "failure_category": type(exc).__name__,
                    }
                )
        write_json(output / "matrix-results.json", results)
        write_json(output / "restoration.json", restoration)
        serverless_report(output)
        from src.experiments.storage import archive_if_configured

        archive_if_configured(output, config_path)
        if any(item["status"] == "restoration_failed" for item in restoration):
            raise RuntimeError(
                "Matrix restoration failed; inspect restoration.json and restore POC manually"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan or explicitly execute the 15-test POC matrix"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-poc", action="store_true")
    parser.add_argument("--allow-unsafe-test", action="store_true")
    parser.add_argument(
        "--reset-dataset",
        action="store_true",
        help="Explicitly reset/reseed the marked synthetic dataset before EACH selected run",
    )
    parser.add_argument("--allow-destructive-tests", action="store_true")
    parser.add_argument("--confirm-single-instance", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--host")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--original-tuning", choices=["baseline", "index", "query", "both"])
    parser.add_argument("--min-vcores", type=float, default=0.5)
    parser.add_argument("--max-vcores", type=int, default=4)
    parser.add_argument("--auto-pause-delay", type=int)
    parser.add_argument("--include-geo", action="store_true")
    parser.add_argument("--tests", type=int, nargs="+", choices=range(1, 16))
    parser.add_argument("--confirm-no-other-sql-clients", action="store_true")
    parser.add_argument("--pause-timeout", type=float, default=7200)
    parser.add_argument("--failover-delay", type=float, default=30)
    parser.add_argument(
        "--cache-backend",
        choices=["memory", "redis"],
        help="Optional assertion of the already configured backend; never creates or switches it",
    )
    parser.add_argument("--users", type=int)
    parser.add_argument("--spawn-rate", type=float)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--write-ratio", type=float)
    parser.add_argument("--product-count", type=int)
    args = parser.parse_args(argv)
    overrides = {
        "users": args.users,
        "spawn_rate": args.spawn_rate,
        "rate": args.rate,
        "duration": args.duration,
        "write_ratio": args.write_ratio,
        "product_count": args.product_count,
    }
    if not args.execute:
        data = plan(overrides)
        if args.output:
            write_json(args.output, data)
        print(json.dumps(data, indent=2))
        return 0
    if not all((args.config, args.host, args.auto_pause_delay)):
        parser.error("Execution needs --config --host --auto-pause-delay")
    execute(
        args.config,
        args.host,
        args.output
        or ROOT
        / "results"
        / "local-untracked-runs"
        / ("matrix-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())),
        confirm_poc=args.confirm_poc,
        allow_unsafe=args.allow_unsafe_test,
        original_tuning=args.original_tuning,
        allowed_hosts=args.allow_host,
        minimum=args.min_vcores,
        maximum=args.max_vcores,
        auto_pause_delay=args.auto_pause_delay,
        include_geo=args.include_geo,
        selected=args.tests,
        overrides=overrides,
        no_other_clients=args.confirm_no_other_sql_clients,
        pause_timeout=args.pause_timeout,
        failover_delay=args.failover_delay,
        cache_backend=args.cache_backend,
        reset_dataset=args.reset_dataset,
        allow_destructive=args.allow_destructive_tests,
        single_instance=args.confirm_single_instance,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main))
