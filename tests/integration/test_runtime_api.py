import asyncio
import secrets
import threading
import time

import httpx
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.configuration.settings import Settings
from src.database.memory import InMemoryRepository
from src.database.models import Product


def test_telemetry_headers_and_unsafe_endpoint_default_off() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get(
            "/api/products/1", headers={"X-Test-Run-Id": "run-001", "X-Correlation-ID": "corr-001"}
        )
        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == "corr-001"
        assert response.headers["X-POC-Outcome"] == "completed_normally"
        assert response.headers["X-Retry-Count"] == "0"
        assert response.headers["X-DB-Calls"] == "0"
        assert response.headers["X-Cache-Hit"] == "false"
        assert (
            client.post("/api/diagnostics/query", json={"allow_unsafe_test": True}).status_code
            == 403
        )
        assert client.get("/internal/metrics").status_code == 403


def test_idle_probe_mode_resume_and_cache_headers() -> None:
    token = secrets.token_urlsafe(32)
    settings = Settings(internal_api_token=token, cache_backend="memory")
    with TestClient(create_app(settings), client=("127.0.0.1", 4000)) as client:
        assert client.get("/api/products/1").headers["X-Cache-Hit"] == "false"
        assert client.get("/api/products/1").headers["X-Cache-Hit"] == "true"
        authorization = {"Authorization": f"Bearer {token}"}
        idle = client.post(
            "/internal/maintenance", json={"action": "idle", "confirm": True}, headers=authorization
        )
        assert idle.status_code == 200
        assert idle.json()["readiness_mode"] == "process"
        assert client.get("/readyz").status_code == 200
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/products/1").status_code == 429
        response = client.post(
            "/internal/maintenance",
            json={"action": "resume", "confirm": True},
            headers=authorization,
        )
        assert response.status_code == 200
        assert client.get("/api/products/1").headers["X-Cache-Hit"] == "false"
        metrics = client.get("/internal/metrics", headers=authorization)
        assert metrics.status_code == 200
        assert metrics.json()["counts"]["cache_hits"] == 1


def test_guarded_metadata_and_versioned_cache_toggle_restore() -> None:
    token = secrets.token_urlsafe(32)
    settings = Settings(internal_api_token=token, cache_backend="memory")
    authorization = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(settings), client=("127.0.0.1", 4000)) as client:
        assert client.get("/internal/metadata").status_code == 403
        metadata = client.get("/internal/metadata", headers=authorization).json()
        assert metadata["application"] == "synthetic-azure-sql-vcore-poc"
        assert metadata["sql_adapter_configured"] is False
        assert metadata["database_validation"] == "not_performed_by_metadata_endpoint"
        original = client.get("/internal/config", headers=authorization).json()
        assert original["cache_enabled"] is True
        assert client.get("/api/products/1").headers["X-Cache-Hit"] == "false"
        assert client.get("/api/products/1").headers["X-Cache-Hit"] == "true"
        changed = client.put(
            "/internal/config",
            headers=authorization,
            json={"cache_enabled": False, "expected_version": original["version"], "confirm": True},
        )
        assert changed.status_code == 200
        current = changed.json()["current"]
        assert changed.json()["previous"] == original
        assert current["cache_enabled"] is False
        assert current["version"] == original["version"] + 1
        assert client.get("/api/products/1").headers["X-Cache-Hit"] == "false"
        assert (
            client.put(
                "/internal/config",
                headers=authorization,
                json={
                    "cache_enabled": True,
                    "expected_version": original["version"],
                    "confirm": True,
                },
            ).status_code
            == 409
        )
        restored = client.put(
            "/internal/config",
            headers=authorization,
            json={
                "cache_enabled": original["cache_enabled"],
                "expected_version": current["version"],
                "confirm": True,
            },
        )
        assert restored.status_code == 200
        assert restored.json()["current"]["cache_enabled"] is True
        assert client.get("/api/products/1").headers["X-Cache-Hit"] == "false"
        assert client.get("/api/products/1").headers["X-Cache-Hit"] == "true"
        assert token not in str(metadata)
        assert metadata["instance_id"] == original["instance_id"]
        assert metadata["product_count"] == 24
        assert metadata["work_item_count"] == 8
        assert metadata["schema_version"] is None
        assert metadata["tuning_mode"] is None
        assert metadata["counts_source"] == "local_memory_initialization"


def test_runtime_config_cannot_create_unconfigured_cache_backend() -> None:
    token = secrets.token_urlsafe(32)
    with TestClient(
        create_app(Settings(internal_api_token=token)), client=("127.0.0.1", 4000)
    ) as client:
        response = client.put(
            "/internal/config",
            headers={"Authorization": f"Bearer {token}"},
            json={"cache_enabled": True, "expected_version": 0, "confirm": True},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "cache_backend_not_configured"


def test_metadata_refresh_is_admitted_and_blocked_during_idle() -> None:
    token = secrets.token_urlsafe(32)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(
        create_app(Settings(internal_api_token=token)), client=("127.0.0.1", 4000)
    ) as client:
        response = client.get("/internal/metadata?refresh_database=true", headers=headers)
        assert response.status_code == 200
        assert "X-POC-Outcome" in response.headers
        metrics = client.get("/internal/metrics", headers=headers).json()
        assert metrics["instance_id"] == response.json()["instance_id"]
        assert metrics["counter_scope"] == "process_lifetime_use_isolated_baseline_end_deltas"
        client.post(
            "/internal/maintenance", headers=headers, json={"action": "idle", "confirm": True}
        )
        assert client.get("/internal/metadata", headers=headers).status_code == 200
        assert (
            client.get("/internal/metadata?refresh_database=true", headers=headers).status_code
            == 429
        )


def test_pool_disposal_alias_requires_server_flags_and_confirmation() -> None:
    token = secrets.token_urlsafe(32)
    headers = {"Authorization": f"Bearer {token}"}
    for poc, unsafe in ((False, True), (True, False), (True, True)):
        settings = Settings(internal_api_token=token, poc_mode=poc, allow_unsafe_tests=unsafe)
        with TestClient(create_app(settings), client=("127.0.0.1", 4000)) as client:
            metadata = client.get("/internal/metadata", headers=headers).json()
            assert metadata["poc_mode"] is poc
            assert metadata["unsafe_tests_enabled"] is (poc and unsafe)
            assert client.post("/admin/pool/dispose", json={"confirm": True}).status_code == 403
            assert client.post("/admin/pool/dispose", json={}, headers=headers).status_code == 422
            result = client.post("/admin/pool/dispose", json={"confirm": True}, headers=headers)
            if not (poc and unsafe):
                assert result.status_code == 403
                continue
            assert result.status_code == 200
            assert result.json()["readiness_mode"] == "process"
            assert result.json()["instance_id"] == metadata["instance_id"]
            assert client.get("/readyz").status_code == 200
            assert client.get("/api/products/1").status_code == 429
            client.post(
                "/internal/maintenance", headers=headers, json={"action": "resume", "confirm": True}
            )
            assert client.get("/api/products/1").status_code == 200


def test_timeout_retains_permit_until_sync_worker_finishes() -> None:
    entered = threading.Event()
    released = threading.Event()

    class SlowRepository(InMemoryRepository):
        def get_product(self, product_id: int) -> Product:
            entered.set()
            released.wait(2)
            return super().get_product(product_id)

    async def exercise() -> None:
        app = create_app(
            Settings(
                request_timeout_seconds=0.05, max_concurrent_requests=1, max_queued_requests=0
            ),
            SlowRepository(),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.get("/api/products/1")
            assert entered.is_set()
            assert first.status_code == 504
            assert app.state.runtime.bulkhead.snapshot()["active_requests"] == 1
            assert (await client.get("/api/products/2")).status_code == 429
            released.set()
            deadline = time.monotonic() + 2
            while app.state.runtime.bulkhead.snapshot()["active_requests"] != 0:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.01)
            assert (await client.get("/api/products/2")).status_code == 200

    try:
        asyncio.run(exercise())
    finally:
        released.set()


def test_diagnostic_requires_server_flag_and_explicit_confirmation() -> None:
    token = secrets.token_urlsafe(32)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(
        create_app(Settings(internal_api_token=token)), client=("127.0.0.1", 4000)
    ) as client:
        assert (
            client.post(
                "/api/diagnostics/query", json={"allow_unsafe_test": True}, headers=headers
            ).status_code
            == 403
        )
    with TestClient(
        create_app(Settings(internal_api_token=token, allow_unsafe_tests=True)),
        client=("127.0.0.1", 4000),
    ) as client:
        assert client.post("/api/diagnostics/query", json={}, headers=headers).status_code == 422
        # The local adapter must never report a successful SQL diagnostic.
        assert (
            client.post(
                "/api/diagnostics/query", json={"allow_unsafe_test": True}, headers=headers
            ).status_code
            == 503
        )


def test_disconnect_cancels_request_but_retains_worker_admission() -> None:
    entered, released = threading.Event(), threading.Event()

    class SlowRepository(InMemoryRepository):
        def get_product(self, product_id: int) -> Product:
            entered.set()
            released.wait(2)
            return super().get_product(product_id)

    async def exercise() -> None:
        app = create_app(Settings(max_concurrent_requests=1), SlowRepository())
        messages = []
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"", "more_body": False}
            while not entered.is_set():
                await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/products/1",
            "raw_path": b"/api/products/1",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 4000),
            "server": ("test", 80),
        }
        await app(scope, receive, send)
        assert messages[0]["status"] == 499
        assert app.state.runtime.bulkhead.snapshot()["active_requests"] == 1
        released.set()
        while app.state.runtime.bulkhead.snapshot()["active_requests"]:
            await asyncio.sleep(0.01)

    try:
        asyncio.run(exercise())
    finally:
        released.set()
