from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.experiments.profiles import Profile


def origin(host: str) -> str:
    parsed = urlsplit(host)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Host must be an HTTP(S) origin, without credentials, paths or query")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def internal_headers() -> dict[str, str]:
    token = os.environ.get("POC_INTERNAL_API_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def metadata(host: str, *, refresh_database: bool = False) -> dict[str, Any]:
    if not os.environ.get("POC_INTERNAL_API_TOKEN"):
        if refresh_database:
            raise ValueError("Database metadata refresh requires POC_INTERNAL_API_TOKEN")
        return {}
    response = httpx.get(
        origin(host) + "/internal/metadata",
        params={"refresh_database": "true"} if refresh_database else None,
        headers=internal_headers(),
        timeout=30 if refresh_database else 10,
        follow_redirects=False,
    )
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("Invalid deployment metadata")
    return value


def guard_unsafe(
    host: str,
    profile: Profile,
    allow_unsafe: bool,
    confirm_poc: bool,
    allowed_hosts: list[str],
    deployment: dict[str, Any],
) -> None:
    if profile.scenario not in {"storm", "slow", "idle", "cache"}:
        return
    if not (allow_unsafe and confirm_poc):
        raise ValueError("Controlled tests require --allow-unsafe-test AND --confirm-poc")
    target = origin(host)
    parsed = urlsplit(target)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not local and (parsed.scheme != "https" or target not in map(origin, allowed_hosts)):
        raise ValueError("Unsafe remote target must be HTTPS and explicitly allowlisted")
    if not (
        deployment.get("poc_mode") is True
        and deployment.get("poc_marker") == "sql-vcore"
        and deployment.get("environment") == "poc"
        and deployment.get("application") == "synthetic-azure-sql-vcore-poc"
        and deployment.get("synthetic_data_only") is True
    ):
        raise ValueError("Deployment metadata does not confirm the POC marker")
    if not os.environ.get("POC_INTERNAL_API_TOKEN"):
        raise ValueError("POC_INTERNAL_API_TOKEN is required for controlled endpoints")


def snapshot(host: str) -> dict[str, Any] | None:
    if not os.environ.get("POC_INTERNAL_API_TOKEN"):
        return None
    response = httpx.get(
        origin(host) + "/internal/metrics",
        headers=internal_headers(),
        timeout=10,
        follow_redirects=False,
    )
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("Invalid application metrics")
    return value


def require_sql_backend(deployment: dict[str, Any]) -> None:
    if (
        deployment.get("repository_backend") != "sql"
        or deployment.get("sql_adapter_configured") is not True
    ):
        raise ValueError(
            "SQL workload comparisons require a verified SQL adapter, not local memory"
        )


def configured_cache_backend(deployment: dict[str, Any]) -> str:
    configuration = deployment.get("configuration")
    backend = configuration.get("cache_backend") if isinstance(configuration, dict) else None
    if not isinstance(backend, str) or backend not in {"memory", "redis"}:
        raise ValueError("Configure a memory or Redis cache backend before running comparisons")
    return backend


def require_sql_observation(deployment: dict[str, Any], observed: dict[str, Any]) -> None:
    require_sql_backend(deployment)
    instance = deployment.get("instance_id")
    if (
        not isinstance(instance, str)
        or not instance
        or observed.get("instance_id") != instance
        or observed.get("database_validation") != "metadata_query_succeeded"
    ):
        raise ValueError("Fresh SQL metadata on the original application instance is required")


def comparison_cache_modes(deployment: dict[str, Any], requested: str | None) -> list[str]:
    backend = configured_cache_backend(deployment)
    modes = requested.split(",") if requested is not None else ["disabled", backend]
    if len(modes) != 2 or set(modes) != {"disabled", backend}:
        raise ValueError(
            "Compare disabled and the existing cache backend; "
            "runtime backend switching is unsupported"
        )
    return modes


def maintenance(host: str, action: str) -> dict[str, Any]:
    response = httpx.post(
        origin(host) + "/internal/maintenance",
        headers=internal_headers(),
        json={"action": action, "confirm": True},
        timeout=60,
        follow_redirects=False,
    )
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("Invalid maintenance response")
    return value


def set_cache(host: str, mode: str) -> None:
    if mode not in {"disabled", "memory", "redis"}:
        raise ValueError("Unsupported cache mode")
    current = httpx.get(
        origin(host) + "/internal/config",
        headers=internal_headers(),
        timeout=10,
        follow_redirects=False,
    )
    current.raise_for_status()
    config = current.json()
    if mode != "disabled" and config.get("cache_backend") != mode:
        raise ValueError("Requested cache backend must be configured before starting this process")
    response = httpx.put(
        origin(host) + "/internal/config",
        headers=internal_headers(),
        json={
            "cache_enabled": mode != "disabled",
            "expected_version": config["version"],
            "confirm": True,
        },
        timeout=30,
        follow_redirects=False,
    )
    response.raise_for_status()
    actual = response.json()["current"]
    if actual.get("instance_id") != config.get("instance_id"):
        raise RuntimeError("Configuration changed a different process; use a single POC instance")
    if actual["cache_enabled"] != (mode != "disabled"):
        raise RuntimeError("Cache configuration did not match the requested state")


def original_tuning_mode(observed: Any, asserted: str | None) -> str:
    supported = {"baseline", "index", "query", "both"}
    if observed is not None and (not isinstance(observed, str) or observed not in supported):
        raise ValueError("Observed original tuning mode is unsupported")
    if asserted is not None and asserted not in supported:
        raise ValueError("Original tuning assertion is unsupported")
    if observed is not None and asserted is not None and observed != asserted:
        raise ValueError("--original-tuning conflicts with observed original tuning mode")
    selected = observed if observed is not None else asserted
    if selected is None:
        raise ValueError("Unknown original tuning requires explicit --original-tuning")
    return str(selected)
