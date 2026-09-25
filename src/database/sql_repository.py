import hashlib
import json
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from azure.core.credentials import TokenCredential
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.pool import QueuePool

from src.configuration.settings import Settings
from src.database.connection import connection_creator, credential_for, make_engine
from src.database.dataset_state import dataset_state
from src.database.models import (
    Activity,
    BatchResponse,
    Dashboard,
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
    RepositoryUnavailable,
    WorkItemFilter,
)
from src.telemetry.context import current_context

# Only fixed columns/predicates are composed below; every request value is bound separately.
PRODUCT_COLUMNS = "id, sku, name, department, unit_price_cents, stock_units"
WORK_COLUMNS = "id, title, status, created_at, total_cents"


def command_hash(command: WorkItemCreate) -> bytes:
    canonical = json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Invalid database timestamp type.")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SqlRepository:
    def __init__(
        self,
        settings: Settings,
        *,
        engine: Engine | None = None,
        credential: TokenCredential | None = None,
    ) -> None:
        self.settings = settings
        self._credential = credential if credential is not None else credential_for(settings)
        self._creator = connection_creator(settings, self._credential)
        self.engine = engine if engine is not None else make_engine(settings, self._creator)

    @contextmanager
    def connection(
        self, *, transaction: bool = False, engine: Engine | None = None
    ) -> Iterator[Connection]:
        selected = self.engine if engine is None else engine
        started = time.monotonic()
        context = current_context.get()
        try:
            connection = selected.connect()
        finally:
            if context is not None:
                context.pool_wait_ms += (time.monotonic() - started) * 1000
        with connection:
            if transaction:
                with connection.begin():
                    connection.execute(text("SET XACT_ABORT ON"))
                    yield connection
            else:
                yield connection

    def check_ready(self) -> None:
        with self.connection() as connection:
            version = connection.execute(
                text("SELECT TOP (1) version FROM dbo.SchemaMigrations ORDER BY version DESC")
            ).scalar_one_or_none()
            if version is None or str(version) != self.settings.schema_version:
                raise RepositoryUnavailable

    def get_product(self, product_id: int) -> Product:
        with self.connection() as connection:
            row = (
                connection.execute(
                    text(
                        f"SELECT {PRODUCT_COLUMNS} FROM dbo.Products WHERE id=:id"  # nosec B608
                    ),
                    {"id": product_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise EntityNotFound
            return Product.model_validate(dict(row))

    def list_products(self, filters: ProductFilter, window: PageWindow) -> Page[Product]:
        with self.connection() as connection:
            upper = window.upper_id
            if upper is None:
                upper = int(
                    connection.execute(
                        text("SELECT COALESCE(MAX(id),0) FROM dbo.Products")
                    ).scalar_one()
                )
            predicates = ["id>:after_id", "id<=:upper_id"]
            parameters: dict[str, Any] = {
                "after_id": window.after_id,
                "upper_id": upper,
                "take": window.limit + 1,
            }
            if filters.department is not None:
                predicates.append("department=:department")
                parameters["department"] = filters.department
            if filters.q is not None:
                predicates.append(
                    "(name COLLATE Latin1_General_100_CI_AS_SC LIKE :q ESCAPE '~' "
                    "OR sku COLLATE Latin1_General_100_CI_AS_SC LIKE :q ESCAPE '~')"
                )
                escaped = (
                    filters.q.replace("~", "~~")
                    .replace("%", "~%")
                    .replace("_", "~_")
                    .replace("[", "~[")
                )
                parameters["q"] = f"%{escaped}%"
            rows = connection.execute(
                text(
                    f"SELECT TOP (:take) {PRODUCT_COLUMNS} "  # nosec B608
                    "FROM dbo.Products WHERE " + " AND ".join(predicates) + " ORDER BY id"
                ),
                parameters,
            ).mappings()
            products = tuple(Product.model_validate(dict(row)) for row in rows)
            return Page(
                products[: window.limit],
                upper,
                products[window.limit - 1].id if len(products) > window.limit else None,
            )

    def batch_products(self, identifiers: tuple[int, ...]) -> BatchResponse[Product]:
        identifiers = tuple(dict.fromkeys(identifiers))
        with self.connection() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {PRODUCT_COLUMNS} FROM dbo.Products WHERE id IN :ids"  # nosec B608
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": identifiers},
            ).mappings()
            values = {int(row["id"]): Product.model_validate(dict(row)) for row in rows}
        return BatchResponse(
            items=tuple(values[key] for key in identifiers if key in values),
            missing_ids=tuple(key for key in identifiers if key not in values),
        )

    @staticmethod
    def _items(connection: Connection, rows: Sequence[RowMapping]) -> tuple[WorkItem, ...]:
        if not rows:
            return ()
        identifiers = tuple(int(row["id"]) for row in rows)
        lines = connection.execute(
            text(
                "SELECT work_item_id, product_id, quantity, unit_price_cents "
                "FROM dbo.WorkItemLines WHERE work_item_id IN :ids ORDER BY work_item_id, ordinal"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": identifiers},
        ).mappings()
        grouped: dict[int, list[WorkItemLine]] = {key: [] for key in identifiers}
        for line in lines:
            grouped[int(line["work_item_id"])].append(
                WorkItemLine(
                    product_id=line["product_id"],
                    quantity=line["quantity"],
                    unit_price_cents=line["unit_price_cents"],
                )
            )
        return tuple(
            WorkItem.model_validate(
                {
                    **dict(row),
                    "created_at": utc(row["created_at"]),
                    "lines": tuple(grouped[int(row["id"])]),
                }
            )
            for row in rows
        )

    def _get_item(self, connection: Connection, identifier: int) -> WorkItem:
        row = (
            connection.execute(
                text(
                    f"SELECT {WORK_COLUMNS} FROM dbo.WorkItems WHERE id=:id"  # nosec B608
                ),
                {"id": identifier},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EntityNotFound
        return self._items(connection, [row])[0]

    def get_work_item(self, work_item_id: int) -> WorkItem:
        with self.connection() as connection:
            return self._get_item(connection, work_item_id)

    def list_work_items(self, filters: WorkItemFilter, window: PageWindow) -> Page[WorkItem]:
        with self.connection() as connection:
            upper = window.upper_id
            if upper is None:
                upper = int(
                    connection.execute(
                        text("SELECT COALESCE(MAX(id),0) FROM dbo.WorkItems")
                    ).scalar_one()
                )
            parameters: dict[str, Any] = {
                "after_id": window.after_id,
                "upper_id": upper,
                "take": window.limit + 1,
            }
            predicates = ["w.id>:after_id", "w.id<=:upper_id"]
            if filters.status is not None:
                predicates.append("w.status=:status")
                parameters["status"] = filters.status
            if filters.product_id is not None:
                predicates.append(
                    "EXISTS (SELECT 1 FROM dbo.WorkItemLines l "
                    "WHERE l.work_item_id=w.id AND l.product_id=:product_id)"
                )
                parameters["product_id"] = filters.product_id
            rows = list(
                connection.execute(
                    text(
                        "SELECT TOP (:take) w.id,w.title,w.status,"  # nosec B608
                        "w.created_at,w.total_cents "
                        "FROM dbo.WorkItems w WHERE " + " AND ".join(predicates) + " ORDER BY w.id"
                    ),
                    parameters,
                ).mappings()
            )
            more = len(rows) > window.limit
            items = self._items(connection, rows[: window.limit])
            return Page(items, upper, items[-1].id if more else None)

    def batch_work_items(self, identifiers: tuple[int, ...]) -> BatchResponse[WorkItem]:
        identifiers = tuple(dict.fromkeys(identifiers))
        with self.connection() as connection:
            rows = list(
                connection.execute(
                    text(
                        f"SELECT {WORK_COLUMNS} FROM dbo.WorkItems WHERE id IN :ids"  # nosec B608
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": identifiers},
                ).mappings()
            )
            values = {item.id: item for item in self._items(connection, rows)}
        return BatchResponse(
            items=tuple(values[key] for key in identifiers if key in values),
            missing_ids=tuple(key for key in identifiers if key not in values),
        )

    def create_work_item(self, command: WorkItemCreate, key: str) -> CreationResult:
        digest = command_hash(command)
        with self.connection(transaction=True) as connection:
            context = current_context.get()
            wait_ms = int(min(context.remaining() if context else 5, 5) * 1000)
            result = connection.execute(
                text(
                    "SET NOCOUNT ON; DECLARE @result int; "
                    "EXEC @result=sys.sp_getapplock @Resource=:resource, @LockMode='Exclusive', "
                    "@LockOwner='Transaction', @LockTimeout=:timeout; SELECT @result"
                ),
                {
                    "resource": "poc-idempotency-" + hashlib.sha256(key.encode()).hexdigest(),
                    "timeout": wait_ms,
                },
            ).scalar_one()
            if int(result) < 0:
                raise RepositoryUnavailable
            existing = (
                connection.execute(
                    text(
                        "SELECT command_hash, work_item_id FROM dbo.IdempotencyKeys "
                        "WHERE [key]=:key"
                    ),
                    {"key": key},
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if bytes(existing["command_hash"]) != digest:
                    raise IdempotencyConflict
                return CreationResult(
                    self._get_item(connection, int(existing["work_item_id"])), True
                )
            prices: dict[int, int] = {}
            for requested in sorted(command.lines, key=lambda line: line.product_id):
                product = (
                    connection.execute(
                        text(
                            "SELECT unit_price_cents,stock_units FROM dbo.Products "
                            "WITH (UPDLOCK,ROWLOCK) "
                            "WHERE id=:id"
                        ),
                        {"id": requested.product_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if product is None:
                    raise EntityNotFound
                if int(product["stock_units"]) < requested.quantity:
                    raise InsufficientStock
                prices[requested.product_id] = int(product["unit_price_cents"])
                connection.execute(
                    text("UPDATE dbo.Products SET stock_units=stock_units-:quantity WHERE id=:id"),
                    {"id": requested.product_id, "quantity": requested.quantity},
                )
            total = sum(prices[line.product_id] * line.quantity for line in command.lines)
            row = (
                connection.execute(
                    text(
                        "INSERT dbo.WorkItems(title,status,total_cents) "
                        "OUTPUT inserted.id,inserted.created_at "
                        "VALUES (:title,'open',:total)"
                    ),
                    {"title": command.title, "total": total},
                )
                .mappings()
                .one()
            )
            identifier = int(row["id"])
            connection.execute(
                text(
                    "INSERT dbo.WorkItemLines("
                    "work_item_id,product_id,quantity,unit_price_cents,ordinal) "
                    "VALUES (:work_item_id,:product_id,:quantity,:price,:ordinal)"
                ),
                [
                    {
                        "work_item_id": identifier,
                        "product_id": line.product_id,
                        "quantity": line.quantity,
                        "price": prices[line.product_id],
                        "ordinal": ordinal,
                    }
                    for ordinal, line in enumerate(command.lines)
                ],
            )
            connection.execute(
                text("INSERT dbo.Activity(work_item_id) VALUES (:id)"), {"id": identifier}
            )
            connection.execute(
                text(
                    "INSERT dbo.IdempotencyKeys([key],command_hash,work_item_id) "
                    "VALUES (:key,:hash,:id)"
                ),
                {"key": key, "hash": digest, "id": identifier},
            )
            item = WorkItem(
                id=identifier,
                title=command.title,
                status="open",
                created_at=utc(row["created_at"]),
                total_cents=total,
                lines=tuple(
                    WorkItemLine(
                        product_id=line.product_id,
                        quantity=line.quantity,
                        unit_price_cents=prices[line.product_id],
                    )
                    for line in command.lines
                ),
            )
        # A lost commit acknowledgement is retryable: the key lock + durable hash resolve it.
        return CreationResult(item, False)

    def dashboard(self) -> Dashboard:
        with self.connection() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT (SELECT COUNT_BIG(*) FROM dbo.Products) AS product_count, "
                        "COUNT_BIG(*) AS work_item_count, "
                        "COALESCE(SUM(CASE WHEN status='open' THEN CAST(1 AS bigint) "
                        "ELSE 0 END),0) AS open_work_item_count,"
                        "COALESCE(SUM(CASE WHEN status='completed' THEN CAST(1 AS bigint) "
                        "ELSE 0 END),0) AS completed_work_item_count,"
                        "COALESCE(SUM(total_cents),0) AS total_work_value_cents, "
                        "(SELECT COALESCE(SUM(CAST(stock_units AS bigint)),0) "
                        "FROM dbo.Products) AS stock_units "
                        "FROM dbo.WorkItems"
                    )
                )
                .mappings()
                .one()
            )
            return Dashboard.model_validate(dict(row))

    def recent_activity(self, window: PageWindow) -> Page[Activity]:
        with self.connection() as connection:
            upper = window.upper_id
            if upper is None:
                upper = int(
                    connection.execute(
                        text("SELECT COALESCE(MAX(id),0) FROM dbo.Activity")
                    ).scalar_one()
                )
            rows = connection.execute(
                text(
                    "SELECT TOP (:take) id,work_item_id,kind,occurred_at FROM dbo.Activity "
                    "WHERE id<=:upper AND (:after=0 OR id<:after) ORDER BY id DESC"
                ),
                {"take": window.limit + 1, "upper": upper, "after": window.after_id},
            ).mappings()
            items = tuple(
                Activity.model_validate({**dict(row), "occurred_at": utc(row["occurred_at"])})
                for row in rows
            )
            return Page(
                items[: window.limit],
                upper,
                items[window.limit - 1].id if len(items) > window.limit else None,
            )

    def diagnostic(self, department: str, delay_seconds: int, poor_pooling: bool) -> dict[str, Any]:
        selected = (
            make_engine(self.settings, self._creator, pooled=False) if poor_pooling else self.engine
        )
        try:
            with self.connection(engine=selected) as connection:
                mode = str(
                    connection.execute(
                        text("SELECT value FROM dbo.RuntimeConfiguration WHERE [key]='tuning_mode'")
                    ).scalar_one()
                )
                if delay_seconds:
                    connection.execute(
                        text("WAITFOR DELAY :delay"), {"delay": f"00:00:{delay_seconds:02d}"}
                    )
                predicate = (
                    "department=:department"
                    if mode in {"query", "both"}
                    else "LOWER(department)=LOWER(:department)"
                )
                rows = connection.execute(
                    text(
                        f"SELECT TOP (100) {PRODUCT_COLUMNS} FROM dbo.Products "  # nosec B608
                        f"WHERE {predicate} ORDER BY id"
                    ),
                    {"department": department},
                ).fetchall()
                return {"rows_returned": len(rows), "tuning_mode": mode, "pooled": not poor_pooling}
        finally:
            if poor_pooling:
                selected.dispose()

    def pool_metrics(self) -> dict[str, int | float]:
        pool = self.engine.pool
        if not isinstance(pool, QueuePool):
            return {}
        capacity = self.settings.sql_pool_size + self.settings.sql_pool_max_overflow
        return {
            "pool_size": pool.size(),
            "pool_checked_out": pool.checkedout(),
            "pool_capacity": capacity,
            "pool_utilization": pool.checkedout() / capacity,
        }

    def dataset_metadata(self) -> dict[str, Any]:
        with self.connection() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT "
                        "(SELECT TOP (1) version FROM dbo.SchemaMigrations ORDER BY version DESC) "
                        "AS schema_version,"
                        "(SELECT TOP (1) version FROM dbo.DatasetVersions "
                        "ORDER BY created_at DESC) "
                        "AS dataset_version,"
                        "(SELECT TOP (1) product_count FROM dbo.DatasetVersions "
                        "ORDER BY created_at DESC) "
                        "AS product_count,"
                        "(SELECT TOP (1) work_item_count FROM dbo.DatasetVersions "
                        "ORDER BY created_at DESC) "
                        "AS work_item_count,"
                        "(SELECT value FROM dbo.RuntimeConfiguration WHERE [key]='tuning_mode') "
                        "AS tuning_mode,"
                        "(SELECT value FROM dbo.RuntimeConfiguration WHERE [key]='dataset_kind') "
                        "AS dataset_kind"
                    )
                )
                .mappings()
                .one()
            )
            return {
                "schema_version": row["schema_version"],
                "dataset_version": row["dataset_version"],
                "product_count": int(row["product_count"])
                if row["product_count"] is not None
                else None,
                "work_item_count": int(row["work_item_count"])
                if row["work_item_count"] is not None
                else None,
                "tuning_mode": row["tuning_mode"],
                "dataset_kind": row["dataset_kind"],
                "counts_source": "dataset_seed_ledger",
                "metadata_observed_at": datetime.now(UTC).isoformat(),
                **dataset_state(connection),
            }

    def dispose(self) -> None:
        self.engine.dispose()

    def close(self) -> None:
        self.dispose()
        close = getattr(self._credential, "close", None)
        if close is not None:
            close()
