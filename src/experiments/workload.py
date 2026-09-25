from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from src.experiments.profiles import Profile


@dataclass
class RequestSpec:
    method: str
    path: str
    operation: str
    params: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] | None = None
    write: bool = False


class Schedule:
    """A bounded offered-load scheduler; missed slots are counted, never caught up."""

    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self.next_due = 0.0
        self.missed = 0
        self.issued = 0

    def acquire(self, elapsed: float) -> tuple[bool, float]:
        rate = self.profile.rate_at(elapsed)
        if not rate:
            self.next_due = elapsed
            return False, 0.05
        if elapsed < self.next_due:
            return False, min(self.next_due - elapsed, 0.05)
        interval = 1 / rate
        self.missed += max(0, math.floor((elapsed - self.next_due) / interval))
        self.next_due = elapsed + interval
        self.issued += 1
        return True, 0


class Workload:
    def __init__(self, profile: Profile, user_index: int) -> None:
        self.profile = profile
        self.random = random.Random(profile.seed + user_index)
        self.cursors: dict[str, str] = {}
        self.operations = 0

    def identifier(self) -> int:
        upper = self.profile.product_count
        if self.random.random() < self.profile.hot_probability:
            upper = max(1, int(upper * self.profile.hot_fraction))
        return self.random.randint(1, upper)

    def next_request(self) -> RequestSpec:
        self.operations += 1
        if self.profile.scenario == "slow":
            return RequestSpec(
                "POST",
                "/api/diagnostics/query",
                "slow-query",
                body={"allow_unsafe_test": True, "department": "operations"},
            )
        if self.profile.scenario == "storm":
            return RequestSpec(
                "POST",
                "/api/diagnostics/query",
                "connection-storm",
                body={
                    "allow_unsafe_test": True,
                    "department": "operations",
                    "poor_pooling": self.profile.connection_mode == "no-reuse",
                },
            )
        if self.random.random() < self.profile.write_ratio:
            return RequestSpec(
                "POST",
                "/api/work-items",
                "transactional-write",
                body={
                    "title": "Synthetic workload item",
                    "lines": [{"product_id": self.identifier(), "quantity": 1}],
                },
                write=True,
            )
        selection = self.random.randrange(100)
        if selection < 40:
            return RequestSpec("GET", f"/api/products/{self.identifier()}", "point-lookup")
        if selection < 55:
            if self.random.random() < 0.5:
                return RequestSpec(
                    "GET",
                    "/api/work-items",
                    "filtered-work-items",
                    params={"status": "open", "limit": 25},
                )
            return RequestSpec(
                "GET",
                "/api/products",
                "filtered-lookup",
                params={"department": "operations", "limit": 25},
            )
        if selection < 70:
            params: dict[str, Any] = {"limit": 25}
            if "paginated-lookup" in self.cursors:
                params["cursor"] = self.cursors["paginated-lookup"]
            return RequestSpec("GET", "/api/products", "paginated-lookup", params=params)
        if selection < 80:
            return RequestSpec("GET", "/api/dashboard", "dashboard")
        if selection < 90:
            params = {"limit": 25}
            if "recent-activity" in self.cursors:
                params["cursor"] = self.cursors["recent-activity"]
            return RequestSpec("GET", "/api/activity", "recent-activity", params=params)
        work_items = self.random.random() < 0.5
        return RequestSpec(
            "POST",
            "/api/work-items/batch" if work_items else "/api/products/batch",
            "batch-work-items" if work_items else "batch-read",
            body={"ids": sorted({self.identifier() for _ in range(5)})},
        )

    def accept_page(self, operation: str, value: Any) -> None:
        if operation not in {"paginated-lookup", "recent-activity"}:
            return
        cursor = value.get("next_cursor") if isinstance(value, dict) else None
        if isinstance(cursor, str) and len(cursor) <= 2048:
            self.cursors[operation] = cursor
        else:
            self.cursors.pop(operation, None)
