from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PositiveId = Annotated[int, Field(gt=0)]
Department = Literal["operations", "engineering", "sales"]
WorkStatus = Literal["open", "completed"]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Product(Model):
    id: PositiveId
    sku: str
    name: str
    department: Department
    unit_price_cents: int = Field(ge=0)
    stock_units: int = Field(ge=0)


class WorkItemLineInput(Model):
    product_id: PositiveId
    quantity: int = Field(ge=1, le=1000)


class WorkItemCreate(Model):
    title: str = Field(min_length=3, max_length=120)
    lines: tuple[WorkItemLineInput, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_products(self) -> Self:
        identifiers = [line.product_id for line in self.lines]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Each product may appear only once.")
        return self


class WorkItemLine(WorkItemLineInput):
    unit_price_cents: int = Field(ge=0)


class WorkItem(Model):
    id: PositiveId
    title: str
    status: WorkStatus
    created_at: datetime
    lines: tuple[WorkItemLine, ...]
    total_cents: int = Field(ge=0)


class Activity(Model):
    id: PositiveId
    work_item_id: PositiveId
    kind: Literal["work_item_created"] = "work_item_created"
    occurred_at: datetime


class Dashboard(Model):
    product_count: int
    work_item_count: int
    open_work_item_count: int
    completed_work_item_count: int
    total_work_value_cents: int
    stock_units: int


class BatchRequest(Model):
    ids: tuple[PositiveId, ...] = Field(min_length=1, max_length=100)


class BatchResponse[T](Model):
    items: tuple[T, ...]
    missing_ids: tuple[int, ...]


class PageResponse[T](Model):
    items: tuple[T, ...]
    next_cursor: str | None
