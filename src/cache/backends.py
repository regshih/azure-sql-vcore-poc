import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, Protocol

from azure.core.credentials import TokenCredential
from redis import Redis

from src.configuration.settings import Settings


class Cache(Protocol):
    def read(self, key: str) -> tuple[str, bytes | None]: ...
    def write(self, generation: str, key: str, value: bytes) -> None: ...
    def invalidate(self) -> None: ...
    def close(self) -> None: ...


class MemoryCache:
    """Local development only; generation keys prevent stale fills after invalidation."""

    def __init__(
        self, ttl: int, capacity: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self._values: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._generation = 0
        self._expirations = 0
        self._lock = threading.Lock()

    def read(self, key: str) -> tuple[str, bytes | None]:
        with self._lock:
            version = str(self._generation)
            value = self._values.get(key)
            if value is None:
                return version, None
            expires, data = value
            if expires <= self.clock():
                del self._values[key]
                self._expirations += 1
                return version, None
            self._values.move_to_end(key)
            return version, data

    def write(self, generation: str, key: str, value: bytes) -> None:
        with self._lock:
            if generation != str(self._generation):
                return
            self._values[key] = (self.clock() + self.ttl, value)
            self._values.move_to_end(key)
            while len(self._values) > self.capacity:
                self._values.popitem(last=False)

    def invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._values.clear()

    def close(self) -> None:
        self.invalidate()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._values),
                "payload_bytes": sum(len(value[1]) for value in self._values.values()),
                "observed_expirations": self._expirations,
            }


class RedisCache:
    def __init__(
        self,
        settings: Settings,
        credential: TokenCredential,
        namespace: str,
        client_factory: Callable[..., Any] = Redis,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not settings.redis_host or not settings.redis_username:
            raise ValueError("REDIS_HOST and REDIS_USERNAME are required for Entra Redis caching.")
        self.settings, self.credential, self.namespace = settings, credential, namespace
        self._factory, self.clock = client_factory, clock
        self._client: Any = None
        self._expires = 0
        self._lock = threading.Lock()

    def _authenticated_client(self) -> Any:
        if self._client is None or self._expires <= self.clock() + 120:
            token = self.credential.get_token("https://redis.azure.com/.default")
            if token.expires_on <= self.clock() + 30:
                raise RuntimeError("Redis token is too close to expiry.")
            new_client = self._factory(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                ssl=True,
                ssl_cert_reqs="required",
                ssl_check_hostname=True,
                username=self.settings.redis_username,
                password=token.token,
                socket_timeout=self.settings.redis_timeout_seconds,
                socket_connect_timeout=self.settings.redis_timeout_seconds,
                max_connections=4,
                decode_responses=False,
            )
            old_client, self._client = self._client, new_client
            self._expires = token.expires_on
            if old_client is not None:
                # Cache operations are serialized, so no in-flight operation uses the old pool.
                old_client.close()
                old_client.connection_pool.disconnect()
        return self._client

    def read(self, key: str) -> tuple[str, bytes | None]:
        with self._lock:
            client = self._authenticated_client()
            raw = client.get(f"{self.namespace}:generation")
            generation = bytes(raw).decode("ascii") if raw else "0"
            value = client.get(f"{self.namespace}:{generation}:{key}")
            return generation, bytes(value) if value is not None else None

    def write(self, generation: str, key: str, value: bytes) -> None:
        with self._lock:
            self._authenticated_client().set(
                f"{self.namespace}:{generation}:{key}", value, ex=self.settings.cache_ttl_seconds
            )

    def invalidate(self) -> None:
        with self._lock:
            self._authenticated_client().incr(f"{self.namespace}:generation")

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client.connection_pool.disconnect()
                self._client = None
