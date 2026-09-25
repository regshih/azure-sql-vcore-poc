from __future__ import annotations

from collections import Counter
from typing import Any

OUTCOMES = (
    "Completed normally",
    "Completed after retry",
    "Client-side timeout",
    "API timeout",
    "Database command timeout",
    "Database transient error",
    "Database nontransient error",
    "Connection-pool timeout",
    "API load-shed response",
    "Circuit-breaker rejection",
    "Deadlock victim",
    "Cancelled request",
    "Unknown and requiring investigation",
)
SERVER_OUTCOMES = {
    "completed_normally": "Completed normally",
    "completed_after_retry": "Completed after retry",
    "api_timeout": "API timeout",
    "database_command_timeout": "Database command timeout",
    "database_transient_error": "Database transient error",
    "database_connection_timeout": "Database transient error",
    "database_nontransient_error": "Database nontransient error",
    "connection_pool_timeout": "Connection-pool timeout",
    "api_load_shed": "API load-shed response",
    "circuit_breaker_rejection": "Circuit-breaker rejection",
    "deadlock_victim": "Deadlock victim",
    "cancelled_request": "Cancelled request",
    "unknown": "Unknown and requiring investigation",
    "invalid_request": "Unknown and requiring investigation",
    "not_found": "Unknown and requiring investigation",
    "business_failure": "Unknown and requiring investigation",
}


def native_outcome(value: str | None) -> str | None:
    return value if value in SERVER_OUTCOMES else None


def classify(
    status: int | None,
    server_outcome: str | None,
    retry_count: float | None,
    client_timeout: bool = False,
) -> str:
    if client_timeout:
        return OUTCOMES[2]
    # HTTP codes/retry counts cannot establish which layer produced a missing outcome.
    return SERVER_OUTCOMES.get(server_outcome or "", OUTCOMES[-1])


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(events: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    durations = [float(event["elapsed_ms"]) for event in events]
    counts = Counter(str(event["outcome"]) for event in events)
    successes = sum(counts[key] for key in OUTCOMES[:2])
    retry_known = [event for event in events if event.get("retry_count") is not None]
    retries = sum(event["retry_count"] > 0 for event in retry_known)
    cache_known = [event for event in events if isinstance(event.get("cache_hit"), bool)]
    timeout_count = sum(counts[key] for key in (OUTCOMES[2], OUTCOMES[3], OUTCOMES[4], OUTCOMES[7]))
    return {
        "request_count": len(events),
        "read_request_count": sum(event.get("write") is False for event in events),
        "write_request_count": sum(event.get("write") is True for event in events),
        "successful_request_count": successes,
        "failed_request_count": len(events) - successes,
        "retried_request_count": retries if len(retry_known) == len(events) and events else None,
        "retry_observations": retries,
        "retry_coverage": len(retry_known) / len(events) if events else None,
        "timeout_count": timeout_count,
        "load_shed_count": counts[OUTCOMES[8]],
        "p50_ms": percentile(durations, 50),
        "p95_ms": percentile(durations, 95),
        "p99_ms": percentile(durations, 99),
        "throughput_rps": len(events) / seconds if seconds > 0 else None,
        "error_rate": (len(events) - successes) / len(events) if events else None,
        "timeout_rate": timeout_count / len(events) if events else None,
        "retry_rate": retries / len(events) if events and len(retry_known) == len(events) else None,
        "cache_hit_ratio": (
            sum(event["cache_hit"] for event in cache_known) / len(cache_known)
            if cache_known
            else None
        ),
        "database_calls": (
            sum(event["db_calls"] for event in events)
            if events and all(event.get("db_calls") is not None for event in events)
            else None
        ),
        "outcomes": {key: counts[key] for key in OUTCOMES},
    }
