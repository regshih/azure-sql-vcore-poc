# Metrics catalog

Use this catalog as a collection contract, **not** a claim every field is emitted
by every exporter or SKU. Missing observations must read **Not demonstrated by this
POC run.** Never convert missing data to zero. Units, dimensions, aggregation
support, diagnostic exportability, and retention must be discovered for the
selected resource before a test.

Every observation carries run ID, profile, database configuration, compute tier,
vCore settings, region, application/schema/dataset versions, UTC start/end,
sampling interval, collection source, and coverage. Keep real resource identifiers
only in private artifacts. A resource metric does not natively carry the
application run ID: correlate its exact resource scope and UTC window locally.

## Reading the tables

- **A**: Application Insights resource → Investigate → Performance/Failures or
  Monitoring → Metrics; logs in `AppRequests`, `AppDependencies`, or `AppTraces`
  as indicated. Custom counters require explicit instrumentation/export.
- **S**: SQL database resource → Monitoring → Metrics, correct metric namespace
  and dimensions; logs in `AzureMetrics` **only if exported and supported**.
  Platform Metrics remains the fallback when a metric is not log-exportable.
- **E**: SQL database/server → Activity Log and Resource Health, subscription
  Service Health; `AzureActivity` only when exported. SQL diagnostics in
  `AzureDiagnostics` depend on category/destination/schema.
- **R**: runner raw samples and summaries (local ignored artifacts). These
  usually provide unsampled client experience; no automatic portal equivalent.
- **C**: Container Apps/managed environment → Monitoring → Logs; console messages
  in `ContainerAppConsoleLogs_CL` when that destination is configured.

These source mappings are part of each row's portal/log definition. Suggested
windows are investigation defaults: **POC assumption, not a confirmed customer
requirement.** Observe one-second app samples where available, one-minute platform
samples, and a 5–15-minute context window before/after the workload. A one-minute
spike deserves raw client detail, not only a five-minute mean.

## Application metrics

### Implemented request and snapshot sources

The protected `GET /internal/metrics` response contains cumulative
process-lifetime counters, a timestamp and `instance_id`. Capture a baseline
after deliberate metadata/database refresh and immediately before workload, then
an end snapshot from the **same instance**. Calculate deltas only for monotonic
counters, retain each original snapshot, and record unrelated traffic. A restart,
negative delta or instance mismatch invalidates the naive interval calculation.
Gauges require samples, not subtraction; lifetime percentiles cannot be converted
to run percentiles by subtracting snapshots.

Per-request response headers available for collection are `X-POC-Outcome`,
`X-Retry-Count`, `X-DB-Calls`, `X-Cache-Hit`, `X-Pool-Wait-Ms`, `X-Elapsed-Ms`,
`X-Correlation-ID`, and `X-Test-Run-Id`. Preserve source/units and actual header
presence. Missing headers are missing evidence, not zero retries or database
calls. These HTTP observations do not imply automatic Application Insights
custom-property export. Use raw client elapsed time for client end-to-end latency
and distinguish it from server-reported elapsed/pool timing.
Missing/unrecognized `X-POC-Outcome` remains `Unknown` irrespective of HTTP/retry
headers, except for a genuinely measured client Timeout exception. Do not infer
success from HTTP 200 or client timeout from HTTP 504. The fixed-allowlisted
`native_outcome` is a separate subtype, not arbitrary header text. See
[outcome normalization](spike-and-throttling-guide.md#runner-outcome-normalization).

OpenTelemetry request `SERVER` spans and child `CLIENT` `sql.execute` spans use
the optional Azure Monitor trace exporter. Structured console
`operation_attempt`/`operation_final` events are the authoritative application
attempt/outcome records. No log exporter is implied: `AppTraces` alternatives
below require separately verified ingestion, whereas configured Container Apps
console ingestion can expose the JSON events in its console-log table.

`GET /internal/metadata` is process-only unless
`refresh_database=true` is explicitly requested. Pre-run SQL counts/version/
tuning refresh precedes baseline counters; post-run refresh follows end counters.
Neither belongs inside the measured window or serverless idle. All snapshots use approved
private control authentication and networking. Without a control token, the
shared client returns unavailable metadata without probing an anonymous route.
The fresh snapshot supplies `dataset_size` with `product_count`,
`work_item_count` and `counts_source`, plus verified SQL adapter/schema/dataset/
tuning metadata. SQL comparisons require `repository_backend=sql` and
`sql_adapter_configured=true`; a configured flag alone is insufficient.
Memory-backend smoke is not SQL evidence. Maintain the order
refresh → baseline counters → workload → end counters → refresh, keeping both
refreshes outside measurement and idle intervals.

Dataset refresh exposes live `dataset_state` and
`dataset_state_fingerprint`, scoped as `aggregate_state_not_full_content`.
It summarizes state rather than hashing every row; equal fingerprints alone
cannot establish identical row contents. Record reset provenance and this scope.
Seed-ledger metadata such as the original `work_item_count` is historical seed
information, not necessarily the current live count after writes.

| Metric: what it measures / why it matters | Unit; aggregation; window | Interpret with / common misinterpretation | Portal and Logs | SQL alternative |
| --- | --- | --- | --- | --- |
| Requests per second: arriving and completed HTTP demand | requests/s; count divided by elapsed seconds; 1 s and 1 min | Compare target, attempted, accepted, completed; configured rate is not achieved throughput | R; A `AppRequests` counts, sampling-aware | None; SQL execution counts are not HTTP requests |
| Completed operations: logical business outcomes | count; sum by outcome; full run and 1 min | Separate success after retry from attempts; HTTP success may not prove write correctness | R; A/C structured outcomes | Business validation queries, not a general request counter |
| p50 latency: median end-to-end experience | ms; percentile of raw samples; phase/full run | Compare operation/mix; median hides tail pain | R; A `DurationMs` for server-side scope | Query Store duration has different scope |
| p95 latency: 95th percentile | ms; percentile, not mean of percentiles; 1 min/phase/run | Check sample count, exclusions, failed requests; not a customer objective until agreed | R; A `AppRequests.DurationMs` | Query Store is per SQL statement, not end-to-end |
| p99 latency: extreme tail | ms; raw/histogram percentile; phase/run | Requires enough samples and uncertainty disclosure; small samples do not establish reliable tails | R; A `AppRequests.DurationMs` | No equivalent API percentile |
| Error rate: final failed logical requests / attempted logical requests | %; ratio of summed counts; 1 min/run | Break down category/status and client/server scope; a retry attempt is not necessarily a final error | R; A `Success`, `ResultCode` | SQL events cover only database failures |
| Retry rate: requests retried / attempted logical requests; also attempts/request | % and ratio; ratios of totals; 1 min/run | Report both definitions; retries can hide errors and amplify demand | A `AppTraces` or C custom events; R when captured | No general client-retry DMV |
| Timeout rate: final timeout outcomes / attempts, with explicit denominator | %; by client/API/SQL/pool layer; 1 min/run | Classify timeout source; latency alone cannot prove throttling | R; A/C outcome category | `sys.event_log` where recorded; active waits alone cannot prove client timeout |
| Active requests: currently executing or admitted requests | count gauge; mean/max; 1 s/1 min | Correlate arrival/completion and concurrency cap; not connected users | A custom metric or C snapshot | `sys.dm_exec_requests` shows SQL requests only |
| Queue depth: waiting admitted work | count gauge; max and time-weighted mean; 1 s/1 min | Define queue boundary; pool waiters and HTTP queue may differ; not always emitted | A custom metric or C snapshot | No equivalent application queue |
| Load-shed count: explicit admission refusals | count; sum by route/reason; 1 min/run | Confirm handler/reason; any generic error response is not automatically intentional shedding | A/C structured outcomes; R response classification | None |
| Circuit state: closed/open/half-open and transitions | categorical; transition count/time per state; 1 s/run | Open protects dependency; not proof database is down | A/C custom events | None |
| Database pool size: configured cap and current open connections | count; last/max; 1 s/1 min | Include overflow and all workers/replicas; config cap is not actual usage | A/C pool snapshots | `sys.dm_exec_sessions` can corroborate sessions with appropriate rights |
| Checked-out connections: currently borrowed connections | count gauge; max/mean; 1 s/1 min | Include leaks/long transactions; not equivalent to active SQL requests | A/C pool snapshots | Session/request views show different lifetimes |
| Pool utilization: checked out / configured effective pool cap | %; ratio per process then aggregate correctly; 1 s/1 min | State denominator and process count; never average unequal pools blindly | A/C custom metric | No direct server-side equivalent |
| Pool wait time: acquire-start to connection-checkout | ms; p50/p95/p99 and max; phase/run | Distinguish connection establishment and checkout wait; SQL CPU does not explain all waits | A/C pool events | No direct equivalent |
| Cache requests: eligible lookup attempts | count; sum; 1 min/run | Exclude noncacheable routes; all API requests are not cache lookups | A/C cache counters | None |
| Cache hits: entry found and usable | count; sum; 1 min/run | Hit correctness depends on TTL/invalidation; hit does not guarantee freshness | A/C counters | None |
| Cache misses: no usable entry | count; sum; 1 min/run | Separate cold/expired/evicted/errors; miss need not imply successful DB call | A/C counters | None |
| Cache hit ratio: hits / cache requests | %; ratio of totals; phase/run | Report eligible request volume; never infer SQL calls avoided 1:1 | A/C counters | None |
| Database calls avoided: measured difference versus equivalent uncached execution | count; matched-run total; full run | Normalize request mix/volume; do not manufacture from hit ratio | R plus A/C dependency counts | Query Store execution deltas can corroborate |
| Cache expiration and stale-data window | seconds/events; TTL, max observed staleness; controlled write/read phase | Configured TTL is not measured staleness; distributed invalidation differs from memory cache | A/C custom events; explicit runner validation | Version/timestamp readback, not a platform metric |
| Cache memory use | bytes; last/max; phase/run | Process memory includes noncache objects; backend-specific gauge may be unavailable | Optional cache resource Metrics; A/C development gauge if emitted | None |
| Dependency latency: database/network call elapsed time | ms; p50/p95/p99, grouped operation; 1 min/phase | Includes driver/network scope; is not Query Store execution time | A `AppDependencies.DurationMs`; C spans if exported | Query Store weighted duration and waits |
| Dependency failures: unsuccessful dependency attempts | count and %; count/total; 1 min/run | Multiple attempts per logical request; do not equate with user-visible failures | A `AppDependencies.Success`; C outcomes | SQL event/error diagnostics where enabled |
| Cancellation: caller/request cancellation observed by app | count; sum by phase; 1 min/run | Client disconnect does not prove SQL statement stopped; verify cancellation path | R; A/C classified outcomes | Active requests can verify remaining SQL work with permissions |

Application Insights sampling can bias counts and percentiles. `ItemCount` supports
weighted count estimates, not reconstruction of an unsampled latency distribution.
State whether sampling was disabled, weighted, or unknown. Unsampled runner
percentiles and server-side request percentiles have different boundaries.

## Azure SQL and serverless metrics

Metric identifiers are examples from the documented SQL namespace; discover exact
spelling and supported aggregations for the deployed SKU. Some portal display
labels differ from REST identifiers.

| Metric: what it measures / why it matters | Unit; aggregation; window | Interpret with / common misinterpretation | Portal and Logs | SQL alternative |
| --- | --- | --- | --- | --- |
| CPU percentage (`cpu_percent`): user workload CPU relative to its limit | %; average and maximum; 1 min, 5–15 min context | Pair with top CPU queries/waits; low CPU does not prove spare workers or low latency | S | `sys.dm_db_resource_stats`, `sys.resource_stats` |
| Data I/O percentage (`physical_data_read_percent` in platform metrics; SQL views use data I/O fields): physical read pressure relative to limit | %; average/max; 1 min/phase | Correlate logical reads, scans, cache state and latency; not bytes read or disk fullness | S | Resource stats plus Query Store logical/physical reads |
| Log I/O percentage (`log_write_percent`): transaction-log write pressure | %; average/max; 1 min/phase | Check write volume, transaction size, index maintenance; not data-read I/O | S | Resource stats and waits |
| Workers percentage (`workers_percent`): worker limit usage | %; max/average; 1 min, raw waits if available | Blocking, parallelism, fan-out, retries; high usage is not necessarily CPU saturation | S | Resource stats, active requests, waits |
| Sessions percentage (`sessions_percent`): sessions relative to service limit | %; max/average; 1 min | Pool count across replicas, idle sessions, auth failures; sessions are not active users | S | Resource stats; session views with required permissions |
| Successful connections (`connection_successful`): connection successes | count; total; 1 min/run | High count can indicate poor reuse; not completed SQL statements | S | `sys.database_connection_stats` where available |
| Failed connections (`connection_failed`): failed connection attempts | count; total by available dimension; 1 min/run | Separate auth, resource, network and transient causes; not all failures originate at SQL | S, E diagnostics | `sys.database_connection_stats`, `sys.event_log` |
| Connection dimensions: categorized success/failure telemetry | count; total by documented category; 1 min/run | Inspect actual dimensions before grouping; client-only failures may never reach service | S/E | Connection stats/events in logical `master` |
| Deadlocks (`deadlock`): detected deadlock events | count; total; 1 min/run | Retrieve safe graph/context; blocking is not necessarily a deadlock | S, E enabled deadlock diagnostics | Query Store waits are not a deadlock graph; use supported event diagnostics |
| Data space used (`storage` or current supported equivalent): used data storage | bytes; last/max; 5 min/run | Distinguish used, allocated, maximum, backup storage; not all are billed identically | S | `sys.database_files`, file space-used functions |
| Storage percentage (`storage_percent` where supported): use relative to configured maximum | %; last/max and trend; 5 min/days | A flat short run does not prove growth capacity; cap differs from allocated bytes | S | Used bytes / validated configured maximum |
| Database availability (`availability` where supported): service availability signal | % or published metric unit; supported aggregation; 1 min/event window | Inspect metric definition; does not measure entire app or establish an SLA | S plus E | No single SQL query can prove availability while unreachable |
| App CPU (`app_cpu_percent`): app-package vCores used relative to maximum allowed | %; average/max; 1 min/phase | App includes system scope; not interchangeable with user-pool CPU or actual allocated-vCore history | S, serverless | Resource views can corroborate workload only, not a complete allocation trace |
| Billed compute (`app_cpu_billed`): CPU/memory-normalized compute charged in reporting interval | vCore-seconds; **Total**; 1 min and exact run sum | Memory/minimums matter; never estimate by CPU% × duration alone | S; use metrics API if export unavailable | No interchangeable billing DMV |
| App memory (`app_memory_percent` where exposed): memory used relative to app maximum | %; average/max; 1 min/phase | Memory contributes to billing; not direct billed vCores or process RSS | S | Relevant memory views with elevated diagnostic permissions; different scope |
| Configured minimum vCores | vCores; last configuration plus change events; run boundaries | Configuration is not utilization; .5 minimum may imply .7 active billing floor in documented example | Compute and storage; control-plane snapshot; E changes | `sys.database_service_objectives` does not expose every serverless bound |
| Configured maximum vCores | vCores; last configuration; run boundaries | A ceiling, not a promise of immediate allocation | Compute and storage; control-plane snapshot | Service objective/resource governance views where supported |
| Observed compute utilization | % and documented source; series/phase | Report app/user scope and sampling; do not invent allocated cores from percentage | S | Resource stats corroboration only |
| Time near maximum | seconds and % observed coverage; sum intervals above declared utilization threshold | Threshold is a POC assumption; label “near-ceiling utilization,” not proven allocated cores; missing intervals unknown | Derived from S; private analysis | No direct equivalent |
| Pause events and state | event/state with UTC; transition list; idle experiment | Activity Log plus control-plane Paused state; absence of rows does not prove no pause | E; `AzureActivity` if exported | **Do not query SQL during idle** |
| Resume events and state | event/state with UTC; transitions; first request window | Control-plane completion differs from first stable successful request | E plus R | Avoid monitoring SQL until designated resume trigger |
| Idle duration | seconds; contiguous no-demand interval, separately observed paused duration | No requests ≠ no sessions ≠ paused; report all three | R timeline plus E/S | No idle SQL polling |
| Active duration | seconds; observed online intervals; full run, coverage stated | Online time includes idle-but-unpaused time; do not subtract missing data as paused | E plus S; R manifest | No exact billing substitute |
| First-request resume latency | ms; individual end-to-end result including retries; repeated idle trials | One trial is not a p99; include failure/deadline and starting paused evidence | R; A for app-only scope | Query duration alone excludes resume/client time |
| Subsequent-request resume latency | ms; p50/p95/p99 separately after first request; fixed recovery phase | Warm-cache effects may persist; do not blend with steady-state without disclosure | R; A requests/dependencies | Query Store context only |
| Scale/tier-switch duration | seconds; operation start to completion, plus client recovery interval | Azure operation success does not imply zero disruption | E; private operation log and R | Confirm service objective only outside idle experiment |

## Diagnostic and Query Store interpretation

| Diagnostic source | Purpose and permissions | Granularity/retention and limits |
| --- | --- | --- |
| `sys.dm_db_resource_stats` | Recent CPU/I/O/workers/sessions; diagnostic principal with currently required database performance-state rights | Typically 15-second samples for about one hour; verify current documentation; resets/failovers can affect continuity |
| `sys.resource_stats` | Longer resource history, queried in logical `master` with approved server/database monitoring rights | Typically five-minute aggregates up to 14 days; short spikes can be hidden |
| `sys.dm_exec_requests`, `sys.dm_tran_locks` | Active queries, waits, blocking/locks; permission scope affects visibility | Point-in-time snapshots, not historical proof; avoid exporting statement text/parameters |
| `sys.dm_db_wait_stats` | Cumulative database waits; capture interval deltas | Lifetime/reset context required; total cumulative wait is not elapsed wall time |
| `sys.database_files` | File size and used space with metadata permissions | Snapshot; growth requires repeated observations |
| `sys.database_service_objectives` | Current service objective | Snapshot; not a complete history or all serverless settings |
| `sys.database_connection_stats`, `sys.event_log` | Service-recorded connection summaries/failures in logical `master` | View-specific rolling retention/aggregation; read current docs and filter a bounded time; client network failures may be absent |
| `sys.query_store_query`, `sys.query_store_query_text`, `sys.query_store_plan` | Identify query/plan relationships | Captured content may contain sensitive SQL/literals; do not export text by default |
| `sys.query_store_runtime_stats`, `sys.query_store_runtime_stats_interval` | Execution count, duration, CPU, reads by interval/plan | Capture mode, interval length, retention, size cap and read-only state govern coverage; sum execution counts, weight averages by execution count |
| `sys.query_store_wait_stats` | Wait categories by plan/interval | Requires wait-stat capture and supported configuration; overlap and aggregation are not an API latency decomposition |
| `sys.database_automatic_tuning_options` | Desired/actual automatic tuning settings and reasons | Document settings before/after; recommendations do not prove improvement |

Diagnostic scripts should carry purpose, required permissions, output definitions,
interpretation, and retention limits. Use a diagnostic identity distinct from
the API runtime—not runtime privilege escalation. The default cloud observer
uses the runner's separately provisioned contained CONNECT/VIEW DATABASE STATE
grants, NullPool and a fresh Online check after workload completion; idle windows
skip it. Broader catalog examples above are not a claim that every listed view
is collected or authorized by that narrow role. Rank queries independently by CPU, average duration,
total duration, execution count, logical reads, plan regression, and wait category.
Compare like-for-like intervals; a higher total duration may simply mean more
executions. Do not execute Query Store/DMV collectors during an auto-pause wait.

## Sources and validation

- [SQL database supported metrics](https://learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-sql-servers-databases-metrics)
- [Serverless monitoring](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-monitor)
- [Serverless billing](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-billing)
- [Monitoring with DMVs](https://learn.microsoft.com/azure/azure-sql/database/monitoring-with-dmvs)
- [Query Store](https://learn.microsoft.com/sql/relational-databases/performance/monitoring-performance-by-using-the-query-store)
- [Workspace table/schema guidance](monitoring-guide.md#logs-schema-first)

Never declare root cause from one metric. Correlate demand, client latency,
dependency timing, pool pressure, SQL limits, query plans/waits, errors, and
control-plane events in the same UTC window.
