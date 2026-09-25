import re
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

from opentelemetry.trace import Span

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def safe_identifier(value: str | None, fallback: str) -> str:
    return value if value is not None and SAFE_IDENTIFIER.fullmatch(value) else fallback


@dataclass
class ExecutionContext:
    deadline: float
    test_run_id: str = "unassigned"
    workload_profile: str = "unspecified"
    correlation_id: str = field(default_factory=lambda: uuid4().hex)
    started: float = field(default_factory=time.monotonic)
    started_ns: int = field(default_factory=time.time_ns)
    operation: str = "request"
    http_method: str = "UNKNOWN"
    http_status: int = 500
    request_span: Span | None = field(default=None, repr=False)
    retry_count: int = 0
    attempt: int = 0
    db_calls: int = 0
    pool_wait_ms: float = 0
    dependency_ms: float = 0
    cache_hit: bool = False
    outcome: str = "completed_normally"
    cancelled: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancel_command: Callable[[], None] | None = field(default=None, repr=False)

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def register_cancel(self, callback: Callable[[], None] | None) -> None:
        with self._lock:
            self._cancel_command = callback

    def cancel(self) -> None:
        self.cancelled.set()
        with self._lock:
            callback = self._cancel_command
        if callback is not None:
            # Driver cancellation is best effort and must not block the ASGI event loop.
            threading.Thread(target=callback, daemon=True, name="sql-command-cancel").start()


current_context: ContextVar[ExecutionContext | None] = ContextVar("execution_context", default=None)
