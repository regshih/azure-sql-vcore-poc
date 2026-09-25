import math
import struct
import time
from collections.abc import Callable
from typing import Any

import pyodbc  # type: ignore[import-not-found]
from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from src.configuration.settings import Settings
from src.resilience.errors import API_TIMEOUT, Failure, OperationFailure, classify
from src.telemetry.context import current_context

# Configure once, before any physical connection. SQLAlchemy is the sole pooling layer.
pyodbc.pooling = False
SQL_TOKEN_ATTRIBUTE = 1256
SQL_SCOPE = "https://database.windows.net/.default"


def credential_for(settings: Settings) -> DefaultAzureCredential:
    managed_only = settings.app_environment == "production"
    return DefaultAzureCredential(
        managed_identity_client_id=settings.managed_identity_client_id,
        exclude_environment_credential=True,
        exclude_workload_identity_credential=managed_only,
        exclude_shared_token_cache_credential=True,
        exclude_visual_studio_code_credential=True,
        exclude_cli_credential=managed_only,
        exclude_powershell_credential=managed_only,
        exclude_developer_cli_credential=managed_only,
        exclude_interactive_browser_credential=True,
        exclude_broker_credential=True,
        retry_total=0,
    )


def pack_token(token: str) -> bytes:
    encoded = token.encode("utf-16-le")
    return struct.pack("<I", len(encoded)) + encoded


def connection_creator(
    settings: Settings,
    credential: TokenCredential,
    connect: Callable[..., Any] = pyodbc.connect,
) -> Callable[[], Any]:
    if not settings.sql_server or not settings.sql_database:
        raise ValueError("SQL_SERVER and SQL_DATABASE are required for SQL operations.")
    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER=tcp:{settings.sql_server},1433;DATABASE={settings.sql_database};"
        "Encrypt=yes;TrustServerCertificate=no;"
        "APP=SyntheticSqlVcorePoc;"
        "ConnectRetryCount=0;"
        + (
            "ApplicationIntent=ReadOnly;"
            if settings.database_target_role == "secondary"
            else "ApplicationIntent=ReadWrite;"
        )
    )

    def create() -> Any:
        context = current_context.get()
        if context is not None and (context.cancelled.is_set() or context.remaining() <= 0):
            raise OperationFailure(API_TIMEOUT)
        # Credential caching is safe; the packed token must never be cached in the creator.
        token = credential.get_token(SQL_SCOPE)
        timeout = settings.sql_login_timeout_seconds
        if context is not None:
            if context.cancelled.is_set() or context.remaining() <= 0:
                raise OperationFailure(API_TIMEOUT)
            timeout = min(timeout, max(1, math.ceil(context.remaining())))
        try:
            connection = connect(
                connection_string,
                attrs_before={SQL_TOKEN_ATTRIBUTE: pack_token(token.token)},
                timeout=timeout,
                autocommit=False,
            )
        except pyodbc.Error as error:
            failure = classify(error)
            if failure.outcome == "database_command_timeout":
                raise OperationFailure(
                    Failure("database_connection_timeout", "login_timeout", True, 503)
                ) from None
            raise
        connection.timeout = settings.sql_command_timeout_seconds
        return connection

    return create


def make_engine(settings: Settings, creator: Callable[[], Any], *, pooled: bool = True) -> Engine:
    options: dict[str, Any] = (
        {
            "pool_size": settings.sql_pool_size,
            "max_overflow": settings.sql_pool_max_overflow,
            "pool_timeout": settings.sql_pool_timeout_seconds,
            "pool_recycle": settings.sql_pool_recycle_seconds,
            "pool_pre_ping": True,
        }
        if pooled
        else {"poolclass": NullPool}
    )
    engine = create_engine(
        "mssql+pyodbc://", creator=creator, echo=False, hide_parameters=True, **options
    )

    @event.listens_for(engine, "before_cursor_execute")
    def before(
        connection: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        execution_context: Any,
        executemany: bool,
    ) -> None:
        context = current_context.get()
        timeout = settings.sql_command_timeout_seconds
        if context is not None:
            if context.cancelled.is_set() or context.remaining() <= 0:
                raise OperationFailure(API_TIMEOUT)
            timeout = min(timeout, max(1, math.ceil(context.remaining())))
            context.db_calls += 1

            def cancel() -> None:
                try:
                    cursor.cancel()
                except pyodbc.Error:
                    return

            context.register_cancel(cancel)
        dbapi = connection.connection.dbapi_connection
        if dbapi is None:
            raise RuntimeError("Physical connection is unavailable.")
        dbapi.timeout = timeout
        execution_context.poc_started = time.monotonic()
        span = trace.get_tracer("synthetic-poc.sql").start_span(
            "sql.execute",
            kind=SpanKind.CLIENT,
            attributes={"db.system": "mssql", "db.operation.name": "execute"},
        )
        execution_context.poc_span = span
        if context is not None:
            span.set_attributes(
                {
                    "operation": context.operation,
                    "correlation_id": context.correlation_id,
                    "test_run_id": context.test_run_id,
                    "workload_profile": context.workload_profile,
                    "attempt": context.attempt,
                    "database_target_role": settings.database_target_role,
                }
            )

    @event.listens_for(engine, "after_cursor_execute")
    def after(
        connection: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        execution_context: Any,
        executemany: bool,
    ) -> None:
        context = current_context.get()
        span = getattr(execution_context, "poc_span", None)
        if span is not None:
            span.set_status(Status(StatusCode.OK))
            span.end()
        if context is not None:
            context.register_cancel(None)
            context.dependency_ms += (time.monotonic() - execution_context.poc_started) * 1000

    @event.listens_for(engine, "handle_error")
    def failure(exception_context: Any) -> None:
        context = current_context.get()
        execution = exception_context.execution_context
        span = getattr(execution, "poc_span", None)
        if span is not None:
            error = classify(exception_context.original_exception)
            span.set_attributes({"error.type": error.outcome, "error.code": error.code})
            span.set_status(Status(StatusCode.ERROR))
            span.end()
        if context is not None:
            context.register_cancel(None)
            if execution is not None and hasattr(execution, "poc_started"):
                context.dependency_ms += (time.monotonic() - execution.poc_started) * 1000

    return engine
