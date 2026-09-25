import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

BUSINESS_QUERIES = {
    "Products": (
        "SELECT id,sku,name,department,unit_price_cents,stock_units FROM dbo.Products ORDER BY id"
    ),
    "WorkItems": ("SELECT id,title,status,created_at,total_cents FROM dbo.WorkItems ORDER BY id"),
    "WorkItemLines": (
        "SELECT work_item_id,product_id,quantity,unit_price_cents,ordinal "
        "FROM dbo.WorkItemLines ORDER BY work_item_id,product_id"
    ),
    "Activity": ("SELECT id,work_item_id,kind,occurred_at FROM dbo.Activity ORDER BY id"),
    "IdempotencyKeys": (
        "SELECT [key],command_hash,work_item_id,created_at "
        "FROM dbo.IdempotencyKeys ORDER BY [key] COLLATE Latin1_General_100_BIN2"
    ),
}


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"datetime": value.isoformat(timespec="microseconds")}
    if isinstance(value, bytes | bytearray | memoryview):
        return {"binary_hex": bytes(value).hex()}
    if value is None or isinstance(value, str | int | bool):
        return value
    raise TypeError("Unsupported database fingerprint value type.")


def full_dataset_fingerprint(connection: Connection) -> dict[str, Any]:
    digest = hashlib.sha256(b"synthetic-poc-ordered-business-rows-v1\n")
    counts: dict[str, int] = {}
    for table, query in BUSINESS_QUERIES.items():
        digest.update(json.dumps({"table": table}, separators=(",", ":")).encode("ascii") + b"\n")
        count = 0
        result = connection.execute(text(query))
        for rows in result.partitions(500):
            for row in rows:
                encoded = json.dumps(
                    [_canonical_value(value) for value in row],
                    ensure_ascii=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("ascii")
                digest.update(encoded + b"\n")
                count += 1
        counts[table] = count
    return {
        "full_dataset_fingerprint": digest.hexdigest(),
        "full_dataset_fingerprint_scope": "ordered_business_rows_v1",
        "full_dataset_fingerprint_algorithm": "sha256_canonical_jsonl_v1",
        "full_dataset_row_counts": counts,
        "full_dataset_requires_quiescent_workload": True,
    }


def dataset_state(connection: Connection) -> dict[str, Any]:
    row = (
        connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT_BIG(*) FROM dbo.Products) AS products,"
                "(SELECT COALESCE(SUM(CONVERT(bigint,stock_units)),0) FROM dbo.Products) "
                "AS stock_units,"
                "(SELECT COUNT_BIG(*) FROM dbo.WorkItems) AS work_items,"
                "(SELECT COALESCE(MAX(id),0) FROM dbo.WorkItems) AS last_work_item_id,"
                "(SELECT COALESCE(SUM(total_cents),0) FROM dbo.WorkItems) AS work_item_total_cents,"
                "(SELECT COUNT_BIG(*) FROM dbo.WorkItemLines) AS work_item_lines,"
                "(SELECT COALESCE(SUM(CONVERT(bigint,quantity)),0) FROM dbo.WorkItemLines) "
                "AS quantities,"
                "(SELECT COUNT_BIG(*) FROM dbo.Activity) AS activity,"
                "(SELECT COALESCE(MAX(id),0) FROM dbo.Activity) AS last_activity_id,"
                "(SELECT COUNT_BIG(*) FROM dbo.IdempotencyKeys) AS idempotency_keys"
            )
        )
        .mappings()
        .one()
    )
    values = {key: int(value) for key, value in row.items()}
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("ascii")
    return {
        "dataset_state": values,
        "dataset_state_fingerprint": hashlib.sha256(encoded).hexdigest(),
        "dataset_fingerprint_scope": "aggregate_state_not_full_content",
        "dataset_state_requires_quiescent_workload": True,
    }
