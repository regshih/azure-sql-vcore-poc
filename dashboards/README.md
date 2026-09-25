# Portable observation assets

No workspace, subscription, datasource identity or billable Grafana resource is embedded.
Import [workbook.json](workbook.json) into an Azure Monitor workbook's advanced editor,
select the existing destination workspace, and choose the UTC experiment interval.
[grafana.json](grafana.json) is optional for an **existing** Grafana installation with an
authorized Azure Monitor datasource. Enter resource IDs only locally; never commit the
configured export. Provider/editor versions can change: JSON structure is checked locally,
but live workbook, Grafana and KQL execution require an explicitly configured environment.

## Prerequisites and queries

1. Inspect the actual destination workspace schema using [discover.kql](kql/discover.kql).
   Run each semicolon-separated query independently when the editor accepts one query.
   `getschema` and missing-table messages are discovery aids, not health evidence.
2. List Azure SQL metric **definitions** from ARM using the operations metrics collector before
   choosing names, supported aggregations, units or exports. Metrics unsupported for Logs must
   be collected through the metrics API/portal; do not synthesize zero samples.
3. Enable only available diagnostic categories and confirm their destination/table mode.
   AzureDiagnostics and resource-specific AzureSQL tables have different schemas.
4. Set the run ID and UTC bounds in the query to match the run manifest. Sampling, collection
   delays, discarded spans and missing export can make workspace counts differ from the load
   generator. Percentiles below describe observed telemetry, not a reconstruction of missing data.

| Query | Actual prerequisite and purpose |
|---|---|
| [api-requests.kql](kql/api-requests.kql) | Workspace `AppRequests` from exported SERVER spans; latency and failed request rows |
| [dependencies.kql](kql/dependencies.kql) | `AppDependencies` SQL CLIENT spans joined to distinct request operation IDs; latency/failures |
| [retries.kql](kql/retries.kql) | **Optional** `AppTraces` JSON-log export; final request retry rate separate from retry attempts |
| [console-outcomes.kql](kql/console-outcomes.kql) | Default ACA environment `ContainerAppConsoleLogs_CL`, `Log_s`, `ContainerAppName_s`; parses allow-listed JSON fields |
| [sql-metrics.kql](kql/sql-metrics.kql) | `AzureMetrics` after diagnostic metric export; percentages, failures, deadlocks and supported billed-compute metrics |
| [sql-diagnostics.kql](kql/sql-diagnostics.kql) | `AzureDiagnostics` confirmed categories: Errors, Timeouts, Blocks, Deadlocks, Query Store statistics |
| [availability-activity.kql](kql/availability-activity.kql) | Exported `AzureActivity` control-plane failover/Resource Health/Service Health records where emitted |

Trace export alone does **not** populate AppTraces; the default JSON retry/final events go to
console. Inspect actual dependency types before filtering for `SQL`. ACA resource-specific mode
uses `ContainerAppConsoleLogs` and unsuffixed columns instead; adapt only after `getschema`.
No raw SQL statements, URLs, exception text or caller IPs are projected by these examples.
Resource IDs and correlation fields are still private and require sanitization.

There is no assumed `ServerlessPauseEvents` table. Timestamp database ARM status samples
(`Online`, `Pausing`, `Paused`, `Resuming`) using the operations collector and correlate them with
requests and metrics. Polling itself, readiness checks and background connections can interfere
with the idle experiment. Activity Log does not prove auto-pause, outage duration, or RTO.
Control-plane writes unrelated to failover must not be labeled failovers.

## Alert and cost interpretation

These dashboards do not activate paging. Alert rules belong to infrastructure and require
explicit opt-in, supported metric definitions, configured thresholds/action groups and owner.
All default thresholds are **POC starting point, not a universal production threshold**.
Review noise after each run; correlate CPU/data/log/worker/session pressure with application
latency, final failures, retries and pool waiting before changing compute. Serverless
`app_cpu_percent` interpretation must follow its discovered metric definition, not an assumed
vCore count. Billed compute has units, not a fixed monetary price; use the official Retail
Prices input collector and include storage/monitoring/network/DR costs separately.

## Verified first-party schema references

- [AppRequests](https://learn.microsoft.com/azure/azure-monitor/reference/tables/apprequests),
  [AppDependencies](https://learn.microsoft.com/azure/azure-monitor/reference/tables/appdependencies),
  [AppTraces](https://learn.microsoft.com/azure/azure-monitor/reference/tables/apptraces)
- [AzureMetrics](https://learn.microsoft.com/azure/azure-monitor/reference/tables/azuremetrics),
  [SQL database metric definitions](https://learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-sql-servers-databases-metrics)
- [Container Apps log monitoring and table modes](https://learn.microsoft.com/azure/container-apps/log-monitoring)
- [Activity Log schema](https://learn.microsoft.com/azure/azure-monitor/platform/activity-log-schema)
- [Workbooks resource parameters](https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-resources)
- [Serverless monitoring](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview)
