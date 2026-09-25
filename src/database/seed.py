import random
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.database.dataset_state import dataset_state, full_dataset_fingerprint

PROFILES = {"small": (100, 24), "medium": (10000, 2000), "large": (500000, 50000)}
MAX_ROWS = 3000000


def products(count: int, seed: int) -> list[dict[str, Any]]:
    # Reproducibility is intentional; this generator never creates secrets.
    randomizer = random.Random(seed)  # nosec B311
    return [
        {
            "id": identifier,
            "sku": f"SYN-{identifier:08d}",
            "name": f"Synthetic product {identifier:08d}",
            "department": randomizer.choices(["operations", "engineering", "sales"], [70, 20, 10])[
                0
            ],
            "unit_price_cents": randomizer.randint(100, 100000),
            "stock_units": 100000000,
        }
        for identifier in range(1, count + 1)
    ]


def work_items(count: int, product_count: int, seed: int) -> Iterator[dict[str, Any]]:
    # Reproducible synthetic distribution, not cryptographic randomness.
    randomizer = random.Random(seed + 1)  # nosec B311
    epoch = datetime(2025, 1, 1)
    hot_count = max(1, product_count // 20)
    for identifier in range(1, count + 1):
        hot = randomizer.random() < 0.8
        product_id = randomizer.randint(1, hot_count if hot else product_count)
        age_days = (
            randomizer.randint(0, 7) if identifier > count * 0.8 else randomizer.randint(8, 730)
        )
        yield {
            "id": identifier,
            "title": f"Synthetic work item {identifier:010d}",
            "status": "open" if identifier % 5 else "completed",
            "created_at": epoch - timedelta(days=age_days, seconds=randomizer.randint(0, 86399)),
            "product_id": product_id,
            "quantity": randomizer.randint(1, 3),
        }


def seed_database(
    engine: Engine,
    *,
    size: str = "small",
    seed: int = 42,
    rows: int | None = None,
    reset: bool = False,
    allow_destructive_tests: bool = False,
    confirm_poc: bool = False,
) -> dict[str, Any]:
    if reset and not (allow_destructive_tests and confirm_poc):
        raise ValueError("Reset requires --allow-destructive-tests and --confirm-poc.")
    count, product_count = PROFILES[size]
    count = count if rows is None else rows
    if not 1 <= count <= MAX_ROWS or not 0 <= seed <= 2147483647:
        raise ValueError("Rows must be 1..3000000 and seed must be 0..2147483647.")
    version = f"synthetic-v1-s{seed}-p{product_count}-w{count}"
    product_rows = products(product_count, seed)
    prices = {int(product["id"]): int(product["unit_price_cents"]) for product in product_rows}
    consumption: dict[int, int] = {}
    with engine.begin() as connection:
        lock: int = connection.execute(
            text(
                "SET NOCOUNT ON; DECLARE @r int; EXEC @r=sys.sp_getapplock "
                "@Resource='poc-seed',@LockMode='Exclusive',@LockOwner='Transaction',"
                "@LockTimeout=30000; SELECT @r"
            )
        ).scalar_one()
        if int(lock) < 0:
            raise ValueError("Unable to acquire seed lock.")
        existing: Sequence[str] = (
            connection.execute(text("SELECT version FROM dbo.DatasetVersions")).scalars().all()
        )
        previous_version = None
        if reset:
            marker = connection.execute(
                text("SELECT value FROM dbo.RuntimeConfiguration WHERE [key]='dataset_kind'")
            ).scalar_one_or_none()
            ledger = (
                connection.execute(
                    text(
                        "SELECT version,generation_seed,product_count,work_item_count "
                        "FROM dbo.DatasetVersions"
                    )
                )
                .mappings()
                .all()
            )
            if marker != "synthetic-v1" or len(ledger) != 1:
                raise ValueError(
                    "Reset requires the synthetic seed safety marker and one dataset ledger."
                )
            entry = ledger[0]
            previous_version = (
                f"synthetic-v1-s{entry['generation_seed']}"
                f"-p{entry['product_count']}-w{entry['work_item_count']}"
            )
            if entry["version"] != previous_version:
                raise ValueError("Dataset ledger does not match the synthetic generator.")
            foreign_products: int = connection.execute(
                text(
                    "SELECT COUNT_BIG(*) FROM dbo.Products "
                    "WHERE sku NOT LIKE 'SYN-%' OR name NOT LIKE 'Synthetic product %'"
                )
            ).scalar_one()
            if foreign_products:
                raise ValueError("Non-synthetic products detected; refusing reset.")
            # Callers must drain every application instance before this admin-only transaction.
            for statement in (
                "DELETE FROM dbo.IdempotencyKeys WITH (TABLOCKX)",
                "DELETE FROM dbo.Activity WITH (TABLOCKX)",
                "DELETE FROM dbo.WorkItemLines WITH (TABLOCKX)",
                "DELETE FROM dbo.WorkItems WITH (TABLOCKX)",
                "DELETE FROM dbo.Products WITH (TABLOCKX)",
            ):
                connection.exec_driver_sql(statement)
            connection.exec_driver_sql("DELETE FROM dbo.DatasetVersions")
            connection.exec_driver_sql(
                "DBCC CHECKIDENT ('dbo.WorkItems', RESEED, 0) WITH NO_INFOMSGS"
            )
            connection.exec_driver_sql(
                "DBCC CHECKIDENT ('dbo.Activity', RESEED, 0) WITH NO_INFOMSGS"
            )
            existing = []
        if existing:
            if existing == [version]:
                return {
                    "dataset_version": version,
                    "status": "already_seeded",
                    "work_items": count,
                    **dataset_state(connection),
                }
            raise ValueError("A different dataset exists; use a fresh evaluation database.")
        if connection.execute(text("SELECT COUNT_BIG(*) FROM dbo.Products")).scalar_one() != 0:
            raise ValueError("Seeding requires empty business tables.")
        for offset in range(0, len(product_rows), 500):
            connection.execute(
                text(
                    "INSERT dbo.Products(id,sku,name,department,unit_price_cents,stock_units) "
                    "VALUES (:id,:sku,:name,:department,:unit_price_cents,:stock_units)"
                ),
                product_rows[offset : offset + 500],
            )
        pending: list[dict[str, Any]] = []

        def flush() -> None:
            if not pending:
                return
            connection.exec_driver_sql("SET IDENTITY_INSERT dbo.WorkItems ON")
            connection.execute(
                text(
                    "INSERT dbo.WorkItems(id,title,status,created_at,total_cents) "
                    "VALUES (:id,:title,:status,:created_at,:total_cents)"
                ),
                pending,
            )
            connection.exec_driver_sql("SET IDENTITY_INSERT dbo.WorkItems OFF")
            connection.execute(
                text(
                    "INSERT dbo.WorkItemLines("
                    "work_item_id,product_id,quantity,unit_price_cents,ordinal) "
                    "VALUES (:id,:product_id,:quantity,:unit_price_cents,0)"
                ),
                pending,
            )
            connection.exec_driver_sql("SET IDENTITY_INSERT dbo.Activity ON")
            connection.execute(
                text(
                    "INSERT dbo.Activity(id,work_item_id,occurred_at) VALUES (:id,:id,:created_at)"
                ),
                pending,
            )
            connection.exec_driver_sql("SET IDENTITY_INSERT dbo.Activity OFF")
            pending.clear()

        for row in work_items(count, product_count, seed):
            price = prices[int(row["product_id"])]
            row["unit_price_cents"] = price
            row["total_cents"] = price * int(row["quantity"])
            product_id = int(row["product_id"])
            consumption[product_id] = consumption.get(product_id, 0) + int(row["quantity"])
            pending.append(row)
            if len(pending) == 500:
                flush()
        flush()
        for offset in range(0, len(consumption), 500):
            entries = list(consumption.items())[offset : offset + 500]
            connection.execute(
                text("UPDATE dbo.Products SET stock_units=stock_units-:quantity WHERE id=:id"),
                [{"id": key, "quantity": quantity} for key, quantity in entries],
            )
        connection.execute(
            text(
                "INSERT dbo.DatasetVersions(version,generation_seed,product_count,work_item_count) "
                "VALUES (:version,:seed,:products,:rows)"
            ),
            {"version": version, "seed": seed, "products": product_count, "rows": count},
        )
        connection.execute(
            text(
                "IF NOT EXISTS (SELECT 1 FROM dbo.RuntimeConfiguration WHERE [key]='dataset_kind') "
                "INSERT dbo.RuntimeConfiguration([key],value) "
                "VALUES ('dataset_kind','synthetic-v1')"
            )
        )
        state = dataset_state(connection)
        if reset:
            state.update(full_dataset_fingerprint(connection))
    return {
        "dataset_version": version,
        "previous_dataset_version": previous_version,
        "status": "reset_and_seeded" if reset else "seeded",
        "destructive_reset": reset,
        "generation_seed": seed,
        "size": size,
        "work_items": count,
        "products": product_count,
        **state,
    }
