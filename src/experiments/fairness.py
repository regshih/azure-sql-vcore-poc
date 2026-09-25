from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from src.database.seed import MAX_ROWS, PROFILES
from src.experiments import client
from src.experiments.common import NOT_DEMONSTRATED, ROOT, utc_now

STATE_FIELDS = (
    "database_validation",
    "schema_version",
    "product_count",
    "work_item_count",
    "counts_source",
    "tuning_mode",
    "dataset_version",
    "dataset_kind",
    "dataset_state",
    "dataset_state_fingerprint",
    "dataset_fingerprint_scope",
    "dataset_state_requires_quiescent_workload",
    "metadata_observed_at",
    "instance_id",
)


def write_once(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def snapshot(host: str, *, enabled: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": NOT_DEMONSTRATED,
        "sampled_utc": utc_now(),
        "dataset_state_fingerprint": None,
        "dataset_state": None,
        "dataset_fingerprint_scope": "unknown",
    }
    if not enabled or not os.environ.get("POC_INTERNAL_API_TOKEN"):
        return result
    try:
        value = client.metadata(host, refresh_database=True)
        result.update({key: value.get(key) for key in STATE_FIELDS})
        fingerprint = result["dataset_state_fingerprint"]
        if (
            value.get("database_validation") == "metadata_query_succeeded"
            and isinstance(fingerprint, str)
            and re.fullmatch(r"[a-f0-9]{64}", fingerprint)
            and isinstance(result["dataset_state"], dict)
            and value.get("metadata_observed_at")
        ):
            result["status"] = "measured"
    except (httpx.HTTPError, ValueError) as exc:
        result["failure_category"] = type(exc).__name__
    return result


def seed_parameters(state: dict[str, Any]) -> dict[str, Any]:
    match = re.fullmatch(r"synthetic-v1-s(\d+)-p(\d+)-w(\d+)", str(state.get("dataset_version")))
    if (
        state.get("status") != "measured"
        or state.get("dataset_kind") != "synthetic-v1"
        or not match
    ):
        raise ValueError("Reset requires refreshed, verified synthetic dataset metadata")
    seed, products, rows = map(int, match.groups())
    sizes = [name for name, (_, count) in PROFILES.items() if count == products]
    if len(sizes) != 1 or not 1 <= rows <= MAX_ROWS or not 0 <= seed <= 2147483647:
        raise ValueError("Existing dataset cannot be reproduced by the bounded seed generator")
    return {
        "size": sizes[0],
        "seed": seed,
        "rows": rows,
        "products": products,
        "dataset_version": state["dataset_version"],
        "generator_sha256": hashlib.sha256(
            (ROOT / "src" / "database" / "seed.py").read_bytes()
        ).hexdigest(),
    }


def resume_verified(host: str, instance_id: str) -> None:
    if client.metadata(host).get("instance_id") != instance_id:
        raise RuntimeError("Application instance changed before admission restoration")
    client.maintenance(host, "resume")
    current = client.metadata(host)
    if current.get("instance_id") != instance_id or current.get("idle") is not False:
        raise RuntimeError("Admission restoration could not be verified on the original instance")


def reset_dataset(
    host: str,
    config: dict[str, Any],
    parameters: dict[str, Any],
    receipt_path: Path,
    *,
    allow_destructive: bool,
    confirm_poc: bool,
    no_other_clients: bool,
    single_instance: bool,
) -> dict[str, Any]:
    if not (allow_destructive and confirm_poc and no_other_clients and single_instance):
        raise ValueError(
            "Reset requires destructive approval, POC and isolated-instance confirmations"
        )
    if receipt_path.exists():
        raise FileExistsError(
            "Reset receipt already exists; refusing another destructive operation"
        )
    deployment = client.metadata(host)
    if not (
        deployment.get("application") == "synthetic-azure-sql-vcore-poc"
        and deployment.get("synthetic_data_only") is True
        and deployment.get("poc_mode") is True
        and deployment.get("control_scope") == "single_process"
        and deployment.get("repository_backend") == "sql"
        and deployment.get("instance_id")
        and deployment.get("idle") is False
    ):
        raise ValueError("Reset requires a verified, active synthetic SQL POC process")
    before = snapshot(host, enabled=True)
    if (
        before.get("instance_id") != deployment["instance_id"]
        or seed_parameters(before) != parameters
    ):
        raise ValueError("Seed provenance changed before reset; refusing to mutate")
    receipt: dict[str, Any] = {
        "status": "failed",
        "start_utc": utc_now(),
        "parameters": parameters,
        "before": before,
        "allow_destructive_tests": allow_destructive,
        "confirm_poc": confirm_poc,
        "confirm_no_other_sql_clients": no_other_clients,
        "confirm_single_instance": single_instance,
        "synthetic_marker_checked_by_admin_transaction": None,
        "admission_restored": False,
    }
    entered = False
    try:
        entered = True
        drained = client.maintenance(host, "idle")
        state = client.metadata(host)
        if (
            drained.get("pool_disposed") is not True
            or state.get("instance_id") != deployment["instance_id"]
            or state.get("idle") is not True
        ):
            raise RuntimeError("Cannot verify the isolated application was drained")
        server = str(config["sql_server"])
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.database.manage",
                "seed",
                "--reset",
                "--size",
                parameters["size"],
                "--seed",
                str(parameters["seed"]),
                "--rows",
                str(parameters["rows"]),
                "--allow-destructive-tests",
                "--confirm-poc",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "SQL_SERVER": server if "." in server else server + ".database.windows.net",
                "SQL_DATABASE": str(config["database"]),
                "REPOSITORY_BACKEND": "sql",
                "POC_MODE": "true",
            },
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if process.returncode:
            raise RuntimeError(f"Guarded synthetic reset failed (exit {process.returncode})")
        value = json.loads(process.stdout)
        if (
            value.get("status") != "reset_and_seeded"
            or value.get("destructive_reset") is not True
            or value.get("dataset_version") != parameters["dataset_version"]
            or value.get("products") != parameters["products"]
            or value.get("work_items") != parameters["rows"]
            or not isinstance(value.get("dataset_state_fingerprint"), str)
        ):
            raise RuntimeError("Reset did not acknowledge the exact synthetic seed provenance")
        receipt["reset_result"] = {key: value.get(key) for key in STATE_FIELDS}
        receipt["synthetic_marker_checked_by_admin_transaction"] = True
        resume_verified(host, deployment["instance_id"])
        entered = False
        receipt["admission_restored"] = True
        after = snapshot(host, enabled=True)
        receipt["after"] = after
        if (
            after.get("status") != "measured"
            or after.get("instance_id") != deployment["instance_id"]
            or after.get("dataset_state_fingerprint") != value["dataset_state_fingerprint"]
            or seed_parameters(after) != parameters
        ):
            raise RuntimeError("Application dataset did not match the reset receipt")
        receipt["status"] = "reset-verified"
    except Exception as exc:
        receipt["failure_category"] = type(exc).__name__
        raise
    finally:
        try:
            if entered:
                try:
                    resume_verified(host, deployment["instance_id"])
                    receipt["admission_restored"] = True
                except Exception as exc:
                    receipt["restoration_failure"] = type(exc).__name__
                    raise RuntimeError("Reset admission restoration failed") from None
        finally:
            receipt["end_utc"] = utc_now()
            write_once(receipt_path, receipt)
    return receipt


def assessment(
    before: dict[str, Any],
    after: dict[str, Any],
    reset: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
    write_ratio: float,
) -> dict[str, Any]:
    observed = before.get("status") == after.get("status") == "measured"
    same_process = bool(before.get("instance_id")) and (
        before.get("instance_id") == after.get("instance_id")
    )
    matched: bool | None = None
    if baseline and observed and baseline["before"].get("status") == "measured":
        matched = (
            baseline["before"]["dataset_state_fingerprint"] == before["dataset_state_fingerprint"]
        )
    reset_verified = bool(
        reset
        and reset.get("status") == "reset-verified"
        and before.get("dataset_state_fingerprint")
        == reset.get("after", {}).get("dataset_state_fingerprint")
    )
    baseline_reset = (baseline or {}).get("reset_provenance") or {}
    paired_reset = bool(
        baseline
        and reset_verified
        and baseline_reset.get("status") == "reset-verified"
        and reset
        and reset["parameters"] == baseline_reset.get("parameters")
        and matched
        and same_process
    )
    return {
        "before": before,
        "after": after,
        "write_ratio": write_ratio,
        "reset_provenance": reset,
        "reference_run_id": (baseline or {}).get("test_run_id"),
        "aggregate_prestate_matches_reference": matched,
        "aggregate_state_changed": (
            before["dataset_state_fingerprint"] != after["dataset_state_fingerprint"]
            if observed
            else None
        ),
        "same_application_process": same_process,
        "reset_before_run_verified": reset_verified,
        "paired_deterministic_reset_verified": paired_reset,
        "data_state_comparison_status": (
            "matched-reset-aggregate-state" if paired_reset else "non-equivalent-or-unverified"
        ),
        "fair_comparison_claim_allowed": False,
        "full_content_equivalence": None,
        "limitations": (
            "Aggregate fingerprints do not prove full-content equality. Without separately "
            "approved deterministic resets before every compared run, write-mix results are "
            "non-equivalent or unverified. Equal profiles alone never establish fairness. "
            "Pre-run aggregate queries can warm SQL caches; they are not workload-neutral."
        ),
    }
