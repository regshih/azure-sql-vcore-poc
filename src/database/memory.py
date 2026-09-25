from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol

from src.database.models import (
    Activity,
    BatchResponse,
    Dashboard,
    Department,
    Product,
    WorkItem,
    WorkItemCreate,
    WorkItemLine,
)
from src.database.repository import (
    CreationResult,
    EntityNotFound,
    IdempotencyConflict,
    InsufficientStock,
    Page,
    PageWindow,
    ProductFilter,
    WorkItemFilter,
)


class Identified(Protocol):
    @property
    def id(self) -> int: ...


def select_page[T: Identified](
    values: Iterable[T], window: PageWindow, upper_id: int, *, descending: bool = False
) -> Page[T]:
    eligible = [
        value
        for value in values
        if value.id <= upper_id
        and (
            (window.after_id == 0 or value.id < window.after_id)
            if descending
            else value.id > window.after_id
        )
    ]
    eligible.sort(key=lambda value: value.id, reverse=descending)
    items = tuple(eligible[: window.limit])
    next_id = items[-1].id if len(eligible) > window.limit and items else None
    return Page(items=items, upper_id=upper_id, next_after_id=next_id)


def select_batch[T](values: dict[int, T], identifiers: tuple[int, ...]) -> BatchResponse[T]:
    unique_ids = tuple(dict.fromkeys(identifiers))
    return BatchResponse(
        items=tuple(values[identifier] for identifier in unique_ids if identifier in values),
        missing_ids=tuple(identifier for identifier in unique_ids if identifier not in values),
    )


class InMemoryRepository:
    """Process-local deterministic synthetic data, never a durable/cloud substitute."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._lock = RLock()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._products: dict[int, Product] = {}
        self._work_items: dict[int, WorkItem] = {}
        self._activities: dict[int, Activity] = {}
        self._idempotency: dict[str, tuple[WorkItemCreate, WorkItem]] = {}
        departments: tuple[Department, ...] = ("operations", "engineering", "sales")
        for identifier in range(1, 25):
            self._products[identifier] = Product(
                id=identifier,
                sku=f"SYN-{identifier:04d}",
                name=f"Synthetic product {identifier:04d}",
                department=departments[(identifier - 1) % len(departments)],
                unit_price_cents=1000 + identifier * 125,
                stock_units=100 + identifier * 10,
            )
        epoch = datetime(2025, 1, 1, tzinfo=UTC)
        for identifier in range(1, 9):
            product = self._products[identifier]
            line = WorkItemLine(
                product_id=identifier, quantity=1, unit_price_cents=product.unit_price_cents
            )
            item = WorkItem(
                id=identifier,
                title=f"Synthetic work item {identifier:04d}",
                status="completed" if identifier % 2 == 0 else "open",
                created_at=epoch + timedelta(minutes=identifier),
                lines=(line,),
                total_cents=product.unit_price_cents,
            )
            self._work_items[identifier] = item
            self._activities[identifier] = Activity(
                id=identifier, work_item_id=identifier, occurred_at=item.created_at
            )
            self._products[identifier] = product.model_copy(
                update={"stock_units": product.stock_units - 1}
            )

    def check_ready(self) -> None:
        with self._lock:
            if not self._products:
                raise RuntimeError("Synthetic repository is not initialized.")

    def get_product(self, product_id: int) -> Product:
        with self._lock:
            product = self._products.get(product_id)
            if product is None:
                raise EntityNotFound
            return product

    def list_products(self, filters: ProductFilter, window: PageWindow) -> Page[Product]:
        with self._lock:
            upper = max(self._products, default=0) if window.upper_id is None else window.upper_id
            products = (
                product
                for product in self._products.values()
                if (filters.department is None or product.department == filters.department)
                and (
                    filters.q is None
                    or filters.q in product.name.casefold()
                    or filters.q in product.sku.casefold()
                )
            )
            return select_page(products, window, upper)

    def batch_products(self, identifiers: tuple[int, ...]) -> BatchResponse[Product]:
        with self._lock:
            return select_batch(self._products, identifiers)

    def get_work_item(self, work_item_id: int) -> WorkItem:
        with self._lock:
            item = self._work_items.get(work_item_id)
            if item is None:
                raise EntityNotFound
            return item

    def list_work_items(self, filters: WorkItemFilter, window: PageWindow) -> Page[WorkItem]:
        with self._lock:
            upper = max(self._work_items, default=0) if window.upper_id is None else window.upper_id
            items = (
                item
                for item in self._work_items.values()
                if (filters.status is None or item.status == filters.status)
                and (
                    filters.product_id is None
                    or any(line.product_id == filters.product_id for line in item.lines)
                )
            )
            return select_page(items, window, upper)

    def batch_work_items(self, identifiers: tuple[int, ...]) -> BatchResponse[WorkItem]:
        with self._lock:
            return select_batch(self._work_items, identifiers)

    def create_work_item(self, command: WorkItemCreate, key: str) -> CreationResult:
        with self._lock:
            existing = self._idempotency.get(key)
            if existing is not None:
                original, item = existing
                if original != command:
                    raise IdempotencyConflict
                return CreationResult(item=item, replayed=True)

            # Stage every change before publishing any effects under the same lock.
            products: dict[int, Product] = {}
            lines: list[WorkItemLine] = []
            for requested in command.lines:
                product = self._products.get(requested.product_id)
                if product is None:
                    raise EntityNotFound
                if product.stock_units < requested.quantity:
                    raise InsufficientStock
                products[product.id] = product.model_copy(
                    update={"stock_units": product.stock_units - requested.quantity}
                )
                lines.append(
                    WorkItemLine(
                        product_id=product.id,
                        quantity=requested.quantity,
                        unit_price_cents=product.unit_price_cents,
                    )
                )
            identifier = max(self._work_items, default=0) + 1
            item = WorkItem(
                id=identifier,
                title=command.title,
                status="open",
                created_at=self._clock(),
                lines=tuple(lines),
                total_cents=sum(line.unit_price_cents * line.quantity for line in lines),
            )
            activity_id = max(self._activities, default=0) + 1
            activity = Activity(
                id=activity_id, work_item_id=identifier, occurred_at=item.created_at
            )
            self._products.update(products)
            self._work_items[identifier] = item
            self._activities[activity_id] = activity
            self._idempotency[key] = (command, item)
            return CreationResult(item=item, replayed=False)

    def dashboard(self) -> Dashboard:
        with self._lock:
            items = tuple(self._work_items.values())
            return Dashboard(
                product_count=len(self._products),
                work_item_count=len(items),
                open_work_item_count=sum(item.status == "open" for item in items),
                completed_work_item_count=sum(item.status == "completed" for item in items),
                total_work_value_cents=sum(item.total_cents for item in items),
                stock_units=sum(product.stock_units for product in self._products.values()),
            )

    def recent_activity(self, window: PageWindow) -> Page[Activity]:
        with self._lock:
            upper = max(self._activities, default=0) if window.upper_id is None else window.upper_id
            return select_page(self._activities.values(), window, upper, descending=True)
