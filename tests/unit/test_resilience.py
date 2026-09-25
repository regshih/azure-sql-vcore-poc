import asyncio
import threading
import time
from unittest.mock import patch

import pyodbc
import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from src.configuration.settings import Settings
from src.resilience.errors import OperationFailure, classify
from src.resilience.policies import Bulkhead, CircuitBreaker, Resilience, RetryBudget
from src.telemetry.context import ExecutionContext
from src.telemetry.metrics import Registry


@pytest.mark.parametrize(
    "state,code,outcome,retry",
    [
        ("40001", 1205, "deadlock_victim", True),
        ("08S01", 10054, "database_transient_error", True),
        ("42000", 40501, "database_transient_error", True),
        ("42000", 40613, "database_transient_error", True),
        ("28000", 18456, "database_nontransient_error", False),
        ("42000", 229, "database_nontransient_error", False),
        ("42000", 208, "database_nontransient_error", False),
        ("23000", 2627, "database_nontransient_error", False),
        ("HYT00", 0, "database_command_timeout", False),
    ],
)
def test_sql_failure_classification(state: str, code: int, outcome: str, retry: bool) -> None:
    error = pyodbc.Error(state, f"DO_NOT_LOG_RAW_MESSAGE ({code})")
    failure = classify(DBAPIError("DO_NOT_LOG_SQL", {}, error))
    assert failure.outcome == outcome
    assert failure.retryable is retry
    assert "DO_NOT_LOG" not in failure.code


def test_pool_timeout_not_retried() -> None:
    assert classify(PoolTimeout("pool-full")).outcome == "connection_pool_timeout"
    assert not classify(PoolTimeout()).retryable


def test_budget_refill_is_shared_and_bounded() -> None:
    now = [0.0]
    budget = RetryBudget(2, 1, lambda: now[0])
    assert budget.take() and budget.take()
    assert not budget.take()
    now[0] = 0.5
    assert not budget.take()
    now[0] = 1.0
    assert budget.take()
    assert not budget.take()


def test_circuit_half_open_allows_one_probe_and_ignores_stale_success() -> None:
    now = [0.0]
    breaker = CircuitBreaker(1, 5, lambda: now[0])
    stale = breaker.enter()
    breaker.finish(breaker.enter(), True)
    breaker.finish(stale, False)
    with pytest.raises(OperationFailure):
        breaker.enter()
    now[0] = 6
    probe = breaker.enter()
    assert breaker.snapshot() == "half_open"
    with pytest.raises(OperationFailure):
        breaker.enter()
    breaker.finish(probe, False)
    assert breaker.snapshot() == "closed"


def test_abandoned_half_open_probe_does_not_claim_recovery() -> None:
    now = [0.0]
    breaker = CircuitBreaker(1, 5, lambda: now[0])
    breaker.finish(breaker.enter(), True)
    now[0] = 6
    probe = breaker.enter()
    breaker.finish(probe, None)
    assert breaker.snapshot() == "open"
    assert breaker.enter()[1] is True


def test_retries_jitter_then_reconnect_success() -> None:
    settings = Settings(retry_base_delay_seconds=0.001, retry_max_delay_seconds=0.01)
    policy = Resilience(settings, Registry(settings))
    context = ExecutionContext(time.monotonic() + 5)
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise pyodbc.Error("08S01", "simulated disconnect (10054)")
        return "reconnected"

    with patch("src.resilience.policies.random.uniform", return_value=0) as jitter:
        assert policy.execute(operation, context) == "reconnected"
    assert jitter.call_args_list[0].args == (0, 0.001)
    assert jitter.call_args_list[1].args == (0, 0.002)
    assert context.retry_count == 2
    assert context.outcome == "completed_after_retry"


def test_retry_budget_prevents_amplification() -> None:
    settings = Settings(retry_budget_capacity=0)
    policy = Resilience(settings, Registry(settings))
    context = ExecutionContext(time.monotonic() + 5)

    def unavailable() -> None:
        raise pyodbc.Error("08S01", "simulated (10054)")

    with pytest.raises(OperationFailure):
        policy.execute(unavailable, context)
    assert context.attempt == 1
    assert context.retry_count == 0


def test_cancellation_prevents_attempt() -> None:
    settings = Settings()
    policy = Resilience(settings, Registry(settings))
    context = ExecutionContext(time.monotonic() + 5)
    context.cancelled.set()
    with pytest.raises(OperationFailure, match="cancelled"):
        policy.execute(lambda: pytest.fail("Must not execute"), context)


def test_bulkhead_queue_and_shedding() -> None:
    async def exercise() -> None:
        bulkhead = Bulkhead(1, 1, 0.5)
        context = ExecutionContext(time.monotonic() + 2)
        await bulkhead.acquire(context)
        waiting = asyncio.create_task(bulkhead.acquire(context))
        await asyncio.sleep(0.02)
        assert bulkhead.snapshot()["queue_depth"] == 1
        with pytest.raises(OperationFailure, match="api_load_shed"):
            await bulkhead.acquire(context)
        bulkhead.release()
        await waiting
        assert bulkhead.snapshot()["active_requests"] == 1
        bulkhead.release()
        assert bulkhead.snapshot()["active_requests"] == 0

    asyncio.run(exercise())


def test_retry_wait_is_cancellation_aware() -> None:
    settings = Settings(retry_base_delay_seconds=2, retry_max_delay_seconds=2)
    policy = Resilience(settings, Registry(settings))
    context = ExecutionContext(time.monotonic() + 5)
    timer = threading.Timer(0.03, context.cancelled.set)

    def unavailable() -> None:
        raise pyodbc.Error("08S01", "simulated (10054)")

    timer.start()
    try:
        with patch("src.resilience.policies.random.uniform", return_value=1):
            with pytest.raises(OperationFailure, match="cancelled"):
                policy.execute(unavailable, context)
    finally:
        timer.cancel()
    assert context.attempt == 1
