import asyncio
import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from azure.core.exceptions import AzureError
from pydantic import BaseModel, ValidationError
from redis.exceptions import RedisError

from src.cache.backends import Cache, MemoryCache, RedisCache
from src.configuration.settings import Settings, assert_local_memory_allowed
from src.database.connection import credential_for
from src.database.memory import InMemoryRepository
from src.database.models import (
    Activity,
    BatchResponse,
    Dashboard,
    Product,
    WorkItem,
    WorkItemCreate,
)
from src.database.repository import (
    CreationResult,
    Page,
    PageWindow,
    ProductFilter,
    Repository,
    RepositoryUnavailable,
    WorkItemFilter,
)
from src.database.sql_repository import SqlRepository
from src.resilience.errors import API_TIMEOUT, OperationFailure
from src.resilience.policies import Bulkhead, Resilience
from src.telemetry.context import ExecutionContext, current_context
from src.telemetry.metrics import Registry

CACHE_ERRORS = (RedisError, AzureError, OSError, ValueError, RuntimeError, ValidationError)


class RuntimeRepository:
    def __init__(self, repository: Repository, settings: Settings, registry: Registry) -> None:
        self.repository, self.settings, self.registry = repository, settings, registry
        self.resilience = Resilience(settings, registry)
        self.bulkhead = Bulkhead(
            settings.max_concurrent_requests,
            settings.max_queued_requests,
            settings.queue_timeout_seconds,
        )
        self.idle = False
        self.instance_id = uuid4().hex
        self._configuration_version = 0
        self._dataset_metadata: dict[str, Any] = {
            "schema_version": None,
            "dataset_version": None,
            "product_count": None,
            "work_item_count": None,
            "tuning_mode": None,
            "counts_source": "unknown",
            "dataset_kind": None,
            "dataset_state": None,
            "dataset_state_fingerprint": None,
            "dataset_fingerprint_scope": "unknown",
            "metadata_observed_at": None,
        }
        if isinstance(repository, InMemoryRepository):
            dashboard = repository.dashboard()
            self._dataset_metadata.update(
                {
                    "dataset_version": "synthetic-memory-v1",
                    "product_count": dashboard.product_count,
                    "work_item_count": dashboard.work_item_count,
                    "counts_source": "local_memory_initialization",
                    "metadata_observed_at": datetime.now(UTC).isoformat(),
                }
            )
        self._cache_enabled = settings.cache_backend != "disabled"
        self._maintenance_lock = asyncio.Lock()
        self.cache: Cache | None = None
        self._cache_credential = None
        if settings.cache_backend == "memory":
            assert_local_memory_allowed(settings)
            self.cache = MemoryCache(settings.cache_ttl_seconds, settings.cache_max_entries)
        elif settings.cache_backend == "redis":
            self._cache_credential = credential_for(settings)
            namespace = (
                "poc:"
                + hashlib.sha256(
                    f"{settings.sql_server}:{settings.sql_database}".encode()
                ).hexdigest()[:16]
            )
            self.cache = RedisCache(settings, self._cache_credential, namespace)

    def _run[T](self, name: str, operation: Callable[[], T]) -> T:
        context = current_context.get()
        own_context = context is None
        if context is None:
            context = ExecutionContext(time.monotonic() + self.settings.request_timeout_seconds)
        context.operation = name
        token = current_context.set(context) if own_context else None
        try:
            return self.resilience.execute(operation, context)
        finally:
            if token is not None:
                current_context.reset(token)

    def _cached[T: BaseModel](self, key: str, model: type[T], operation: Callable[[], T]) -> T:
        context = current_context.get()
        if context is not None:
            context.operation = "product_lookup" if key.startswith("product:") else "dashboard"
        cache = self.cache
        if cache is None or not self._cache_enabled:
            return operation()
        self.registry.increment("cache_requests")
        generation: str | None = None
        try:
            generation, data = cache.read(key)
            if data is not None:
                result = model.model_validate_json(data)
                self.registry.increment("cache_hits")
                self.registry.increment("database_queries_avoided")
                context = current_context.get()
                if context is not None:
                    context.cache_hit = True
                return result
        except CACHE_ERRORS:
            self.registry.increment("cache_errors")
        self.registry.increment("cache_misses")
        result = operation()
        if generation is not None:
            try:
                cache.write(generation, key, result.model_dump_json().encode())
            except CACHE_ERRORS:
                self.registry.increment("cache_errors")
        return result

    def check_ready(self) -> None:
        if self.idle or self.settings.readiness_mode == "process":
            return
        self._run("readiness", self.repository.check_ready)

    def get_product(self, product_id: int) -> Product:
        return self._cached(
            f"product:{product_id}",
            Product,
            lambda: self._run("product_lookup", lambda: self.repository.get_product(product_id)),
        )

    def list_products(self, filters: ProductFilter, window: PageWindow) -> Page[Product]:
        return self._run("product_filter", lambda: self.repository.list_products(filters, window))

    def batch_products(self, identifiers: tuple[int, ...]) -> BatchResponse[Product]:
        return self._run("product_batch", lambda: self.repository.batch_products(identifiers))

    def get_work_item(self, work_item_id: int) -> WorkItem:
        return self._run("work_item_lookup", lambda: self.repository.get_work_item(work_item_id))

    def list_work_items(self, filters: WorkItemFilter, window: PageWindow) -> Page[WorkItem]:
        return self._run(
            "work_item_filter", lambda: self.repository.list_work_items(filters, window)
        )

    def batch_work_items(self, identifiers: tuple[int, ...]) -> BatchResponse[WorkItem]:
        return self._run("work_item_batch", lambda: self.repository.batch_work_items(identifiers))

    def create_work_item(self, command: WorkItemCreate, key: str) -> CreationResult:
        result = self._run(
            "work_item_create", lambda: self.repository.create_work_item(command, key)
        )
        # Even replays invalidate: an earlier ambiguous commit may have bypassed invalidation.
        if self.cache is not None:
            try:
                self.cache.invalidate()
                self.registry.increment("cache_invalidations")
            except CACHE_ERRORS:
                self.registry.increment("cache_invalidation_failures")
        return result

    def dashboard(self) -> Dashboard:
        return self._cached(
            "dashboard", Dashboard, lambda: self._run("dashboard", self.repository.dashboard)
        )

    def recent_activity(self, window: PageWindow) -> Page[Activity]:
        return self._run("recent_activity", lambda: self.repository.recent_activity(window))

    def diagnostic(self, department: str, delay_seconds: int, poor_pooling: bool) -> dict[str, Any]:
        repository = self.repository
        if not isinstance(repository, SqlRepository):
            raise RepositoryUnavailable
        return self._run(
            "controlled_diagnostic",
            lambda: repository.diagnostic(department, delay_seconds, poor_pooling),
        )

    async def enter_idle(self) -> None:
        async with self._maintenance_lock:
            await self._drain()

    async def _drain(self) -> None:
        self.idle = True
        self.bulkhead.suspend(True)
        await self._wait_for_workers()
        if isinstance(self.repository, SqlRepository):
            await asyncio.to_thread(self.repository.dispose)
        if self.cache is not None:
            try:
                await asyncio.to_thread(self.cache.invalidate)
            except CACHE_ERRORS:
                self.registry.increment("cache_invalidation_failures")

    async def _wait_for_workers(self) -> None:
        deadline = time.monotonic() + self.settings.request_timeout_seconds + 5
        while int(self.bulkhead.snapshot()["active_requests"]) > 0:
            if time.monotonic() >= deadline:
                # Admission remains suspended. Caller can retry draining; never claim zero sessions.
                raise OperationFailure(API_TIMEOUT)
            await asyncio.sleep(0.01)

    async def resume(self) -> None:
        async with self._maintenance_lock:
            self.idle = False
            self.bulkhead.suspend(False)

    def configuration(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "version": self._configuration_version,
            "cache_enabled": self._cache_enabled,
            "cache_backend": self.settings.cache_backend,
            "cache_ttl_seconds": self.settings.cache_ttl_seconds,
        }

    async def configure_cache(self, enabled: bool, expected_version: int) -> dict[str, Any]:
        async with self._maintenance_lock:
            if expected_version != self._configuration_version:
                raise ValueError("configuration_version_conflict")
            if enabled and self.cache is None:
                raise ValueError("cache_backend_not_configured")
            previous = self.configuration()
            if self._cache_enabled == enabled:
                return {"previous": previous, "current": previous}
            was_idle = self.idle
            self.idle = True
            self.bulkhead.suspend(True)
            # On a drain failure admission remains suspended for a subsequent maintenance retry.
            await self._wait_for_workers()
            try:
                if self.cache is not None:
                    try:
                        await asyncio.to_thread(self.cache.invalidate)
                    except CACHE_ERRORS:
                        self.registry.increment("cache_invalidation_failures")
                        raise ValueError("cache_reset_failed") from None
                self._cache_enabled = enabled
                self._configuration_version += 1
                self.registry.increment("runtime_configuration_changes")
                return {"previous": previous, "current": self.configuration()}
            finally:
                self.idle = was_idle
                self.bulkhead.suspend(was_idle)

    def metadata(self) -> dict[str, Any]:
        return {
            "application": "synthetic-azure-sql-vcore-poc",
            "poc_mode": self.settings.poc_mode,
            "poc_marker": "sql-vcore" if self.settings.poc_mode else None,
            "environment": "poc" if self.settings.poc_mode else None,
            "marker_source": "application_configuration_not_azure_resource_validation",
            "contract_version": 1,
            "synthetic_data_only": True,
            "instance_id": self.instance_id,
            "repository_backend": self.settings.repository_backend,
            "sql_adapter_configured": isinstance(self.repository, SqlRepository),
            "database_validation": (
                "metadata_query_succeeded"
                if isinstance(self.repository, SqlRepository)
                and self._dataset_metadata["metadata_observed_at"] is not None
                else "not_performed_by_metadata_endpoint"
            ),
            "unsafe_tests_enabled": self.settings.poc_mode and self.settings.allow_unsafe_tests,
            "control_scope": "single_process",
            "readiness_mode": "process" if self.idle else self.settings.readiness_mode,
            "idle": self.idle,
            "configuration": self.configuration(),
            "application_version": self.settings.application_version,
            "cache_mode": self.settings.cache_backend if self._cache_enabled else "disabled",
            "workload_configuration": {
                "request_timeout_seconds": self.settings.request_timeout_seconds,
                "max_concurrent_requests": self.settings.max_concurrent_requests,
                "max_queued_requests": self.settings.max_queued_requests,
                "retry_max_attempts": self.settings.retry_max_attempts,
                "sql_pool_size": self.settings.sql_pool_size,
                "sql_pool_max_overflow": self.settings.sql_pool_max_overflow,
                "sql_command_timeout_seconds": self.settings.sql_command_timeout_seconds,
            },
            **dict(self._dataset_metadata),
            "telemetry": dict(self.registry.tags),
        }

    def refresh_metadata(self) -> dict[str, Any]:
        repository = self.repository
        if isinstance(repository, SqlRepository):
            self._dataset_metadata = self._run("metadata_refresh", repository.dataset_metadata)
        return self.metadata()

    def snapshot(self) -> dict[str, Any]:
        pool = self.repository.pool_metrics() if isinstance(self.repository, SqlRepository) else {}
        cache_details = self.cache.snapshot() if isinstance(self.cache, MemoryCache) else {}
        return {
            "instance_id": self.instance_id,
            "counter_scope": "process_lifetime_use_isolated_baseline_end_deltas",
            **self.registry.snapshot(),
            **self.bulkhead.snapshot(),
            **pool,
            "cache": {
                "backend": self.settings.cache_backend,
                "ttl_seconds": self.settings.cache_ttl_seconds,
                "enabled": self._cache_enabled,
                **cache_details,
            },
            "circuit_state": self.resilience.circuit.snapshot(),
            "idle": self.idle,
            "readiness_mode": "process" if self.idle else self.settings.readiness_mode,
        }

    def close(self) -> None:
        if isinstance(self.repository, SqlRepository):
            self.repository.close()
        if self.cache is not None:
            self.cache.close()
        if self._cache_credential is not None:
            self._cache_credential.close()
