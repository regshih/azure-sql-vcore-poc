import pytest
from pydantic import ValidationError

from src.api.app import create_app
from src.configuration.settings import CLOUD_MARKERS, Settings, assert_local_memory_allowed
from src.database.factory import UnconfiguredSqlRepository, build_repository
from src.database.memory import InMemoryRepository


def test_defaults_are_local_only() -> None:
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.cors_allow_origins == ()
    assert isinstance(build_repository(settings), InMemoryRepository)


def test_production_memory_is_rejected_even_when_injected() -> None:
    with pytest.raises(ValueError, match="local/test only"):
        create_app(Settings(app_environment="production"))
    with pytest.raises(ValueError, match="local/test only"):
        create_app(
            Settings(app_environment="production", repository_backend="sql"),
            repository=InMemoryRepository(),
        )


@pytest.mark.parametrize("marker", CLOUD_MARKERS)
def test_cloud_detection_prevents_silent_memory_fallback(
    monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    monkeypatch.setenv(marker, "synthetic-host-signal")
    with pytest.raises(ValueError, match="local/test only"):
        create_app(Settings())


def test_sql_never_falls_back_to_memory() -> None:
    repository = build_repository(Settings(repository_backend="sql"))
    assert isinstance(repository, UnconfiguredSqlRepository)
    assert_local_memory_allowed(Settings(), environ={})


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.invalid",
        "https://example.invalid/path",
        "https://example.invalid:bad",
    ],
)
def test_invalid_cors_origin_is_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(cors_allow_origins=(origin,))


def test_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "8012")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", '["http://localhost:5173"]')
    assert Settings().port == 8012
    assert Settings().cors_allow_origins == ("http://localhost:5173",)
