import asyncio
import random
import threading
import time
from collections.abc import Callable

import pyodbc  # type: ignore[import-not-found]
from azure.core.exceptions import ClientAuthenticationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from src.configuration.settings import Settings
from src.database.repository import (
    EntityNotFound,
    IdempotencyConflict,
    InsufficientStock,
    RepositoryUnavailable,
)
from src.resilience.errors import (
    API_TIMEOUT,
    CANCELLED,
    CIRCUIT_OPEN,
    LOAD_SHED,
    OperationFailure,
    classify,
)
from src.telemetry.context import ExecutionContext
from src.telemetry.metrics import Registry


class RetryBudget:
    def __init__(
        self, capacity: int, refill: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.capacity, self.refill, self.clock = capacity, refill, clock
        self._tokens = float(capacity)
        self._updated = clock()
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            now = self.clock()
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.refill)
            self._updated = now
            if self._tokens < 1:
                return False
            self._tokens -= 1
            return True


class CircuitBreaker:
    def __init__(
        self, threshold: int, reset: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.threshold, self.reset, self.clock = threshold, reset, clock
        self._failures = 0
        self._opened: float | None = None
        self._probe = False
        self._generation = 0
        self._lock = threading.Lock()

    def enter(self) -> tuple[int, bool]:
        with self._lock:
            if self._opened is not None:
                if self.clock() - self._opened < self.reset or self._probe:
                    raise OperationFailure(CIRCUIT_OPEN)
                self._probe = True
                return self._generation, True
            return self._generation, False

    def finish(self, ticket: tuple[int, bool], failed: bool | None) -> None:
        with self._lock:
            if ticket[0] != self._generation:
                return
            if failed is None:
                if ticket[1]:
                    self._probe = False
                return
            if failed:
                self._failures += 1
                if ticket[1] or self._failures >= self.threshold:
                    self._opened = self.clock()
                    self._generation += 1
                    self._probe = False
            else:
                self._failures = 0
                if ticket[1]:
                    self._opened = None
                    self._probe = False
                    self._generation += 1

    def snapshot(self) -> str:
        with self._lock:
            return "half_open" if self._probe else "open" if self._opened is not None else "closed"


class Bulkhead:
    def __init__(self, concurrency: int, queue: int, queue_timeout: float) -> None:
        self.limit, self.queue_limit, self.queue_timeout = concurrency, queue, queue_timeout
        self.active = self.queued = 0
        self.suspended = False
        self._lock = threading.Lock()

    async def acquire(self, context: ExecutionContext) -> None:
        queued = False
        started = time.monotonic()
        try:
            while True:
                with self._lock:
                    if self.suspended:
                        raise OperationFailure(LOAD_SHED)
                    if context.cancelled.is_set() or context.remaining() <= 0:
                        raise OperationFailure(API_TIMEOUT)
                    if self.active < self.limit:
                        self.active += 1
                        return
                    if not queued:
                        if self.queued >= self.queue_limit:
                            raise OperationFailure(LOAD_SHED)
                        self.queued += 1
                        queued = True
                if time.monotonic() - started >= self.queue_timeout:
                    raise OperationFailure(LOAD_SHED)
                await asyncio.sleep(min(0.01, context.remaining()))
        finally:
            if queued:
                with self._lock:
                    self.queued -= 1

    def release(self) -> None:
        with self._lock:
            self.active -= 1

    def suspend(self, value: bool) -> None:
        with self._lock:
            self.suspended = value

    def snapshot(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "active_requests": self.active,
                "queue_depth": self.queued,
                "admission_suspended": self.suspended,
                "concurrency_limit": self.limit,
            }


class Resilience:
    def __init__(self, settings: Settings, registry: Registry) -> None:
        self.settings, self.registry = settings, registry
        self.budget = RetryBudget(
            settings.retry_budget_capacity, settings.retry_budget_refill_per_second
        )
        self.circuit = CircuitBreaker(
            settings.circuit_failure_threshold, settings.circuit_reset_seconds
        )

    def execute[T](self, operation: Callable[[], T], context: ExecutionContext) -> T:
        ticket = self.circuit.enter()
        dependency_failed: bool | None = None
        try:
            for attempt in range(1, self.settings.retry_max_attempts + 1):
                context.attempt = attempt
                if context.cancelled.is_set():
                    raise OperationFailure(CANCELLED)
                if context.remaining() <= 0:
                    raise OperationFailure(API_TIMEOUT)
                self.registry.increment("repository_attempts")
                try:
                    value = operation()
                except (EntityNotFound, IdempotencyConflict, InsufficientStock):
                    dependency_failed = False
                    raise
                except (
                    pyodbc.Error,
                    DBAPIError,
                    PoolTimeout,
                    ClientAuthenticationError,
                    RepositoryUnavailable,
                    OperationFailure,
                ) as error:
                    failure = CANCELLED if context.cancelled.is_set() else classify(error)
                    dependency_failed = True if failure.dependency_failure else None
                    if failure.dependency_failure:
                        self.registry.increment("dependency_failures")
                    ceiling = min(
                        self.settings.retry_max_delay_seconds,
                        self.settings.retry_base_delay_seconds * 2 ** (attempt - 1),
                    )
                    # Retry jitter is not used for secrets or identifiers.
                    delay = random.uniform(0, ceiling)  # nosec B311
                    retry = (
                        failure.retryable
                        and attempt < self.settings.retry_max_attempts
                        and context.remaining() > delay + 0.05
                        and not context.cancelled.is_set()
                        and self.budget.take()
                    )
                    self.registry.event(
                        context,
                        category=failure.outcome,
                        code=failure.code,
                        retry=retry,
                        delay=delay if retry else 0,
                    )
                    if not retry:
                        context.outcome = failure.outcome
                        raise OperationFailure(failure) from None
                    self.registry.increment("retries")
                    context.retry_count += 1
                    if context.cancelled.wait(delay):
                        raise OperationFailure(CANCELLED) from None
                else:
                    dependency_failed = False
                    if context.cancelled.is_set() or context.remaining() <= 0:
                        raise OperationFailure(API_TIMEOUT)
                    context.outcome = (
                        "completed_after_retry" if context.retry_count else "completed_normally"
                    )
                    return value
            raise AssertionError("Unreachable retry state")
        finally:
            self.circuit.finish(ticket, dependency_failed)
