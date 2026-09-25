from __future__ import annotations

import math
import os
import re
from contextlib import nullcontext
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from azure.core.credentials import TokenCredential
from azure.core.exceptions import AzureError
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from src.configuration.settings import Settings
from src.database.connection import connection_creator, credential_for, make_engine
from src.database.dataset_state import dataset_state
from src.experiments.common import NOT_DEMONSTRATED, ROOT, sql_configuration, utc_now
from src.resilience.errors import OperationFailure

MAX_ROWS = 500
READ_ERRORS = (SQLAlchemyError, AzureError, OperationFailure, OSError)
QUERIES = {
    "schema": (
        "SELECT TOP (500) TABLE_NAME AS table_name,COLUMN_NAME AS column_name,"
        "DATA_TYPE AS data_type,IS_NULLABLE AS is_nullable "
        "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME IN "
        "('Products','WorkItems','WorkItemLines','Activity','IdempotencyKeys','SchemaMigrations') "
        "ORDER BY TABLE_NAME,ORDINAL_POSITION"
    ),
    "schema_versions": (
        "SELECT TOP (100) version,checksum,applied_at FROM dbo.SchemaMigrations ORDER BY version"
    ),
    "resource_samples": (
        "SELECT TOP (500) end_time,avg_cpu_percent,avg_data_io_percent,avg_log_write_percent,"
        "max_worker_percent,max_session_percent,cpu_limit FROM sys.dm_db_resource_stats "
        "WHERE end_time>=CAST(:start_utc AS datetimeoffset) "
        "AND end_time<CAST(:end_utc AS datetimeoffset) ORDER BY end_time"
    ),
    "storage": (
        "SELECT file_id,type_desc,size/128.0 AS allocated_mb,"
        "FILEPROPERTY(name,'SpaceUsed')/128.0 AS used_mb,max_size,growth,is_percent_growth "
        "FROM sys.database_files"
    ),
    "query_store_options": (
        "SELECT actual_state_desc,desired_state_desc,readonly_reason,"
        "current_storage_size_mb,max_storage_size_mb,interval_length_minutes "
        "FROM sys.database_query_store_options"
    ),
}


def missing(reason: str, error: Exception | None = None) -> dict[str, Any]:
    return {
        "status": NOT_DEMONSTRATED,
        "reason": reason,
        "rows": None,
        "failure_category": type(error).__name__ if error else None,
    }


def value_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError("Unexpected SQL diagnostic value type")


def windowed_query(asset: str) -> str:
    if asset not in {"top-queries", "waits"}:
        raise ValueError("Unsupported SQL evidence query")
    source = (ROOT / "sql" / "query-store" / f"{asset}.sql").read_text(encoding="utf-8")
    source, end_count = re.subn(
        r"DECLARE @EndUtc datetimeoffset = SYSUTCDATETIME\(\);",
        "",
        source,
    )
    source, start_count = re.subn(
        r"DECLARE @StartUtc datetimeoffset = DATEADD\(HOUR, -1, @EndUtc\);",
        "",
        source,
    )
    if (start_count, end_count) != (1, 1):
        raise ValueError("Query Store SQL asset window contract changed")
    return source.replace("@StartUtc", "CAST(:start_utc AS datetimeoffset)").replace(
        "@EndUtc", "CAST(:end_utc AS datetimeoffset)"
    )


def read_rows(connection: Connection, query: str, parameters: dict[str, str]) -> dict[str, Any]:
    try:
        rows = connection.execute(text(query), parameters).mappings().fetchmany(MAX_ROWS + 1)
        return {
            "status": "measured",
            "sampled_utc": utc_now(),
            "rows": [
                {str(key): value_json(value) for key, value in row.items()}
                for row in rows[:MAX_ROWS]
            ],
            "row_count": min(len(rows), MAX_ROWS),
            "truncated": len(rows) > MAX_ROWS,
            "empty_rows_do_not_prove_zero_activity": not rows,
        }
    except READ_ERRORS as exc:
        return missing("SQL query unavailable or permission denied", exc)
    finally:
        connection.rollback()


def collect_sql(
    config: dict[str, Any],
    start: str,
    end: str,
    *,
    include_query_store: bool = True,
    control: dict[str, Any] | None = None,
    credential: TokenCredential | None = None,
    observer_only: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    beginning = datetime.fromisoformat(start.replace("Z", "+00:00"))
    ending = datetime.fromisoformat(end.replace("Z", "+00:00"))
    if beginning.utcoffset() is None or ending.utcoffset() is None or beginning >= ending:
        raise ValueError("SQL collection requires an ordered, timezone-aware UTC run window")
    parameters = {
        "start_utc": beginning.astimezone(UTC).isoformat(),
        "end_utc": ending.astimezone(UTC).isoformat(),
    }
    common = {
        **parameters,
        "sampled_utc": utc_now(),
        "read_only_queries": True,
        "collection_after_workload": True,
        "run_exclusive": False,
        "sql_text_included": False,
    }
    diagnostics: dict[str, Any] = dict(common)
    query_store: dict[str, Any] = {
        **common,
        "interval_overlap_may_include_out_of_window_executions": True,
        "capture_flush_and_retention_may_omit_recent_executions": True,
        "no_rows_is_not_zero": True,
    }
    try:
        control = sql_configuration(config) if control is None else control
    except RuntimeError as exc:
        unavailable = missing("Control-plane state unavailable; no SQL connection attempted", exc)
        diagnostics.update(unavailable)
        query_store.update(unavailable)
        return diagnostics, query_store
    if control.get("status") != "Online":
        unavailable = missing("Database not confirmed Online; no SQL probe or resume attempted")
        diagnostics.update(unavailable)
        query_store.update(unavailable)
        return diagnostics, query_store
    diagnostics["online_state_sampled_utc"] = utc_now()
    server = str(config["sql_server"])
    if "." not in server:
        server += ".database.windows.net"
    settings = Settings(
        repository_backend="sql",
        app_environment="production"
        if any(
            os.environ.get(name)
            for name in ("IDENTITY_ENDPOINT", "CONTAINER_APP_NAME", "CONTAINER_APP_JOB_NAME")
        )
        else "local",
        sql_server=server,
        sql_database=config["database"],
        sql_login_timeout_seconds=5,
        sql_command_timeout_seconds=10,
        managed_identity_client_id=config.get("managed_identity_client_id"),
    )
    credential_context = (
        nullcontext(credential) if credential is not None else credential_for(settings)
    )
    with credential_context as sql_credential:
        engine = make_engine(settings, connection_creator(settings, sql_credential), pooled=False)
        try:
            with engine.connect() as connection:
                for name, query in QUERIES.items():
                    if observer_only and name in {"schema", "schema_versions"}:
                        diagnostics[name] = missing("Observer role has no application-table grants")
                        continue
                    if name == "query_store_options" and not include_query_store:
                        continue
                    result = read_rows(connection, query, parameters)
                    if name == "query_store_options":
                        query_store["options"] = result
                    else:
                        diagnostics[name] = result
                if observer_only:
                    diagnostics["dataset"] = missing(
                        "Dataset state comes from guarded API; "
                        "observer has no application-table grants"
                    )
                else:
                    try:
                        diagnostics["dataset"] = {
                            "status": "measured",
                            "sampled_utc": utc_now(),
                            **dataset_state(connection),
                        }
                    except READ_ERRORS as exc:
                        diagnostics["dataset"] = missing("Dataset aggregate query unavailable", exc)
                    finally:
                        connection.rollback()
                for name in ("top-queries", "waits") if include_query_store else ():
                    query_store[name.replace("-", "_")] = read_rows(
                        connection, windowed_query(name), parameters
                    )
        except READ_ERRORS as exc:
            diagnostics.update(missing("SQL connection unavailable or permission denied", exc))
            query_store.update(missing("SQL connection unavailable or permission denied", exc))
        finally:
            engine.dispose()
    query_store["status"] = (
        "measured"
        if query_store.get("top_queries", {}).get("status") == "measured"
        else NOT_DEMONSTRATED
    )
    diagnostics.setdefault("status", "collected; inspect per-section availability")
    return diagnostics, query_store
