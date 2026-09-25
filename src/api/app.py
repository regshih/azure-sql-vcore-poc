import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from src.api.dependencies import RepositoryDependency
from src.api.execution import ExecutionMiddleware
from src.api.internal import router as internal_router
from src.api.pagination import InvalidCursor
from src.api.routes import router
from src.configuration.settings import Settings, assert_local_memory_allowed
from src.database.factory import build_repository
from src.database.memory import InMemoryRepository
from src.database.repository import (
    EntityNotFound,
    IdempotencyConflict,
    InsufficientStock,
    Repository,
    RepositoryUnavailable,
)
from src.database.runtime import RuntimeRepository
from src.resilience.errors import OperationFailure, classify
from src.telemetry.context import current_context
from src.telemetry.metrics import Registry, configure_telemetry

logger = logging.getLogger("poc.telemetry")


def create_app(settings: Settings | None = None, repository: Repository | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    selected_repository = repository if repository is not None else build_repository(configuration)
    if isinstance(selected_repository, InMemoryRepository):
        assert_local_memory_allowed(configuration)
    configure_telemetry(configuration)
    registry = Registry(configuration)
    runtime = RuntimeRepository(selected_repository, configuration, registry)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        runtime.close()

    app = FastAPI(
        title="Synthetic Business API",
        version="0.2.0",
        description="Synthetic Azure SQL workload evaluation API.",
        lifespan=lifespan,
    )
    app.state.repository = runtime
    app.state.runtime = runtime
    app.state.settings = configuration

    @app.middleware("http")
    async def sanitize_unexpected_failures(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.error('{"event":"request_failed","category":"unknown"}')
            return JSONResponse(status_code=500, content={"error": "internal_error"})

    async def invalid_request(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "invalid_request"})

    async def domain_failure(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, EntityNotFound):
            status, code = 404, "not_found"
        elif isinstance(exc, IdempotencyConflict):
            status, code = 409, "idempotency_conflict"
        elif isinstance(exc, InsufficientStock):
            status, code = 409, "insufficient_stock"
        elif isinstance(exc, InvalidCursor):
            status, code = 400, "invalid_cursor"
        else:
            status, code = 503, "repository_unavailable"
            logger.warning("repository_unavailable")
        return JSONResponse(status_code=status, content={"error": code})

    app.add_exception_handler(RequestValidationError, invalid_request)

    async def operation_failure(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, OperationFailure):
            return JSONResponse(status_code=500, content={"error": "internal_error"})
        content = {"error": exc.failure.outcome, "outcome": exc.failure.outcome}
        if exc.failure.code == "repository_unavailable":
            content = {"error": "repository_unavailable"}
        elif exc.failure.outcome == "unknown":
            content = {"error": "internal_error"}
        return JSONResponse(status_code=exc.failure.status, content=content)

    app.add_exception_handler(OperationFailure, operation_failure)
    for exception_type in (
        EntityNotFound,
        IdempotencyConflict,
        InsufficientStock,
        RepositoryUnavailable,
        InvalidCursor,
    ):
        app.add_exception_handler(exception_type, domain_failure)

    @app.get("/healthz", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"], response_model=None)
    def ready(repository: RepositoryDependency) -> JSONResponse:
        try:
            repository.check_ready()
        except Exception as error:
            failure = classify(error)
            context = current_context.get()
            if context is not None:
                context.outcome = failure.outcome
            logger.warning(
                json.dumps(
                    {"event": "readiness_failed", "category": failure.outcome, "code": failure.code}
                )
            )
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return JSONResponse(status_code=200, content={"status": "ready"})

    app.include_router(router)
    app.include_router(internal_router)
    app.add_middleware(ExecutionMiddleware, runtime=runtime)
    if configuration.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(configuration.cors_allow_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=[
                "Content-Type",
                "Idempotency-Key",
                "X-Test-Run-Id",
                "X-Workload-Profile",
                "X-Correlation-ID",
            ],
            expose_headers=[
                "Location",
                "Idempotency-Replayed",
                "X-POC-Outcome",
                "X-Retry-Count",
                "X-DB-Calls",
                "X-Cache-Hit",
                "X-Pool-Wait-Ms",
                "X-Elapsed-Ms",
                "X-Correlation-ID",
            ],
        )
    return app
