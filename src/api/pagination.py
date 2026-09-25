import base64
import binascii
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.database.models import PageResponse
from src.database.repository import Page, PageWindow

type FilterScope = dict[str, str | int | None]


class InvalidCursor(Exception):
    """Malformed cursor or cursor belonging to a different query."""


class Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    resource: Literal["products", "work-items", "activity"]
    filters: FilterScope
    after_id: int = Field(gt=0)
    upper_id: int = Field(gt=0)


def page_window(token: str | None, resource: str, filters: FilterScope, limit: int) -> PageWindow:
    if token is None:
        return PageWindow(limit=limit)
    try:
        if not token or len(token) > 2048:
            raise InvalidCursor
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        cursor = Cursor.model_validate_json(raw)
        if (
            cursor.resource != resource
            or cursor.filters != filters
            or cursor.after_id > cursor.upper_id
        ):
            raise InvalidCursor
    except (binascii.Error, ValueError, ValidationError):
        raise InvalidCursor from None
    return PageWindow(limit=limit, after_id=cursor.after_id, upper_id=cursor.upper_id)


def page_response[T](page: Page[T], resource: str, filters: FilterScope) -> PageResponse[T]:
    token = None
    if page.next_after_id is not None:
        payload = {
            "version": 1,
            "resource": resource,
            "filters": filters,
            "after_id": page.next_after_id,
            "upper_id": page.upper_id,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return PageResponse(items=page.items, next_cursor=token)
