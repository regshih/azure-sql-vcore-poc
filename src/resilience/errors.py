import re
from dataclasses import dataclass

import pyodbc  # type: ignore[import-not-found]
from azure.core.exceptions import ClientAuthenticationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from src.database.repository import (
    EntityNotFound,
    IdempotencyConflict,
    InsufficientStock,
    RepositoryUnavailable,
)


@dataclass(frozen=True)
class Failure:
    outcome: str
    code: str
    retryable: bool
    status: int
    dependency_failure: bool = True


class OperationFailure(Exception):
    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.outcome)
        self.failure = failure


API_TIMEOUT = Failure("api_timeout", "deadline", False, 504, False)
CANCELLED = Failure("cancelled_request", "cancelled", False, 499, False)
LOAD_SHED = Failure("api_load_shed", "bulkhead_full", False, 429, False)
CIRCUIT_OPEN = Failure("circuit_breaker_rejection", "circuit_open", False, 503, False)


def classify(error: Exception) -> Failure:
    if isinstance(error, OperationFailure):
        return error.failure
    if isinstance(error, (EntityNotFound, IdempotencyConflict, InsufficientStock)):
        return Failure("business_failure", "business_rule", False, 409, False)
    if isinstance(error, RepositoryUnavailable):
        return Failure("database_nontransient_error", "repository_unavailable", False, 503)
    if isinstance(error, ClientAuthenticationError):
        return Failure("database_nontransient_error", "authentication", False, 503)
    if isinstance(error, PoolTimeout):
        return Failure("connection_pool_timeout", "pool_timeout", False, 503, False)
    original = error.orig if isinstance(error, DBAPIError) else error
    if not isinstance(original, pyodbc.Error):
        return Failure("unknown", "unclassified", False, 500, False)
    parts = [str(part) for part in original.args]
    codes = {int(value) for part in parts for value in re.findall(r"\((-?\d+)\)", part)}
    state = parts[0][:5] if parts else ""
    if codes & {18456, 18452, 229, 230, 102, 207, 208, 2812, 2601, 2627, 547, 515, 8115}:
        code = str(
            min(codes & {18456, 18452, 229, 230, 102, 207, 208, 2812, 2601, 2627, 547, 515, 8115})
        )
        return Failure("database_nontransient_error", code, False, 503)
    if 1205 in codes:
        return Failure("deadlock_victim", "1205", True, 503)
    if state in {"HYT00", "HYT01"} or -2 in codes:
        return Failure("database_command_timeout", "command_timeout", False, 504)
    transient = codes & {
        40613,
        40197,
        40501,
        10928,
        10929,
        49918,
        49919,
        49920,
        42108,
        42109,
        10053,
        10054,
        10060,
        64,
        233,
    }
    if transient or state.startswith("08"):
        return Failure(
            "database_transient_error", str(min(transient)) if transient else state, True, 503
        )
    return Failure(
        "database_nontransient_error",
        state if re.fullmatch(r"[A-Z0-9]{5}", state) else "sql_error",
        False,
        503,
    )
