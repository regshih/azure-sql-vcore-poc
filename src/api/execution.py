import asyncio
import time
from dataclasses import replace

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from starlette.datastructures import QueryParams
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.database.runtime import RuntimeRepository
from src.resilience.errors import API_TIMEOUT, CANCELLED, OperationFailure
from src.telemetry.context import ExecutionContext, current_context, safe_identifier

OUTCOMES = {
    400: "invalid_request",
    404: "not_found",
    409: "business_failure",
    422: "invalid_request",
    429: "api_load_shed",
    500: "unknown",
    503: "database_nontransient_error",
    504: "api_timeout",
}


class ExecutionMiddleware:
    def __init__(self, app: ASGIApp, runtime: RuntimeRepository) -> None:
        self.app, self.runtime = app, runtime
        self._workers: set[asyncio.Task[None]] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        metadata_refresh = path == "/internal/metadata" and QueryParams(
            scope.get("query_string", b"")
        ).get("refresh_database", "").lower() in {"true", "1", "yes", "on"}
        if scope["type"] != "http" or not (
            path.startswith("/api/") or path == "/readyz" or metadata_refresh
        ):
            await self.app(scope, receive, send)
            return
        if path == "/readyz" and (
            self.runtime.idle or self.runtime.settings.readiness_mode == "process"
        ):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value.decode("latin-1") for key, value in scope["headers"]}
        context = ExecutionContext(
            deadline=time.monotonic() + self.runtime.settings.request_timeout_seconds,
            test_run_id=safe_identifier(headers.get(b"x-test-run-id"), "unassigned"),
            workload_profile=safe_identifier(headers.get(b"x-workload-profile"), "unspecified"),
        )
        context.correlation_id = safe_identifier(
            headers.get(b"x-correlation-id"), context.correlation_id
        )
        token = current_context.set(context)
        method = scope.get("method", "")
        context.http_method = (
            method
            if method in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
            else "UNKNOWN"
        )
        context.request_span = trace.get_tracer("synthetic-poc").start_span(
            "request", kind=SpanKind.SERVER, start_time=context.started_ns
        )
        tracing_token = otel_context.attach(trace.set_span_in_context(context.request_span))
        acquired = False
        detached = False
        terminal_outcome: str | None = None
        messages: list[Message] = []
        outbound: list[Message] = []
        size = 0
        incoming: asyncio.Queue[Message] = asyncio.Queue(maxsize=2)
        disconnected = asyncio.Event()

        async def pump_receive() -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    context.cancel()
                    disconnected.set()
                await incoming.put(message)
                if message["type"] == "http.disconnect":
                    return

        async def request_receive() -> Message:
            return await incoming.get()

        def stop_input() -> None:
            while not incoming.empty():
                incoming.get_nowait()
            incoming.put_nowait({"type": "http.disconnect"})

        async def buffer(message: Message) -> None:
            nonlocal size
            size += len(message.get("body", b""))
            if size > 4 * 1024 * 1024:
                raise RuntimeError("Response exceeds bounded buffer.")
            messages.append(message)

        async def run() -> None:
            nonlocal size
            try:
                await self.app(scope, request_receive, buffer)
            except Exception:
                context.outcome = "unknown"
                messages.clear()
                size = 0
                await JSONResponse({"error": "internal_error"}, status_code=500)(
                    scope, receive, buffer
                )

        def release(task: asyncio.Task[None]) -> None:
            self._workers.discard(task)
            self.runtime.bulkhead.release()
            if not task.cancelled():
                task.exception()
            self.runtime.registry.increment("timed_out_workers_finished")

        pump: asyncio.Task[None] | None = None
        disconnected_wait: asyncio.Task[bool] | None = None
        try:
            await self.runtime.bulkhead.acquire(context)
            acquired = True
            pump = asyncio.create_task(pump_receive())
            disconnected_wait = asyncio.create_task(disconnected.wait())
            task = asyncio.create_task(run())
            done, _ = await asyncio.wait(
                {task, disconnected_wait},
                timeout=context.remaining(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if task not in done:
                detached = True
                self._workers.add(task)
                task.add_done_callback(release)
                context.cancel()
                stop_input()
                raise OperationFailure(CANCELLED if disconnected.is_set() else API_TIMEOUT)
            await task
            outbound = list(messages)
            status = next(
                (
                    int(message["status"])
                    for message in messages
                    if message["type"] == "http.response.start"
                ),
                500,
            )
            context.http_status = status
            if status >= 400 and context.outcome.startswith("completed"):
                context.outcome = OUTCOMES.get(status, "unknown")
            elif status < 400:
                context.outcome = (
                    "completed_after_retry" if context.retry_count else "completed_normally"
                )
        except OperationFailure as error:
            context.outcome = error.failure.outcome
            context.http_status = error.failure.status
            terminal_outcome = error.failure.outcome

            async def failure_buffer(message: Message) -> None:
                outbound.append(message)

            await JSONResponse(
                {"error": error.failure.outcome, "outcome": error.failure.outcome},
                status_code=error.failure.status,
                headers={"Retry-After": "1"} if error.failure.status == 429 else None,
            )(scope, receive, failure_buffer)
        except asyncio.CancelledError:
            context.cancel()
            stop_input()
            context.outcome = "cancelled_request"
            context.http_status = 499
            terminal_outcome = "cancelled_request"
            if acquired and not detached and not task.done():
                detached = True
                self._workers.add(task)
                task.add_done_callback(release)
            raise
        finally:
            for pending in (pump, disconnected_wait):
                if pending is not None:
                    pending.cancel()
            await asyncio.gather(
                *(pending for pending in (pump, disconnected_wait) if pending is not None),
                return_exceptions=True,
            )
            elapsed = (time.monotonic() - context.started) * 1000
            if acquired and not detached:
                self.runtime.bulkhead.release()
            completed_context = replace(context)
            if terminal_outcome is not None:
                completed_context.outcome = terminal_outcome
            self.runtime.registry.completed(completed_context, elapsed)
            otel_context.detach(tracing_token)
            current_context.reset(token)
        response_headers = {
            "x-correlation-id": completed_context.correlation_id,
            "x-test-run-id": completed_context.test_run_id,
            "x-poc-outcome": completed_context.outcome,
            "x-retry-count": str(completed_context.retry_count),
            "x-db-calls": str(completed_context.db_calls),
            "x-cache-hit": str(completed_context.cache_hit).lower(),
            "x-pool-wait-ms": f"{completed_context.pool_wait_ms:.3f}",
            "x-elapsed-ms": f"{elapsed:.3f}",
        }
        for message in outbound:
            if message["type"] == "http.response.start":
                existing: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                existing.extend(
                    (key.encode("ascii"), value.encode("ascii"))
                    for key, value in response_headers.items()
                )
                message["headers"] = existing
            await send(message)
