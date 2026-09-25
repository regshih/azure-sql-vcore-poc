import base64
import json

import pytest

from src.api.pagination import InvalidCursor, page_response, page_window
from src.database.repository import Page


def encode(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def test_cursor_round_trip() -> None:
    response = page_response(Page(items=(1, 2), upper_id=24, next_after_id=2), "products", {})
    window = page_window(response.next_cursor, "products", {}, 3)
    assert (window.after_id, window.upper_id, window.limit) == (2, 24, 3)


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 2},
        {"after_id": -1},
        {"after_id": 25},
        {"after_id": True},
        {"upper_id": 0},
        {"resource": "other"},
        {"extra": "field"},
        {"filters": []},
    ],
)
def test_invalid_cursor_structure_is_rejected(changes: dict[str, object]) -> None:
    payload = {
        "version": 1,
        "resource": "products",
        "filters": {},
        "after_id": 2,
        "upper_id": 24,
        **changes,
    }
    with pytest.raises(InvalidCursor):
        page_window(encode(payload), "products", {}, 5)


@pytest.mark.parametrize("token", ["", "!", "a" * 2049, encode([]), encode("not-a-cursor")])
def test_malformed_cursor_is_rejected(token: str) -> None:
    with pytest.raises(InvalidCursor):
        page_window(token, "products", {}, 5)
