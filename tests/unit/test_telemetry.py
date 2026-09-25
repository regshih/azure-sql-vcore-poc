import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pyodbc
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from src.api.app import create_app
from src.configuration.settings import Settings
from src.database.connection import make_engine
from src.database.memory import InMemoryRepository
from src.database.models import Product
from src.telemetry.context import ExecutionContext, current_context


@pytest.fixture
def traces(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    return exporter


def test_api_exports_server_span_without_url_query_or_headers(
    traces: InMemorySpanExporter,
) -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get(
            "/api/products/1?ignored=private-query",
            headers={"X-Test-Run-Id": "synthetic-run", "Authorization": "private-header"},
        )
    assert response.status_code == 200
    spans = traces.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.kind == SpanKind.SERVER
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes is not None
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.response.status_code"] == 200
    assert span.attributes["test_run_id"] == "synthetic-run"
    assert "private" not in str(span.attributes)
    assert not span.events


def test_sql_span_in_worker_inherits_api_request_parent(
    traces: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = InMemoryRepository()
    original = repository.get_product
    engine = make_engine(Settings(), MagicMock())

    def instrumented_lookup(product_id: int) -> Product | None:
        execution = SimpleNamespace()
        engine.dispatch.before_cursor_execute(
            MagicMock(), MagicMock(), "SELECT synthetic", (), execution, False
        )
        engine.dispatch.after_cursor_execute(
            MagicMock(), MagicMock(), "SELECT synthetic", (), execution, False
        )
        return original(product_id)

    monkeypatch.setattr(repository, "get_product", instrumented_lookup)
    try:
        with TestClient(create_app(Settings(), repository)) as client:
            assert client.get("/api/products/1").status_code == 200
    finally:
        engine.dispose()
    dependency, request = traces.get_finished_spans()
    assert dependency.kind == SpanKind.CLIENT
    assert request.kind == SpanKind.SERVER
    assert dependency.parent is not None
    assert request.context is not None
    assert dependency.parent.span_id == request.context.span_id


@pytest.mark.parametrize("failed", [False, True])
def test_sql_exports_child_client_span_with_sanitized_failure(
    traces: InMemorySpanExporter, failed: bool
) -> None:
    engine = make_engine(Settings(), MagicMock())
    context = ExecutionContext(deadline=time.monotonic() + 10, operation="product_lookup")
    token = current_context.set(context)
    execution = SimpleNamespace()
    statement = "SELECT private_column WHERE private_parameter = ?"
    try:
        with trace.get_tracer("test").start_as_current_span("request", kind=SpanKind.SERVER):
            engine.dispatch.before_cursor_execute(
                MagicMock(), MagicMock(), statement, ("private-value",), execution, False
            )
            if failed:
                error_context = SimpleNamespace(
                    execution_context=execution,
                    original_exception=pyodbc.Error("42000", "private-exception (102)"),
                )
                for callback in engine.dialect.dispatch.handle_error:
                    callback(error_context)
            else:
                engine.dispatch.after_cursor_execute(
                    MagicMock(), MagicMock(), statement, ("private-value",), execution, False
                )
    finally:
        current_context.reset(token)
        engine.dispose()
    spans = traces.get_finished_spans()
    sql_span, parent = spans
    assert sql_span.kind == SpanKind.CLIENT
    assert sql_span.parent is not None
    assert parent.context is not None
    assert sql_span.parent.span_id == parent.context.span_id
    assert sql_span.name == "sql.execute"
    assert sql_span.attributes is not None
    assert sql_span.attributes["db.system"] == "mssql"
    assert sql_span.status.status_code == (StatusCode.ERROR if failed else StatusCode.OK)
    assert "private" not in str(sql_span.attributes)
    assert not sql_span.events
