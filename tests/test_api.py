import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.dependencies import get_repository
from src.configuration.settings import Settings
from src.database.factory import UnconfiguredSqlRepository
from src.database.memory import InMemoryRepository
from src.database.models import Product
from src.database.repository import Repository

PAYLOAD = {"title": "Synthetic evaluation request", "lines": [{"product_id": 1, "quantity": 2}]}


def test_health_and_readiness(client: TestClient) -> None:
    live = client.get("/healthz", follow_redirects=False)
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert client.get("/readyz", follow_redirects=False).json() == {"status": "ready"}
    assert client.get("/openapi.json").status_code == 200


def test_sql_is_explicitly_unavailable() -> None:
    with TestClient(
        create_app(Settings(app_environment="production", repository_backend="sql"))
    ) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        response = client.get("/api/products")
        assert response.status_code == 503
        assert response.json() == {"error": "repository_unavailable"}


class BrokenRepository(UnconfiguredSqlRepository):
    def check_ready(self) -> None:
        raise RuntimeError("DO_NOT_DISCLOSE_READINESS_DETAIL")

    def get_product(self, product_id: int) -> Product:
        raise RuntimeError("DO_NOT_DISCLOSE_REQUEST_DETAIL")


def test_failures_are_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(Settings(repository_backend="sql"), repository=BrokenRepository())
    with TestClient(app) as client, caplog.at_level(logging.WARNING, logger="synthetic_api"):
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json() == {"status": "not_ready"}
        failed = client.get("/api/products/1?private=DO_NOT_DISCLOSE_QUERY_DETAIL")
        assert failed.status_code == 500
        assert failed.json() == {"error": "internal_error"}
        assert client.get("/healthz").status_code == 200
    assert "DO_NOT_DISCLOSE" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_dependency_override_checks_the_configured_repository(client: TestClient) -> None:
    def override() -> Iterator[Repository]:
        yield UnconfiguredSqlRepository()

    client.app.dependency_overrides[get_repository] = override
    try:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        assert client.get("/api/dashboard").status_code == 503
    finally:
        client.app.dependency_overrides.clear()


def test_lookup_filter_and_dashboard(client: TestClient) -> None:
    product = client.get("/api/products/1")
    assert product.status_code == 200
    assert product.json()["sku"] == "SYN-0001"
    assert client.get("/api/products/9999").status_code == 404
    filtered = client.get("/api/products", params={"department": "operations", "q": "SYN-"})
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 8
    assert all(item["department"] == "operations" for item in filtered.json()["items"])
    assert client.get("/api/products", params={"q": "no-match"}).json() == {
        "items": [],
        "next_cursor": None,
    }
    summary = client.get("/api/dashboard").json()
    assert summary["product_count"] == 24
    assert summary["work_item_count"] == 8
    assert summary["open_work_item_count"] == 4
    assert client.get("/api/work-items/1").status_code == 200
    items = client.get("/api/work-items", params={"status": "open", "product_id": 1}).json()
    assert [item["id"] for item in items["items"]] == [1]


def test_product_pagination_has_no_gaps_or_duplicates(client: TestClient) -> None:
    identifiers: list[int] = []
    params: dict[str, str | int] = {"limit": 5}
    for _ in range(10):
        response = client.get("/api/products", params=params)
        assert response.status_code == 200
        body = response.json()
        identifiers.extend(item["id"] for item in body["items"])
        if body["next_cursor"] is None:
            break
        params["cursor"] = body["next_cursor"]
    else:
        pytest.fail("Pagination did not terminate.")
    assert identifiers == list(range(1, 25))
    exact = client.get("/api/products", params={"limit": 24}).json()
    assert exact["next_cursor"] is None


def test_cursor_is_bound_to_filters_and_resource(client: TestClient) -> None:
    first = client.get("/api/products", params={"limit": 2, "department": "sales"}).json()
    token = first["next_cursor"]
    assert token
    assert client.get("/api/products", params={"cursor": token}).status_code == 400
    assert client.get("/api/work-items", params={"cursor": token}).status_code == 400
    assert client.get("/api/products", params={"cursor": "%bad!"}).status_code == 400
    continuation = client.get(
        "/api/products", params={"cursor": token, "department": "sales", "limit": 3}
    )
    assert continuation.status_code == 200
    assert [item["id"] for item in continuation.json()["items"]] == [9, 12, 15]


def test_work_item_page_excludes_inserts_after_watermark(client: TestClient) -> None:
    first = client.get("/api/work-items", params={"limit": 3}).json()
    created = client.post("/api/work-items", json=PAYLOAD, headers={"Idempotency-Key": "later"})
    assert created.status_code == 201
    second = client.get(
        "/api/work-items", params={"cursor": first["next_cursor"], "limit": 100}
    ).json()
    assert [item["id"] for item in first["items"] + second["items"]] == list(range(1, 9))
    assert second["next_cursor"] is None


def test_idempotency_replay_conflict_and_transaction(client: TestClient) -> None:
    before = client.get("/api/dashboard").json()
    stock = client.get("/api/products/1").json()["stock_units"]
    headers = {"Idempotency-Key": "synthetic-transaction"}
    original = client.post("/api/work-items", json=PAYLOAD, headers=headers)
    replay = client.post("/api/work-items", json=PAYLOAD, headers=headers)
    assert original.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == original.json()
    assert original.headers["Idempotency-Replayed"] == "false"
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert client.get(original.headers["Location"]).json() == original.json()
    conflict = client.post(
        "/api/work-items",
        json={**PAYLOAD, "title": "Different synthetic request"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"error": "idempotency_conflict"}
    assert client.get("/api/products/1").json()["stock_units"] == stock - 2
    after = client.get("/api/dashboard").json()
    assert after["work_item_count"] == before["work_item_count"] + 1
    activity = client.get("/api/activity", params={"limit": 1}).json()["items"][0]
    assert activity["work_item_id"] == original.json()["id"]


@pytest.mark.parametrize("bad_product,quantity,status", [(9999, 1, 404), (2, 1000, 409)])
def test_failed_transaction_has_no_partial_effects(
    client: TestClient, bad_product: int, quantity: int, status: int
) -> None:
    before = client.get("/api/dashboard").json()
    stock = client.get("/api/products/1").json()
    payload = {
        "title": "Synthetic failing request",
        "lines": [
            {"product_id": 1, "quantity": 1},
            {"product_id": bad_product, "quantity": quantity},
        ],
    }
    failed = client.post(
        "/api/work-items", json=payload, headers={"Idempotency-Key": "retry-after-failure"}
    )
    assert failed.status_code == status
    assert client.get("/api/dashboard").json() == before
    assert client.get("/api/products/1").json() == stock
    retry = client.post(
        "/api/work-items", json=PAYLOAD, headers={"Idempotency-Key": "retry-after-failure"}
    )
    assert retry.status_code == 201


@pytest.mark.parametrize("resource", ["products", "work-items"])
def test_batch_bounds_order_duplicates_and_missing(client: TestClient, resource: str) -> None:
    response = client.post(f"/api/{resource}/batch", json={"ids": [3, 1, 3, 9999, 9999]})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [3, 1]
    assert response.json()["missing_ids"] == [9999]
    for identifiers in ([], [0], list(range(1, 102))):
        assert client.post(f"/api/{resource}/batch", json={"ids": identifiers}).status_code == 422


def test_request_validation_does_not_echo_input(client: TestClient) -> None:
    assert client.post("/api/work-items", json=PAYLOAD).status_code == 422
    duplicate = {
        "title": "Synthetic duplicate products",
        "lines": [{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}],
    }
    response = client.post(
        "/api/work-items", json=duplicate, headers={"Idempotency-Key": "duplicate"}
    )
    assert response.status_code == 422
    response = client.get("/api/products", params={"limit": "DO_NOT_DISCLOSE_INPUT"})
    assert response.json() == {"error": "invalid_request"}
    for limit in (0, 101):
        assert client.get("/api/products", params={"limit": limit}).status_code == 422


def test_recent_activity_ties_are_stable_and_new_inserts_are_excluded() -> None:
    repository = InMemoryRepository(clock=lambda: datetime(2025, 2, 1, tzinfo=UTC))
    with TestClient(create_app(Settings(), repository)) as client:
        for key in ("same-time-a", "same-time-b"):
            response = client.post(
                "/api/work-items", json=PAYLOAD, headers={"Idempotency-Key": key}
            )
            assert response.status_code == 201
        first = client.get("/api/activity", params={"limit": 1}).json()
        assert first["items"][0]["id"] == 10
        response = client.post(
            "/api/work-items", json=PAYLOAD, headers={"Idempotency-Key": "after-page"}
        )
        assert response.status_code == 201
        rest = client.get(
            "/api/activity", params={"limit": 100, "cursor": first["next_cursor"]}
        ).json()
        assert [item["id"] for item in rest["items"]] == list(range(9, 0, -1))
        assert rest["next_cursor"] is None


def test_cors_disabled_by_default_and_explicit_allow_list(client: TestClient) -> None:
    response = client.get("/healthz", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in response.headers
    app = create_app(Settings(cors_allow_origins=("http://localhost:5173",)))
    with TestClient(app) as allowed:
        response = allowed.options(
            "/api/work-items",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Idempotency-Key,Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        response = allowed.get("/healthz", headers={"Origin": "http://localhost:9999"})
        assert "access-control-allow-origin" not in response.headers
