# Monitoring, portal navigation, and KQL

Telemetry coverage must be demonstrated before performance conclusions. A missing
table, unsupported metric, disabled diagnostic category, sampled trace, or
late-ingested event is not a zero. Current POC cloud observations:
**Not demonstrated by this POC run.**

## Before each experiment

Record one UTC run window and unique run ID. Attach profile, database/compute
configuration, vCore bounds, region, application/schema/dataset versions, workload
hash and actual overrides. Configure Application Insights/Log Analytics and the
approved optional SQL diagnostic categories. Inspect ingestion costs and retention.
Platform metrics, diagnostic logs, subscription activity logs, and application
telemetry have different enablement and schemas.

`enable_sql_diagnostics` defaults false. The optional infrastructure setting
exports selected SQL Errors, Timeouts, Blocks and Deadlocks logs plus metrics
to the workspace, subject to actual category support. Approve ingestion/retention
cost and validate real tables after enabling it. This option is distinct from
native Azure Monitor platform metrics and from application span export; a
disabled SQL diagnostic setting does not imply platform metrics are unavailable.

Verify timestamps, one sample request/dependency, one classified outcome,
SQL resource metrics, and the available Query Store interval before starting.
No token, connection string, authentication header, parameter value, SQL text,
personal identifier, real endpoint, or private network value belongs in a public
artifact. SQL text and default telemetry metadata can be sensitive even when the
dataset is synthetic.

### Automated cloud collection and its limits

Managed cloud jobs automatically collect database configuration, metric
definitions/time series and correlated workspace logs through managed-identity
REST, without Azure CLI inside the runner. Inspect `collection-coverage.json`
and manifest coverage. Missing required configuration, CPU/data-I/O/log-I/O/
workers/sessions, correlated logs or serverless billed vCore-seconds results
in incomplete collection and nonzero exit. Optional-source gaps stay explicit.
Archived failure artifacts do not mean monitoring succeeded.
`measured`/`measured-with-gaps` apply to the declared Azure Monitor plus read-only
SQL-observer scope, not all POC requirements or production performance.

After a fresh control-plane Online check, non-idle collection also uses the same
approved identity for bounded SQL/Query Store observer reads through `NullPool`.
Contained SQL `CONNECT` and `VIEW DATABASE STATE` are required separately from
Azure RBAC; no application-table/write/admin grants or dynamic privilege elevation.
Unavailable required observer sections make collection incomplete. Idle windows
and explicit `--skip-sql` omit these reads and record the gap. Public retail
pricing is attempted separately; missing prices are not fabricated. Protected API
pre/post dataset observation is separate and excluded from the measured window.
Its metadata SELECTs can nevertheless warm SQL caches; record that influence.
Do not query SQL during idle. See the
[environment, audiences and coverage contract](evidence-guide.md#cli-free-cloud-monitoring-collector).

### Actual application telemetry paths

The API creates OpenTelemetry `SERVER` request spans and parented `CLIENT`
`sql.execute` spans. Azure Monitor export is optional and must be configured and
verified; local span-parenting tests do not demonstrate Azure ingestion.
Structured console `operation_attempt` and `operation_final` events remain the
authoritative attempt/outcome source for this application.

There is no application log exporter configured by this mechanism. Do not assume
those console events appear in `AppTraces` merely because request/dependency
spans are exported. `AppTraces` needs a separately verified ingestion path.
Container Apps console collection can instead make the JSON events available
through the environment's configured log destination. Verify schema, ingestion,
sampling, timestamps and run identity before using any table in a report.

Importable starting points are provided in
[the dashboard guide](../dashboards/README.md),
[Azure Workbook JSON](../dashboards/workbook.json), and
[Grafana JSON](../dashboards/grafana.json). Reusable KQL lives under
`dashboards\kql`. Configure approved data-source/workspace parameters privately
and inspect real schemas before use; these files are templates, not deployed
dashboards or screenshots of measured results.

## Azure portal walkthrough

Portal labels and grouping change over time. Choose the correct resource and UTC
window; include selected metric/aggregation/granularity in a private screenshot.
Public documentation uses placeholders only, never customer screenshots.

| Destination | Navigation and what to inspect | Screenshot placeholder |
| --- | --- | --- |
| SQL database | Azure portal → SQL databases → selected POC database | `[SCREENSHOT PLACEHOLDER: database resource navigation, identifiers removed]` |
| Overview | Database → Overview; status and configuration summary | `[SCREENSHOT PLACEHOLDER: overview, no identifiers]` |
| Monitoring | Database → Monitoring group; available tools | `[SCREENSHOT PLACEHOLDER: monitoring menu]` |
| Metrics | Monitoring → Metrics; database scope, namespace, metric, UTC, 1-minute grain, aggregation | `[SCREENSHOT PLACEHOLDER: CPU/IO/workers/sessions aligned chart]` |
| Alerts | Monitoring → Alerts; rule state, signal, action group, history | `[SCREENSHOT PLACEHOLDER: disabled configurable POC alert]` |
| Diagnostics | Monitoring → Diagnostic settings; available categories and destination | `[SCREENSHOT PLACEHOLDER: selected categories and retention policy]` |
| Activity Log | Database or logical server → Activity log; bounded operations/status | `[SCREENSHOT PLACEHOLDER: scale/pause/resume/failover timeline]` |
| Resource Health | Database → Help/Support → Resource health; resource-specific event | `[SCREENSHOT PLACEHOLDER: resource health with identifiers removed]` |
| Service Health | Portal → Service Health; subscription/region/service impact | `[SCREENSHOT PLACEHOLDER: service health event summary, no identifiers]` |
| Intelligent Performance | Database → Intelligent Performance grouping where available | `[SCREENSHOT PLACEHOLDER: performance navigation]` |
| Query Performance Insight | Intelligent Performance → Query Performance Insight; top queries and time filter | `[SCREENSHOT PLACEHOLDER: query summary without SQL text]` |
| Automatic tuning | Intelligent Performance → Automatic tuning; desired/actual settings and recommendations | `[SCREENSHOT PLACEHOLDER: tuning options and status]` |
| Compute and storage | Database → Settings → Compute + storage; tier, hardware, capacity, size, serverless bounds/delay | `[SCREENSHOT PLACEHOLDER: configuration without resource identifiers]` |
| Failover groups | Logical SQL server → Data management/Settings → Failover groups | `[SCREENSHOT PLACEHOLDER: primary/secondary roles and policy, endpoints removed]` |
| Geo-replication | Database → Data management → Replicas/Geo-replication, label varies | `[SCREENSHOT PLACEHOLDER: replication state and role, regions generalized]` |
| Backups | Logical SQL server → Data management → Backups; retention and redundancy settings | `[SCREENSHOT PLACEHOLDER: backup retention and restore availability]` |
| Restore | Database Overview → Restore or server Backups → available restore operation | `[SCREENSHOT PLACEHOLDER: restore to new database, no execution implied]` |
| App requests/dependencies | Application Insights → Investigate → Performance/Failures | `[SCREENSHOT PLACEHOLDER: matched request/dependency percentiles]` |
| Logs | Log Analytics workspace or resource → Logs; inspect tables/schema | `[SCREENSHOT PLACEHOLDER: schema and aggregate KQL output only]` |
| App/job logs | Container Apps resource/job or environment → Monitoring → Logs; execution details | `[SCREENSHOT PLACEHOLDER: safe run metadata and persistence receipt, identifiers removed]` |
| Private evidence | Storage account → Data storage → Containers; access requires approved identity/network | `[SCREENSHOT PLACEHOLDER: run file inventory and hashes, no account/container identifiers]` |

## Logs: schema first

The following are real documented tables, **not a promise they exist in every
workspace**:

| Table | Prerequisite and safe use |
| --- | --- |
| `AppRequests` | Workspace-based Application Insights request ingestion; standard `TimeGenerated`, `DurationMs`, `Success`, `ResultCode`, `OperationId`, `Properties`, `ItemCount` |
| `AppDependencies` | Dependency instrumentation/export; standard `DurationMs`, `Success`, `DependencyType`, `OperationId`, `Properties`; do not export `Data`/targets |
| `AppTraces` | Trace export enabled; `Message`, `Properties`, `OperationId`; custom run/error/retry field names require inspection |
| `AzureMetrics` | Diagnostic export of supported metrics; `MetricName`, `Average`, `Maximum`, `Total`, `TimeGenerated`; not every metric supports export |
| `AzureDiagnostics` | Resource diagnostics using this table; `Category`, `TimeGenerated`, resource metadata and category-specific fields; inspect columns and `AdditionalFields` |
| `AzureActivity` | Subscription Activity Log exported to workspace; `OperationNameValue`, `ActivityStatusValue`, `CategoryValue`, `TimeGenerated`; contains sensitive caller/claims metadata |
| `ContainerAppConsoleLogs_CL` | Container Apps console logs sent to Log Analytics using this schema; `TimeGenerated`, `Log_s` and app/revision metadata; inspect actual environment/job schema |

Run only against a table confirmed in the workspace:

```kusto
AppRequests | getschema
```

Then inspect a bounded sample **privately** to identify actual custom properties.
Do not export raw schema samples or all columns to the public repo. There is no
assumed `PauseEvents` table. If an exporter uses a different schema, adapt the
following clearly marked templates and record the mapping.

### Requests, latency, and failures

**Template:** substitute UTC timestamps and the actual run-ID property key locally.
`<run-property-key>` is not a claim about the configured SDK.

```kusto
let start = todatetime("<start-utc>");
let stop = todatetime("<end-utc>");
AppRequests
| where TimeGenerated between (start .. stop)
| where tostring(Properties["<run-property-key>"]) == "<test-run-id>"
| summarize SampledRows=count(),
            EstimatedRequests=sum(ItemCount),
            EstimatedFailures=sumif(ItemCount, Success == false),
            p50=percentile(DurationMs, 50),
            p95=percentile(DurationMs, 95),
            p99=percentile(DurationMs, 99)
  by bin(TimeGenerated, 1m)
```

Percentiles here are of ingested rows, not reconstructed unsampled requests.
For failed API detail, add `where Success == false` and project only safe
`TimeGenerated`, `ResultCode`, and `DurationMs` aggregates. Raw client timeouts
may never appear as a completed AppRequests record.

### Database dependency latency and failures

```kusto
AppDependencies
| where TimeGenerated between (todatetime("<start-utc>") .. todatetime("<end-utc>"))
| where tostring(Properties["<run-property-key>"]) == "<test-run-id>"
| summarize Calls=sum(ItemCount), Failures=sumif(ItemCount, Success == false),
            p95=percentile(DurationMs, 95), p99=percentile(DurationMs, 99)
  by DependencyType, bin(TimeGenerated, 1m)
```

Inspect actual dependency type values before filtering SQL. Correlate requests
and dependencies by `OperationId` privately, within the same run/time scope; a
one-to-many join duplicates request rows, so aggregate attempts before joining.

### Retry, timeout, and error categories

**Custom-property template:** inspect actual logger fields before executing.
Count attempts separately from final outcomes.

```kusto
AppTraces
| where TimeGenerated between (todatetime("<start-utc>") .. todatetime("<end-utc>"))
| where tostring(Properties["<run-property-key>"]) == "<test-run-id>"
| extend Category=tostring(Properties["<error-category-property>"]),
         Decision=tostring(Properties["<retry-decision-property>"])
| summarize Events=count() by Category, Decision, bin(TimeGenerated, 1m)
```

If JSON goes to console rather than AppTraces, parse the actual structured log
message privately and map fields. A plain text search for “timeout” is discovery,
not reliable classification or rate calculation.

### Platform metric trends and billed compute

```kusto
AzureMetrics
| where TimeGenerated between (todatetime("<start-utc>") .. todatetime("<end-utc>"))
| where _ResourceId =~ "<database-resource-id>"
| where MetricName in ("cpu_percent", "workers_percent", "sessions_percent")
| summarize ObservedMaximum=max(Maximum), ObservedAverage=avg(Average)
  by MetricName, bin(TimeGenerated, 1m)
```

Validate metric names and export grain locally. Use Total over nonoverlapping
`app_cpu_billed` intervals for vCore-seconds; do not sum overlapping exports,
average percentages into a bill, or silently ignore missing intervals.
Use the platform metrics API when diagnostic export is unavailable.

### Deadlocks, diagnostic errors, and availability events

First discover actual categories:

```kusto
AzureDiagnostics
| where TimeGenerated between (todatetime("<start-utc>") .. todatetime("<end-utc>"))
| where _ResourceId =~ "<database-resource-id>"
| summarize Events=count() by Category
```

Then select the enabled error/deadlock/availability category and its inspected
schema. Do not invent a category-specific error column. Keep deadlock graphs and
SQL text private; export classified counts/timing only. Service availability also
needs Resource Health and client evidence, not merely diagnostic error counts.

### Scale, failover, pause, and resume

```kusto
AzureActivity
| where TimeGenerated between (todatetime("<start-utc>") .. todatetime("<end-utc>"))
| where ResourceId =~ "<resource-id>"
| project TimeGenerated, OperationNameValue, ActivityStatusValue, CategoryValue
| order by TimeGenerated asc
```

Start with discovered operation names/statuses. Pause/resume operation names and
resource scope can vary; do not hard-code a fictional event. Corroborate
control-plane state and operation times with first-request/client recovery.
Exporting Activity Log requires separate subscription-level configuration.
When no rows exist, check scope, export, retention and ingestion before concluding
an event did not happen.

### Runner job persistence receipt

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated between (todatetime("<start-utc>") .. todatetime("<end-utc>"))
| where Log_s contains "POC_EVIDENCE"
| project TimeGenerated, Log_s
```

Use only after verifying the table/columns for the job destination. `Log_s` remains
private until sanitization. `POC_EVIDENCE` carries file/hash/byte/prefix receipts
only, never raw or sanitized artifact payloads. `POC_EVIDENCE_UPLOAD` records the
prefix/full manifest hash/count. The private completion manifest also holds the
complete inventory and per-file hashes for verification.
Retrieve full artifacts from
private Blob Storage through approved identity and VNet connectivity, then verify
inventory/hashes. An upload failure must fail the run; success in a smoke count
does not excuse persistence failure. See [evidence](evidence-guide.md).

## Alert workflow

Alert templates remain disabled until an owner approves conditions, routing and
noise review. All 14 signal definitions are represented in IaC, including
scheduled-query and event-driven rules; the serverless metric rule is
conditional. The three scheduled-query resources are **omitted unless alerts
are explicitly enabled**; metric/activity rules remain disabled by default.
Disabled state and `skipQueryValidation=true` do not guarantee creation avoids
query execution against missing tables. Verify real ingestion and schema first.
See [alert runbooks](alerting-guide.md). Validate an alert with a
controlled signal and verify notification routing privately before relying on it.
For C2 idle tests, avoid diagnostic collectors that execute SQL.

## Official schema and operations references

- [AppRequests](https://learn.microsoft.com/azure/azure-monitor/reference/tables/apprequests),
  [AppDependencies](https://learn.microsoft.com/azure/azure-monitor/reference/tables/appdependencies),
  [AppTraces](https://learn.microsoft.com/azure/azure-monitor/reference/tables/apptraces)
- [AzureMetrics](https://learn.microsoft.com/azure/azure-monitor/reference/tables/azuremetrics),
  [AzureDiagnostics](https://learn.microsoft.com/azure/azure-monitor/reference/tables/azurediagnostics),
  [AzureActivity](https://learn.microsoft.com/azure/azure-monitor/reference/tables/azureactivity)
- [Container Apps log schemas](https://learn.microsoft.com/azure/container-apps/log-monitoring)
- [SQL diagnostics](https://learn.microsoft.com/azure/azure-sql/database/metrics-diagnostic-telemetry-logging-streaming-export-configure)
- [Serverless monitoring](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-monitor)
