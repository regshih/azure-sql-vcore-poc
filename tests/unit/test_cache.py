from unittest.mock import MagicMock

from azure.core.credentials import AccessToken

from src.cache.backends import MemoryCache, RedisCache
from src.configuration.settings import Settings
from src.database.memory import InMemoryRepository
from src.database.models import WorkItemCreate, WorkItemLineInput
from src.database.runtime import RuntimeRepository
from src.telemetry.metrics import Registry


def test_local_cache_ttl_lru_and_generation_invalidation() -> None:
    now = [0.0]
    cache = MemoryCache(10, 2, lambda: now[0])
    generation, missing = cache.read("a")
    assert missing is None
    cache.write(generation, "a", b"one")
    cache.write(generation, "b", b"two")
    assert cache.read("a")[1] == b"one"
    cache.write(generation, "c", b"three")
    assert cache.read("b")[1] is None
    cache.invalidate()
    cache.write(generation, "a", b"stale-fill")
    assert cache.read("a")[1] is None
    generation, _ = cache.read("a")
    cache.write(generation, "a", b"fresh")
    now[0] = 11
    assert cache.read("a")[1] is None


def test_write_invalidation_changes_stock_and_dashboard() -> None:
    settings = Settings(cache_backend="memory")
    registry = Registry(settings)
    repository = RuntimeRepository(InMemoryRepository(), settings, registry)
    original = repository.get_product(1)
    assert repository.get_product(1) == original
    dashboard = repository.dashboard()
    assert repository.dashboard() == dashboard
    repository.create_work_item(
        WorkItemCreate(
            title="Synthetic cached write", lines=(WorkItemLineInput(product_id=1, quantity=2),)
        ),
        "cache-write",
    )
    assert repository.get_product(1).stock_units == original.stock_units - 2
    assert repository.dashboard().work_item_count == dashboard.work_item_count + 1
    assert registry.snapshot()["counts"]["cache_hits"] == 2


def test_redis_rotates_pools_before_token_expiry_with_tls() -> None:
    now = [1000.0]
    credential = MagicMock()
    credential.get_token.side_effect = [
        AccessToken("synthetic-token-a", 1500),
        AccessToken("synthetic-token-b", 2000),
    ]
    first, second = MagicMock(), MagicMock()
    first.get.return_value = None
    second.get.return_value = None
    factory = MagicMock(side_effect=[first, second])
    cache = RedisCache(
        Settings(redis_host="redis.example.invalid", redis_username="synthetic-runtime"),
        credential,
        "synthetic-test",
        factory,
        lambda: now[0],
    )
    cache.read("product:1")
    now[0] = 1400
    cache.read("product:1")
    assert factory.call_count == 2
    assert factory.call_args.kwargs["ssl"] is True
    assert factory.call_args.kwargs["ssl_cert_reqs"] == "required"
    assert factory.call_args.kwargs["ssl_check_hostname"] is True
    first.close.assert_called_once()
    first.connection_pool.disconnect.assert_called_once()
    credential.get_token.assert_called_with("https://redis.azure.com/.default")
