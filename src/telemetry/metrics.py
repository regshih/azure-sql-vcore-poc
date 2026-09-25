import json
import logging
import math
import threading
import time
from collections import Counter, deque
from datetime import UTC, datetime
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from src.configuration.settings import Settings
from src.telemetry.context import ExecutionContext

logger = logging.getLogger("poc.telemetry")


def silence_dependency_logs() -> None:
    # Native/SDK exceptions can contain endpoints or SQL text; emit our classifications instead.
    for name in ("azure", "sqlalchemy", "urllib3", "httpx", "httpcore", "redis"):
        dependency_logger = logging.getLogger(name)
        dependency_logger.setLevel(logging.CRITICAL + 1)
        dependency_logger.propagate = False
        if not dependency_logger.handlers:
            dependency_logger.addHandler(logging.NullHandler())


def configure_telemetry(settings: Settings) -> None:
    silence_dependency_logs()
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    if settings.applicationinsights_connection_string is None:
        return
    # Manual exporters only. No HTTP/SQL auto-instrumentation, log exporter or parameters.
    from azure.monitor.opentelemetry.exporter import (
        AzureMonitorMetricExporter,
        AzureMonitorTraceExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    connection = settings.applicationinsights_connection_string.get_secret_value()
    resource = Resource.create({"service.name": "synthetic-business-api"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=connection))
    )
    trace.set_tracer_provider(provider)
    metrics.set_meter_provider(
        MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(
                    AzureMonitorMetricExporter(connection_string=connection)
                )
            ],
        )
    )


class Registry:
    def __init__(self, settings: Settings) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._counts: Counter[str] = Counter()
        self._latencies: deque[float] = deque(maxlen=2048)
        self.tags = {
            "database_configuration": settings.database_profile,
            "compute_tier": settings.compute_tier,
            "vcore_configuration": settings.vcore_configuration,
            "deployment_region": settings.deployment_region,
            "application_version": settings.application_version,
            "schema_version": settings.schema_version,
            "dataset_version": settings.dataset_version,
            "database_target_role": settings.database_target_role,
        }
        meter = metrics.get_meter("synthetic-poc")
        self._requests = meter.create_counter("poc.requests")
        self._duration = meter.create_histogram("poc.request.duration", unit="ms")
        self._dependency = meter.create_histogram("poc.database.duration", unit="ms")
        self._events = meter.create_counter("poc.events")

    def increment(self, event: str, count: int = 1) -> None:
        with self._lock:
            self._counts[event] += count
        self._events.add(count, {"event": event})

    def event(
        self,
        context: ExecutionContext,
        *,
        category: str,
        code: str,
        retry: bool = False,
        delay: float = 0,
        final: bool = False,
    ) -> None:
        payload = {
            "event": "operation_final" if final else "operation_attempt",
            "timestamp": datetime.now(UTC).isoformat(),
            "test_run_id": context.test_run_id,
            "workload_profile": context.workload_profile,
            "correlation_id": context.correlation_id,
            "operation": context.operation,
            "attempt": context.attempt,
            "error_category": category,
            "error_code": code,
            "retry_decision": retry,
            "retry_delay_ms": round(delay * 1000, 3),
            "final_result": context.outcome if final else "pending",
            "elapsed_ms": round((time.monotonic() - context.started) * 1000, 3),
            "retry_count": context.retry_count,
            "db_calls": context.db_calls,
            "pool_wait_ms": round(context.pool_wait_ms, 3),
            "dependency_ms": round(context.dependency_ms, 3),
            "cache_hit": context.cache_hit,
            **self.tags,
        }
        logger.info(json.dumps(payload, separators=(",", ":"), allow_nan=False))

    def completed(self, context: ExecutionContext, elapsed_ms: float) -> None:
        with self._lock:
            self._counts["requests"] += 1
            self._counts[context.outcome] += 1
            self._counts["database_calls"] += context.db_calls
            self._latencies.append(elapsed_ms)
        attributes: dict[str, str | bool] = {
            "operation": context.operation,
            "outcome": context.outcome,
            "cache_hit": context.cache_hit,
            **self.tags,
        }
        self._requests.add(1, attributes)
        self._duration.record(elapsed_ms, attributes)
        self._dependency.record(context.dependency_ms, {"operation": context.operation})
        span = context.request_span
        if span is None:
            span = trace.get_tracer("synthetic-poc").start_span(
                context.operation, kind=SpanKind.SERVER, start_time=context.started_ns
            )
        span.update_name(context.operation)
        span.set_attributes(
            {
                **attributes,
                "correlation_id": context.correlation_id,
                "test_run_id": context.test_run_id,
                "retry_count": context.retry_count,
                "workload_profile": context.workload_profile,
                "db_calls": context.db_calls,
                "pool_wait_ms": context.pool_wait_ms,
                "http.request.method": context.http_method,
                "http.response.status_code": context.http_status,
                "http.method": context.http_method,
                "http.status_code": context.http_status,
            }
        )
        if not context.outcome.startswith("completed"):
            span.set_status(Status(StatusCode.ERROR))
        span.end(end_time=context.started_ns + int(elapsed_ms * 1000000))
        self.event(context, category=context.outcome, code="none", final=True)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts = dict(self._counts)
            values = sorted(self._latencies)

        def percentile(fraction: float) -> float | None:
            return values[max(0, math.ceil(len(values) * fraction) - 1)] if values else None

        cache_requests = counts.get("cache_requests", 0)
        uptime = time.monotonic() - self._started
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_seconds": uptime,
            "average_rps_since_start": counts.get("requests", 0) / uptime if uptime else 0,
            "counts": counts,
            "latency_window": "last_2048_completed_requests",
            "p50_ms": percentile(0.5),
            "p95_ms": percentile(0.95),
            "p99_ms": percentile(0.99),
            "cache_hit_ratio": counts.get("cache_hits", 0) / cache_requests
            if cache_requests
            else 0,
            "metadata": self.tags,
        }
