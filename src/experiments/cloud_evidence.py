"""Bounded identity-authenticated Monitor and post-workload read-only SQL evidence."""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from azure.core.credentials import TokenCredential
from azure.core.exceptions import AzureError
from azure.identity import AzureCliCredential, ManagedIdentityCredential

from src.experiments.common import NOT_DEMONSTRATED, read_json, utc_now, write_json
from src.experiments.evidence import METRICS, metric_summary, retail_inputs

ARM = "https://management.azure.com"
LOGS = "https://api.loganalytics.azure.com"
LOG_SCOPE = "https://api.loganalytics.io/.default"
CORE_METRICS = {
    "cpu_percent",
    "physical_data_read_percent",
    "log_write_percent",
    "workers_percent",
    "sessions_percent",
}
LOG_TABLES = ("AppRequests", "AppDependencies", "ContainerAppConsoleLogs_CL")
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class CollectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    resource_id: str
    subscription_id: str
    workspace_id: str
    client_id: str
    wait_seconds: float = 120
    credential: str = "managed-identity"

    def __post_init__(self) -> None:
        for identifier in (self.subscription_id, self.workspace_id):
            UUID(identifier)
        if self.credential == "managed-identity":
            UUID(self.client_id)
        elif self.credential != "azure-cli":
            raise ValueError("Unsupported collection identity")
        pattern = (
            r"/subscriptions/([a-f0-9-]{36})/resourceGroups/[A-Za-z0-9_.()-]+"
            r"/providers/Microsoft\.Sql/servers/[a-z0-9-]+/databases/[A-Za-z0-9_-]+"
        )
        match = re.fullmatch(pattern, self.resource_id, re.IGNORECASE)
        if not match or UUID(match.group(1)) != UUID(self.subscription_id):
            raise ValueError(
                "SQL_RESOURCE_ID must identify a SQL database in the supplied subscription"
            )
        if not math.isfinite(self.wait_seconds) or not 0 <= self.wait_seconds <= 240:
            raise ValueError("Evidence ingestion wait must be between 0 and 240 seconds")

    @classmethod
    def environment(cls) -> Settings:
        names = (
            "SQL_RESOURCE_ID",
            "AZURE_SUBSCRIPTION_ID",
            "LOG_ANALYTICS_WORKSPACE_ID",
            "AZURE_CLIENT_ID",
        )
        if any(not os.environ.get(name) for name in names):
            raise ValueError("Cloud evidence environment is incomplete")
        return cls(
            os.environ["SQL_RESOURCE_ID"],
            os.environ["AZURE_SUBSCRIPTION_ID"],
            os.environ["LOG_ANALYTICS_WORKSPACE_ID"],
            os.environ["AZURE_CLIENT_ID"],
            wait_seconds=float(os.environ.get("EVIDENCE_COLLECTION_WAIT_SECONDS", "120")),
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Settings:
        server = str(config["sql_server"]).lower().removesuffix(".database.windows.net")
        expected = (
            f"/subscriptions/{config['subscription_id']}/resourceGroups/{config['resource_group']}"
            f"/providers/Microsoft.Sql/servers/{server}/databases/{config['database']}"
        )
        resource = config.get("sql_resource_id") or expected
        if not isinstance(resource, str) or resource.lower() != expected.lower():
            raise ValueError("SQL data-plane and ARM collection targets differ")
        return cls(
            resource,
            str(config["subscription_id"]),
            str(config["workspace_id"]),
            str(config.get("managed_identity_client_id", "")),
            credential=config.get("credential", "azure-cli"),
            wait_seconds=float(os.environ.get("EVIDENCE_COLLECTION_WAIT_SECONDS", "120")),
        )


class API:
    def __init__(self, settings: Settings, credential: TokenCredential, http: httpx.Client) -> None:
        self.settings = settings
        self.credential = credential
        self.http = http
        self.deadline = time.monotonic() + 300
        self.requests: list[dict[str, Any]] = []

    def request(
        self,
        service: str,
        path: str,
        operation: str,
        *,
        parameters: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if service not in {"arm", "logs"} or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Unsupported evidence endpoint")
        base, scope = (ARM, ARM + "/.default") if service == "arm" else (LOGS, LOG_SCOPE)
        for attempt in range(1, 4):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise CollectionError("collection-deadline-exceeded")
            record: dict[str, Any] = {
                "service": service,
                "operation": operation,
                "attempt": attempt,
                "http_status": None,
                "sampled_utc": utc_now(),
            }
            self.requests.append(record)
            try:
                token = self.credential.get_token(scope)
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise CollectionError("collection-deadline-exceeded")
                with self.http.stream(
                    "POST" if body is not None else "GET",
                    base + path,
                    params=parameters,
                    json=body,
                    headers={"Authorization": "Bearer " + token.token},
                    timeout=min(30, remaining),
                    follow_redirects=False,
                ) as response:
                    record["http_status"] = response.status_code
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                        delay = float(2**attempt)
                        retry_after = response.headers.get("Retry-After", "")
                        if retry_after.isdigit():
                            delay = max(delay, float(retry_after))
                        delay = min(delay, max(0, self.deadline - time.monotonic()))
                        record["status"] = "retrying"
                        time.sleep(delay)
                        continue
                    if response.status_code != 200:
                        raise CollectionError("http-request-failed")
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= self.deadline:
                            raise CollectionError("collection-deadline-exceeded")
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE_BYTES:
                            raise CollectionError("response-size-limit")
                    value = json.loads(data)
                    if not isinstance(value, dict) or value.get("error") or value.get("nextLink"):
                        raise CollectionError("partial-or-invalid-response")
                    record["status"] = "received"
                    return value
            except httpx.TransportError as exc:
                record["failure_category"] = type(exc).__name__
                record["status"] = "failed"
                if attempt < 3:
                    time.sleep(min(2**attempt, max(0, self.deadline - time.monotonic())))
                    continue
                raise CollectionError("transport-failed") from None
            except (AzureError, ValueError, CollectionError) as exc:
                record["failure_category"] = type(exc).__name__
                record["status"] = "failed"
                raise CollectionError("identity-or-response-failed") from None
        raise CollectionError("request-attempts-exhausted")

    def database(self) -> dict[str, Any]:
        value = self.request(
            "arm",
            self.settings.resource_id,
            "database-configuration",
            parameters={"api-version": "2023-08-01"},
        )
        if not isinstance(value.get("properties"), dict) or not isinstance(value.get("sku"), dict):
            raise CollectionError("database-configuration-invalid")
        return {**value["properties"], "sku": value["sku"], "location": value.get("location")}

    def query(self, query: str, start: str, end: str, operation: str) -> list[dict[str, Any]]:
        value = self.request(
            "logs",
            f"/v1/workspaces/{self.settings.workspace_id}/query",
            operation,
            body={"query": query, "timespan": start + "/" + end},
        )
        tables = value.get("tables")
        if not isinstance(tables, list) or len(tables) != 1:
            raise CollectionError("log-table-response-invalid")
        table = tables[0]
        columns = [column["name"] for column in table.get("columns", [])]
        rows = table.get("rows")
        if (
            not columns
            or not isinstance(rows, list)
            or len(rows) > 500
            or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)
        ):
            raise CollectionError("log-rows-response-invalid")
        return [dict(zip(columns, row, strict=True)) for row in rows]


@contextmanager
def connection(settings: Settings) -> Iterator[API]:
    identity = (
        ManagedIdentityCredential(
            client_id=settings.client_id,
            connection_timeout=5,
            read_timeout=10,
            retry_total=2,
        )
        if settings.credential == "managed-identity"
        else AzureCliCredential(process_timeout=30)
    )
    with (
        identity as credential,
        httpx.Client() as http,
    ):
        yield API(settings, credential, http)


def unavailable(reason: str, error: Exception | None = None) -> dict[str, Any]:
    return {
        "status": NOT_DEMONSTRATED,
        "value": None,
        "reason": reason,
        "failure_category": type(error).__name__ if error else None,
    }


def database_configuration(
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    try:
        with connection(Settings.from_config(config) if config else Settings.environment()) as api:
            attempts = api.requests
            database = api.database()
        return database, {
            "status": "measured",
            "sampled_utc": utc_now(),
            "source": "arm-rest",
            "request_attempts": attempts,
        }
    except (ValueError, AzureError, CollectionError) as exc:
        return None, {
            **unavailable("Cloud SQL configuration not observed", exc),
            "request_attempts": attempts,
        }


def metrics(api: API, start: str, end: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "start_utc": start,
        "end_utc": end,
        "metrics": {},
        "allocated_vcores": None,
        "billed_compute_vcore_seconds": None,
        "allocation_note": "App CPU utilization does not establish allocated compute.",
    }
    definitions = api.request(
        "arm",
        api.settings.resource_id + "/providers/Microsoft.Insights/metricDefinitions",
        "metric-definitions",
        parameters={"api-version": "2018-01-01"},
    ).get("value")
    if not isinstance(definitions, list):
        raise CollectionError("metric-definitions-invalid")
    available = {item["name"]["value"]: item for item in definitions}
    for name, kind in METRICS.items():
        definition = available.get(name)
        record = unavailable("Metric not supported by the target definition")
        record["aggregations"] = {}
        result["metrics"][name] = record
        if not definition:
            continue
        record["unit"] = definition.get("unit")
        desired = ["Total"] if kind == "count" else ["Maximum", "Average"]
        supported = [
            item for item in desired if item in definition.get("supportedAggregationTypes", [])
        ]
        if not supported:
            continue
        try:
            payload = api.request(
                "arm",
                api.settings.resource_id + "/providers/Microsoft.Insights/metrics",
                "metric-values",
                parameters={
                    "api-version": "2023-10-01",
                    "metricnames": name,
                    "timespan": start + "/" + end,
                    "interval": "PT1M",
                    "aggregation": ",".join(supported),
                },
            )
            values = payload.get("value")
            if not isinstance(values, list) or any(
                metric.get("errorCode") not in {None, "Success"} for metric in values
            ):
                raise CollectionError("metric-values-invalid")
            for aggregation in supported:
                measured = metric_summary(payload, aggregation)
                if measured is not None and not math.isfinite(measured):
                    raise CollectionError("nonfinite-metric-response")
                record["aggregations"][aggregation] = {
                    "value": measured,
                    "status": "measured" if measured is not None else NOT_DEMONSTRATED,
                    "series": values,
                }
            record["value"] = record["aggregations"][supported[0]]["value"]
            record["status"] = "measured" if record["value"] is not None else NOT_DEMONSTRATED
            record["reason"] = (
                None if record["value"] is not None else "No samples in the run window"
            )
        except (CollectionError, ValueError, TypeError) as exc:
            record.update(unavailable("Metric request failed", exc))
    result["billed_compute_vcore_seconds"] = result["metrics"]["app_cpu_billed"]["value"]
    return result


def logs(
    api: API, start: str, end: str, run_id: str, *, tables: list[str] | None = None
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", run_id):
        raise ValueError("Unsafe run identifier")
    result: dict[str, Any] = {}
    from src.experiments.evidence import TABLES

    selected = list(LOG_TABLES) if tables is None else tables
    if any(table not in TABLES for table in selected):
        raise ValueError("Unsupported monitoring table")
    for table in selected:
        try:
            schema = api.query(f"{table} | getschema", start, end, "log-schema")
            columns = {row.get("ColumnName") for row in schema}
            container = table == "ContainerAppConsoleLogs_CL"
            correlated = container or table.startswith("App")
            field = "Log_s" if container else "Properties"
            required_columns = {"TimeGenerated", field} if correlated else {"TimeGenerated"}
            if not required_columns.issubset(columns):
                raise CollectionError("required-log-columns-unavailable")
            query = f"{table} | where TimeGenerated between (datetime({start}) .. datetime({end}))"
            if correlated:
                query += (
                    f" | where Log_s contains '{run_id}'"
                    if container
                    else f" | where tostring(Properties['test_run_id']) == '{run_id}'"
                )
            rows = api.query(query + " | summarize observed_rows=count()", start, end, "log-count")
            count = rows[0].get("observed_rows") if len(rows) == 1 else None
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise CollectionError("log-count-invalid")
            result[table] = {
                "status": "measured",
                "observed_rows": count,
                "schema_verified": True,
                "scope": "run-id-correlated-observations-not-request-or-attempt-counts"
                if correlated
                else "workspace-window; correlation not proven",
                "run_id_correlated": correlated,
                "zero_rows_does_not_prove_no_activity": True,
            }
        except (CollectionError, ValueError, KeyError, TypeError) as exc:
            result[table] = unavailable("Log schema or query unavailable", exc)
    return result


def prices(http: httpx.Client, region: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9]+", region):
        raise ValueError("A validated Azure region is required for retail pricing")
    url = "https://prices.azure.com/api/retail/prices"
    parameters: dict[str, str] | None = {
        "api-version": "2023-01-01-preview",
        "$filter": (
            f"armRegionName eq '{region}' and priceType eq 'Consumption' "
            "and (serviceName eq 'SQL Database' or serviceName eq 'Azure Container Apps' "
            "or serviceName eq 'Log Analytics' or serviceName eq 'Storage')"
        ),
    }
    records: list[dict[str, Any]] = []
    deadline = time.monotonic() + 45
    next_page: Any = None
    for _page in range(5):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CollectionError("retail-pricing-deadline-exceeded")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "prices.azure.com"
            or parsed.path != "/api/retail/prices"
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise CollectionError("retail-pricing-pagination-host-invalid")
        with http.stream(
            "GET", url, params=parameters, timeout=min(15, remaining), follow_redirects=False
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES or time.monotonic() >= deadline:
                    raise CollectionError("retail-pricing-response-limit")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise CollectionError("retail-pricing-payload-invalid")
        items = payload.get("Items")
        if (
            not isinstance(items, list)
            or len(items) > 1000
            or any(not isinstance(item, dict) for item in items)
        ):
            raise CollectionError("retail-pricing-items-invalid")
        records.extend(items)
        next_page = payload.get("NextPageLink")
        if not next_page:
            break
        if not isinstance(next_page, str):
            raise CollectionError("retail-pricing-pagination-invalid")
        url, parameters = next_page, None
    return retail_inputs(
        {
            "status": "measured" if records else NOT_DEMONSTRATED,
            "source": "public-retail-pricing-http",
            "sampled_utc": utc_now(),
            "currency": "USD",
            "retail_candidates": records,
            "pagination_truncated": bool(next_page),
        }
    )


def collect(
    directory: Path,
    *,
    config: dict[str, Any] | None = None,
    skip_sql: bool = False,
    include_query_store: bool = True,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    manifest = read_json(directory / "manifest.json")
    configuration = read_json(directory / "configuration.json")
    database_observed = bool(
        isinstance(configuration.get("database"), dict) and configuration["database"].get("sku")
    )
    coverage: dict[str, Any] = {
        "status": "incomplete",
        "scope": "azure-monitor-and-read-only-sql-observer",
        "start_utc": utc_now(),
        "transport": "managed-identity-rest" if config is None else "identity-rest",
        "sql_data_plane_attempted": False,
        "query_store_observer_required": not skip_sql,
        "privileges_elevated": False,
        "request_attempts": [],
        "required_metrics_missing": sorted(CORE_METRICS),
        "correlated_log_rows_observed": False,
        "database_configuration_observed": database_observed,
    }
    metric_data = unavailable("Cloud metric collection has not completed")
    log_data: dict[str, Any] = {}
    idle_window = manifest.get("profile", {}).get("scenario") == "idle" or bool(
        manifest.get("toggles", {}).get("idle_after")
    )
    observer_required = not skip_sql and not idle_window
    coverage["query_store_observer_required"] = observer_required
    coverage["sql_collection_skipped_for_idle"] = idle_window
    for name in ("query-store-summary.json", "sql-diagnostics.json"):
        write_json(
            directory / name,
            unavailable("Read-only observer collection not yet attempted"),
        )
    write_json(
        directory / "cost-inputs.json",
        unavailable("Public retail pricing collection not yet attempted"),
    )
    try:
        start, end = manifest["start_utc"], manifest["end_utc"]
        beginning = datetime.fromisoformat(start.replace("Z", "+00:00"))
        ending = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if (
            beginning.utcoffset() != UTC.utcoffset(beginning)
            or ending.utcoffset() != UTC.utcoffset(ending)
            or beginning >= ending
            or (ending - beginning).total_seconds() > 172800
        ):
            raise ValueError(
                "Cloud collection requires an ordered UTC run window of at most 48 hours"
            )
        settings = Settings.from_config(config) if config else Settings.environment()
        if config is None:
            from src.experiments.cloud_config import environment_configuration

            private_config = directory / "cloud-configuration.json"
            coordinates = (
                read_json(private_config)
                if private_config.exists()
                else environment_configuration()
            )
        else:
            coordinates = config
        required = set(CORE_METRICS)
        if manifest.get("compute_tier") == "Serverless":
            required.add("app_cpu_billed")
        with connection(settings) as api:
            coverage["request_attempts"] = api.requests
            observed_database = api.database()
            configuration["database_end"] = observed_database
            configuration["database_end_sampled_utc"] = utc_now()
            if not database_observed:
                configuration["database"] = observed_database
                configuration["database_collection_scope"] = "sampled-after-workload"
                database_observed = True
            coverage["database_configuration_observed"] = True
            write_json(directory / "configuration.json", configuration)
            if observed_database.get("computeModel") == "Serverless" or "_S_" in observed_database[
                "sku"
            ].get("name", ""):
                required.add("app_cpu_billed")
            wait_until = time.monotonic() + settings.wait_seconds
            while True:
                metric_data = metrics(api, start, end)
                log_data = logs(api, start, end, manifest["test_run_id"], tables=tables)
                missing = sorted(
                    name
                    for name in required
                    if metric_data["metrics"].get(name, {}).get("status") != "measured"
                )
                correlated = any(
                    item.get("run_id_correlated") and item.get("observed_rows", 0) > 0
                    for item in log_data.values()
                )
                coverage.update(
                    {
                        "required_metrics_missing": missing,
                        "correlated_log_rows_observed": correlated,
                        "measured_metric_count": sum(
                            item.get("status") == "measured"
                            for item in metric_data["metrics"].values()
                        ),
                        "measured_log_table_count": sum(
                            item.get("status") == "measured" for item in log_data.values()
                        ),
                    }
                )
                if not missing and correlated and database_observed:
                    gaps = any(
                        item.get("status") != "measured"
                        for item in [*metric_data["metrics"].values(), *log_data.values()]
                    )
                    coverage["status"] = "measured-with-gaps" if gaps else "measured"
                    break
                if time.monotonic() >= min(wait_until, api.deadline):
                    break
                time.sleep(min(15, max(0, min(wait_until, api.deadline) - time.monotonic())))
            if observer_required:
                from src.experiments.sql_evidence import collect_sql

                control = api.database()
                coverage["sql_data_plane_attempted"] = control.get("status") == "Online"
                diagnostics, query_store = collect_sql(
                    coordinates,
                    start,
                    end,
                    include_query_store=include_query_store,
                    control=control,
                    credential=api.credential,
                    observer_only=True,
                )
                write_json(directory / "sql-diagnostics.json", diagnostics)
                if include_query_store:
                    write_json(directory / "query-store-summary.json", query_store)
                query_store_measured = not include_query_store or all(
                    query_store.get(key, {}).get("status") == "measured"
                    for key in ("options", "top_queries", "waits")
                )
                diagnostics_measured = all(
                    diagnostics.get(key, {}).get("status") == "measured"
                    for key in ("resource_samples", "storage")
                )
                coverage["query_store_measured"] = query_store_measured
                coverage["sql_diagnostics_measured"] = diagnostics_measured
                if not query_store_measured or not diagnostics_measured:
                    coverage["status"] = "incomplete"
            else:
                reason = (
                    "No SQL during idle observation" if idle_window else "SQL explicitly skipped"
                )
                for name in ("sql-diagnostics.json", "query-store-summary.json"):
                    write_json(directory / name, unavailable(reason))
            try:
                pricing = prices(api.http, str(coordinates["region"]))
            except (httpx.HTTPError, ValueError, KeyError, CollectionError) as exc:
                pricing = unavailable("Public retail pricing unavailable", exc)
            write_json(directory / "cost-inputs.json", pricing)
            coverage["retail_pricing_observed"] = pricing.get("status") == "measured"
            if coverage["status"] == "measured" and not coverage["retail_pricing_observed"]:
                coverage["status"] = "measured-with-gaps"
    except (ValueError, TypeError, KeyError, OSError, AzureError, CollectionError) as exc:
        coverage["status"] = "incomplete"
        coverage["failure_category"] = type(exc).__name__
    finally:
        coverage["end_utc"] = utc_now()
        write_json(directory / "azure-sql-metrics.json", metric_data)
        write_json(directory / "monitor-logs.json", log_data)
        write_json(directory / "collection-coverage.json", coverage)
        manifest["cloud_evidence_coverage"] = coverage
        manifest["evidence_collection_status"] = coverage["status"]
        write_json(directory / "manifest.json", manifest)
    if coverage["status"] == "incomplete":
        raise CollectionError("Cloud evidence incomplete; inspect private collection-coverage.json")
    return coverage
