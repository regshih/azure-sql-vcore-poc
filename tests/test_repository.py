from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from src.database.memory import InMemoryRepository
from src.database.models import WorkItemCreate, WorkItemLineInput
from src.database.repository import IdempotencyConflict, PageWindow, ProductFilter


def command(quantity: int = 1) -> WorkItemCreate:
    return WorkItemCreate(
        title="Synthetic concurrency request",
        lines=(WorkItemLineInput(product_id=1, quantity=quantity),),
    )


def test_seed_is_deterministic_and_instances_are_isolated() -> None:
    first, second = InMemoryRepository(), InMemoryRepository()
    assert first.dashboard() == second.dashboard()
    assert first.recent_activity(PageWindow(limit=100)) == second.recent_activity(
        PageWindow(limit=100)
    )
    first.create_work_item(command(), "local")
    assert first.dashboard().work_item_count == second.dashboard().work_item_count + 1


def test_concurrent_idempotent_requests_commit_once(repository: InMemoryRepository) -> None:
    before = repository.dashboard()
    stock = repository.get_product(1).stock_units
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(lambda _: repository.create_work_item(command(), "shared"), range(32))
        )
    assert len({result.item.id for result in results}) == 1
    assert sum(not result.replayed for result in results) == 1
    assert repository.get_product(1).stock_units == stock - 1
    assert repository.dashboard().work_item_count == before.work_item_count + 1


def test_same_key_different_request_conflicts(repository: InMemoryRepository) -> None:
    original = repository.create_work_item(command(), "same-key")
    with pytest.raises(IdempotencyConflict):
        repository.create_work_item(command(2), "same-key")
    assert repository.create_work_item(command(), "same-key").item == original.item


def test_clock_failure_rolls_back_all_staged_changes() -> None:
    def broken_clock() -> datetime:
        raise RuntimeError("synthetic clock failure")

    repository = InMemoryRepository(clock=broken_clock)
    before = repository.dashboard()
    product = repository.get_product(1)
    with pytest.raises(RuntimeError):
        repository.create_work_item(command(), "clock-error")
    assert repository.dashboard() == before
    assert repository.get_product(1) == product


def test_empty_and_terminal_pages(repository: InMemoryRepository) -> None:
    empty = repository.list_products(ProductFilter(q="does-not-exist"), PageWindow(limit=1))
    assert empty.items == ()
    assert empty.next_after_id is None
    terminal = repository.list_products(
        ProductFilter(), PageWindow(limit=10, after_id=24, upper_id=24)
    )
    assert terminal.items == ()
    assert terminal.next_after_id is None
