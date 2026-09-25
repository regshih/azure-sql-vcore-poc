from __future__ import annotations

from pathlib import Path
from typing import Any

from src.experiments import client
from src.experiments.common import read_json, sql_configuration, write_json
from src.experiments.matrix import restorable_database_tier, restore_database, switch, tune
from src.experiments.profiles import Profile
from src.experiments.runner import run


def slow_query_comparison(
    profile: Profile,
    host: str,
    output: Path,
    config_path: Path,
    original_tuning: str | None,
    kwargs: dict[str, Any],
) -> None:
    if profile.scenario != "slow":
        raise ValueError("--compare-tuning is only valid for slow-query")
    deployment = client.metadata(host)
    client.guard_unsafe(
        host,
        profile,
        kwargs["allow_unsafe"],
        kwargs["confirm_poc"],
        kwargs["allowed_hosts"],
        deployment,
    )
    client.require_sql_backend(deployment)
    refreshed = client.metadata(host, refresh_database=True)
    client.require_sql_backend(refreshed)
    client.require_sql_observation(deployment, refreshed)
    original_tuning = client.original_tuning_mode(refreshed.get("tuning_mode"), original_tuning)
    original = sql_configuration(read_json(config_path))
    restorable_database_tier(original)
    output.mkdir(parents=True, exist_ok=False)
    write_json(
        output / "original-configuration.json",
        {
            "database": original,
            "tuning": original_tuning,
            "tuning_mode": refreshed.get("tuning_mode"),
        },
    )
    results: list[dict[str, Any]] = []
    restoration: list[dict[str, str]] = []
    try:
        for vcores in (2, 4):
            switch(config_path, "Provisioned", vcores, 0.5, -1)
            for mode in ("baseline", "index", "query", "both"):
                tune(read_json(config_path), mode)
                directory = run(
                    profile,
                    host,
                    output=output / f"vcores-{vcores}-{mode}",
                    **kwargs,
                )
                results.append(
                    {
                        "vcores": vcores,
                        "tuning": mode,
                        "profile_hash": profile.profile_hash,
                        "summary": read_json(directory / "workload-summary.json"),
                    }
                )
                write_json(output / "comparison.json", results)
    finally:
        try:
            restore_database(config_path, original)
            restoration.append({"component": "database", "status": "restored"})
        except Exception as exc:
            restoration.append(
                {
                    "component": "database",
                    "status": "failed",
                    "failure_category": type(exc).__name__,
                }
            )
        try:
            tune(read_json(config_path), original_tuning)
            restoration.append({"component": "tuning", "status": "restored"})
        except Exception as exc:
            restoration.append(
                {
                    "component": "tuning",
                    "status": "failed",
                    "failure_category": type(exc).__name__,
                }
            )
        write_json(output / "restoration.json", restoration)
        from src.experiments.storage import archive_if_configured

        archive_if_configured(output, config_path)
        if any(item["status"] == "failed" for item in restoration):
            raise RuntimeError("Tuning comparison restoration failed; inspect local evidence")
