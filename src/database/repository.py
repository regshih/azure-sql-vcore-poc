from dataclasses import dataclass
from typing import Protocol

from src.database.models import (
    Activity,
    BatchResponse,
    Dashboard,
    Department,
    Product,
    WorkItem,
    WorkItemCreate,
    WorkStatus,
)


class RepositoryUnavailable(Exception):
    """Repository is not ready or cannot serve a request."""


class EntityNotFound(Exception):
    """Requested entity does not exist."""


class IdempotencyConflict(Exception):
    """An idempotency key was already committed with a different request."""


class InsufficientStock(Exception):
    """A transaction would consume more stock than is available."""


@dataclass(frozen=True)
class ProductFilter:
    department: Department | None = None
    q: str | None = None


@dataclass(frozen=True)
class WorkItemFilter:
    status: WorkStatus | None = None
    product_id: int | None = None


@dataclass(frozen=True)
class PageWindow:
    limit: int
    after_id: int = 0
    upper_id: int | None = None


@dataclass(frozen=True)
class Page[T]:
    items: tuple[T, ...]
    upper_id: int
    next_after_id: int | None


@dataclass(frozen=True)
class CreationResult:
    item: WorkItem
    replayed: bool


class Repository(Protocol):
    """Sync methods run in FastAPI's threadpool; implementations must be thread-safe.

    All write effects (stock, work item, activity, idempotency record) commit atomically.
    Pages use immutable IDs and a captured upper watermark, never offsets.
    """

    def check_ready(self) -> None: ...
    def get_product(self, product_id: int) -> Product: ...
    def list_products(self, filters: ProductFilter, window: PageWindow) -> Page[Product]: ...
    def batch_products(self, identifiers: tuple[int, ...]) -> BatchResponse[Product]: ...
    def get_work_item(self, work_item_id: int) -> WorkItem: ...
    def list_work_items(self, filters: WorkItemFilter, window: PageWindow) -> Page[WorkItem]: ...
    def batch_work_items(self, identifiers: tuple[int, ...]) -> BatchResponse[WorkItem]: ...
    def create_work_item(self, command: WorkItemCreate, key: str) -> CreationResult: ...
    def dashboard(self) -> Dashboard: ...
    def recent_activity(self, window: PageWindow) -> Page[Activity]: ...
