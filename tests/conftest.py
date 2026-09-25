from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.configuration.settings import CLOUD_MARKERS, Settings
from src.database.memory import InMemoryRepository


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CLOUD_MARKERS:
        monkeypatch.delenv(name, raising=False)
    for name in (
        "APP_ENVIRONMENT",
        "REPOSITORY_BACKEND",
        "CORS_ALLOW_ORIGINS",
        "HOST",
        "PORT",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def client(repository: InMemoryRepository) -> Iterator[TestClient]:
    app = create_app(Settings(app_environment="test"), repository=repository)
    with TestClient(app) as test_client:
        yield test_client
