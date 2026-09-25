from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Response

from src.api.dependencies import RepositoryDependency
from src.api.pagination import FilterScope, page_response, page_window
from src.database.models import (
    Activity,
    BatchRequest,
    BatchResponse,
    Dashboard,
    Department,
    PageResponse,
    Product,
    WorkItem,
    WorkItemCreate,
    WorkStatus,
)
from src.database.repository import ProductFilter, WorkItemFilter

router = APIRouter(prefix="/api")
Limit = Annotated[int, Query(ge=1, le=100)]
CursorToken = Annotated[str | None, Query(max_length=2048)]
Identifier = Annotated[int, Path(gt=0)]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    ),
]


@router.get("/products")
def products(
    repository: RepositoryDependency,
    department: Department | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    limit: Limit = 25,
    cursor: CursorToken = None,
) -> PageResponse[Product]:
    normalized_q = q.strip().casefold() if q is not None else None
    normalized_q = normalized_q or None
    filters = ProductFilter(department=department, q=normalized_q)
    scope: FilterScope = {"department": department, "q": normalized_q}
    window = page_window(cursor, "products", scope, limit)
    return page_response(repository.list_products(filters, window), "products", scope)


@router.post("/products/batch")
def batch_products(
    request: BatchRequest, repository: RepositoryDependency
) -> BatchResponse[Product]:
    return repository.batch_products(request.ids)


@router.get("/products/{product_id}")
def product(product_id: Identifier, repository: RepositoryDependency) -> Product:
    return repository.get_product(product_id)


@router.get("/work-items")
def work_items(
    repository: RepositoryDependency,
    status: WorkStatus | None = None,
    product_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Limit = 25,
    cursor: CursorToken = None,
) -> PageResponse[WorkItem]:
    filters = WorkItemFilter(status=status, product_id=product_id)
    scope: FilterScope = {"status": status, "product_id": product_id}
    window = page_window(cursor, "work-items", scope, limit)
    return page_response(repository.list_work_items(filters, window), "work-items", scope)


@router.post("/work-items", status_code=201)
def create_work_item(
    request: WorkItemCreate,
    repository: RepositoryDependency,
    idempotency_key: IdempotencyKey,
    response: Response,
) -> WorkItem:
    result = repository.create_work_item(request, idempotency_key)
    response.status_code = 200 if result.replayed else 201
    response.headers["Idempotency-Replayed"] = str(result.replayed).lower()
    response.headers["Location"] = f"/api/work-items/{result.item.id}"
    return result.item


@router.post("/work-items/batch")
def batch_work_items(
    request: BatchRequest, repository: RepositoryDependency
) -> BatchResponse[WorkItem]:
    return repository.batch_work_items(request.ids)


@router.get("/work-items/{work_item_id}")
def work_item(work_item_id: Identifier, repository: RepositoryDependency) -> WorkItem:
    return repository.get_work_item(work_item_id)


@router.get("/dashboard")
def dashboard(repository: RepositoryDependency) -> Dashboard:
    return repository.dashboard()


@router.get("/activity")
def activity(
    repository: RepositoryDependency, limit: Limit = 25, cursor: CursorToken = None
) -> PageResponse[Activity]:
    window = page_window(cursor, "activity", {}, limit)
    return page_response(repository.recent_activity(window), "activity", {})
