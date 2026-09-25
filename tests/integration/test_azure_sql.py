import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from src.configuration.settings import Settings
from src.database.models import WorkItemCreate, WorkItemLineInput
from src.database.repository import IdempotencyConflict, PageWindow, ProductFilter
from src.database.sql_repository import SqlRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_AZURE_SQL_TESTS") != "1",
    reason="Requires a real Entra-authenticated, bootstrapped Azure SQL evaluation database.",
)


def test_live_schema_queries_and_concurrent_idempotency() -> None:
    repository = SqlRepository(Settings(repository_backend="sql"))
    try:
        repository.check_ready()
        product = repository.get_product(1)
        assert product.sku.startswith("SYN-")
        page = repository.list_products(ProductFilter(), PageWindow(limit=2))
        assert len(page.items) == 2
        assert page.next_after_id is not None
        assert repository.dashboard().product_count > 0
        command = WorkItemCreate(
            title="Synthetic SQL integration", lines=(WorkItemLineInput(product_id=1, quantity=1),)
        )
        key = f"integration-{uuid4().hex}"
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(lambda _: repository.create_work_item(command, key), range(4))
            )
        assert len({result.item.id for result in results}) == 1
        assert sum(not result.replayed for result in results) == 1
        assert repository.get_product(1).stock_units == product.stock_units - 1
        with pytest.raises(IdempotencyConflict):
            repository.create_work_item(
                command.model_copy(update={"title": "Synthetic different request"}), key
            )
    finally:
        repository.close()
