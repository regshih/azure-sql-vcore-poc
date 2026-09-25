from typing import NoReturn

from src.configuration.settings import Settings, assert_local_memory_allowed
from src.database.memory import InMemoryRepository
from src.database.models import (
    Activity,
    BatchResponse,
    Dashboard,
    Product,
    WorkItem,
    WorkItemCreate,
)
from src.database.repository import (
    CreationResult,
    Page,
    PageWindow,
    ProductFilter,
    Repository,
    RepositoryUnavailable,
    WorkItemFilter,
)


class UnconfiguredSqlRepository:
    """Fail-closed boundary for missing SQL configuration; never a memory fallback."""

    @staticmethod
    def _unavailable() -> NoReturn:
        raise RepositoryUnavailable

    def check_ready(self) -> None:
        self._unavailable()

    def get_product(self, product_id: int) -> Product:
        self._unavailable()

    def list_products(self, filters: ProductFilter, window: PageWindow) -> Page[Product]:
        self._unavailable()

    def batch_products(self, identifiers: tuple[int, ...]) -> BatchResponse[Product]:
        self._unavailable()

    def get_work_item(self, work_item_id: int) -> WorkItem:
        self._unavailable()

    def list_work_items(self, filters: WorkItemFilter, window: PageWindow) -> Page[WorkItem]:
        self._unavailable()

    def batch_work_items(self, identifiers: tuple[int, ...]) -> BatchResponse[WorkItem]:
        self._unavailable()

    def create_work_item(self, command: WorkItemCreate, key: str) -> CreationResult:
        self._unavailable()

    def dashboard(self) -> Dashboard:
        self._unavailable()

    def recent_activity(self, window: PageWindow) -> Page[Activity]:
        self._unavailable()


def build_repository(settings: Settings) -> Repository:
    if settings.repository_backend == "memory":
        assert_local_memory_allowed(settings)
        return InMemoryRepository()
    if not settings.sql_server or not settings.sql_database:
        return UnconfiguredSqlRepository()
    from src.database.sql_repository import SqlRepository

    return SqlRepository(settings)
