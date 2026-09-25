# Disabled POC alert templates and runbooks

These are reviewable alert definitions, not activated paging. Every default
threshold is a **POC starting point, not a universal production threshold.**
All thresholds, windows and traffic gates are a **POC assumption, not a confirmed
customer requirement.**
Customer objectives and final thresholds are **TBD**. Signal/routing validation:
**Not demonstrated by this POC run.**

The infrastructure implements **14 signal definitions**: eight baseline SQL
metric rules, one conditional serverless metric rule, three scheduled-query
rules, and two event-driven Activity Log/Resource Health rules. The conditional
serverless rule is not part of a provisioned-only deployment. All paging is
disabled by default, owner is **TBD**, and no action group is supplied by default.
Implementation does not prove live metric availability or alert delivery.

Enabling `enable_alerts` requires private `alert_action_group_ids`, an
`alert_owner` other than TBD, and an HTTPS `alert_runbook_base_url`. Scope and
real owner/action-group values must be resolved privately, not committed.
Thresholds are configurable through `alert_thresholds`; aggregation/windows
follow the actual IaC definitions. Activity Log severity is platform-fixed at 4,
not an independently configurable application severity. Validate metric
definitions, actual workspace schemas and denominator behavior before enablement.

| Signal | Illustrative condition and evaluation window | Severity starting point | Runbook and expected operator action |
| --- | --- | --- | --- |
| SQL CPU | Average > 80% for 10 min | 2 | [Scaling](scaling-decision-guide.md): inspect CPU-heavy queries before adding capacity |
| Data I/O | Average > 80% for 10 min | 2 | [Scaling](scaling-decision-guide.md): logical reads, scans, index/query shape |
| Log I/O | Average > 80% for 10 min | 2 | [Scaling](scaling-decision-guide.md): writes, transaction size, indexes and batching |
| Workers | Maximum > 80% for 5 min | 2 | [Spike](spike-and-throttling-guide.md): blocking, fan-out, parallelism, retries |
| Sessions | Maximum > 80% for 5 min | 2 | [Spike](spike-and-throttling-guide.md): pool caps across app workers/replicas and leaks |
| Failed connections | Total > 0 in 5 min | 3 | [Security](security-guide.md): classify auth/network/resource/transient failures |
| Deadlocks | Total > 0 in 5 min | 3 | [Spike](spike-and-throttling-guide.md): safe deadlock evidence and transaction ordering |
| Storage use | Maximum > 80% cap in 15 min | 2 | [Scaling](scaling-decision-guide.md): verify used/max bytes, separately review growth and stop generator before cap |
| Availability event | Resource Health event matching configured conditions; event-driven, not a periodic metric | 4, platform-fixed | [Availability](availability-guide.md): correlate client reachability and Service Health |
| API p95 latency | `AppRequests` p95 > 500 ms over 5 min, with minimum 100 observed rows | 2 | [Metrics](metrics-catalog.md): queue/pool/dependency/SQL correlation; 500 ms is not an approved customer objective |
| API error rate | `AppRequests` failure ratio > 1% over 5 min with minimum traffic gate | 2 | [Spike](spike-and-throttling-guide.md): separate timeout, shedding, auth and dependency outcomes |
| Retry rate | Parsed `ContainerAppConsoleLogs_CL` retry ratio > 5% over 5 min with minimum traffic gate | 3 | [Spike](spike-and-throttling-guide.md): verify event mapping, amplification, budget and classification |
| Serverless near ceiling | `app_cpu_percent` average > 90% over 5 min | 2 | [Serverless](serverless-decision-guide.md): validate ceiling context; not direct proof of allocated cores |
| Failover activity | Relevant operation/status in Activity Log; event-driven | 4, platform-fixed | [Failover](failover-test-guide.md): approved change window, role/listener and stable client recovery |

### Threshold configuration keys

| `alert_thresholds` key | Default |
| --- | --- |
| `cpu` | 80% |
| `dataIo` | 80% |
| `logIo` | 80% |
| `workers` | 80% |
| `sessions` | 80% |
| `failedConnections` | 0; alert on observed Total greater than zero |
| `deadlocks` | 0; alert on observed Total greater than zero |
| `storage` | 80% |
| `serverlessCpu` | 90% |
| `p95Milliseconds` | 500 ms |
| `errorPercent` | 1% |
| `retryPercent` | 5% |
| `minimumRequests` | 100 observed rows; verify each query's actual denominator |

The scheduled-query templates initially use `skipQueryValidation=true` because
real ingestion/schema has not yet been verified. This is a deployment
accommodation, **not query validation**. Run each actual query against observed
tables before enabling notifications and review whether the skip remains
necessary. No synthetic rows or forced zero results should be introduced to
make validation appear successful.

Observed log rows may be sampled, duplicated or incomplete. The
`minimumRequests` key is not proof of that many unsampled business requests.
Validate row/event mappings, deduplication and sampling before interpreting
ratios or percentile thresholds.

## Noise-review contract

Before enabling **each** rule, observe at least one representative baseline,
spike, and maintenance window where practical; measure alert frequency, duration,
missing-data behavior, and false positives. Select dimensions, minimum traffic,
deduplication, resolution behavior, and maintenance suppression. Review the
owner/action-group route with a controlled notification. Record the review date,
decision, and next review privately.

Do not page on every expected POC retry. Do not suppress unexplained errors to
make a result look healthy. Alert on symptoms plus corroborating evidence rather
than one metric claimed as root cause. Idle/paused database missing samples need
an explicit no-data policy, not a forced zero or continuous SQL readiness probe.

Use the implemented infrastructure templates, then verify actual deployment,
query execution, signal transitions, owner routing, action-group delivery and
noise. All 14 definitions are represented in IaC; remaining work is live
verification and customer approval, not an unimplemented log-alert placeholder.
Owner-configured alert delivery: **Not demonstrated by this POC run.**

Reference: [Azure Monitor alerts](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-overview).
