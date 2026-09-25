# Serverless test procedure

This is a first-class comparison of variable compute **and** idle-cost behavior,
not just a spike demonstration. Suggested GP Gen5 minimum 0.5 / maximum 4 vCores
is a **POC assumption, not a confirmed customer requirement.** Exact supported
configuration must be validated in the selected region. Customer acceptable
resume delay, tail latency, idle schedule, and availability objectives are **TBD**.
Observed serverless scaling, pause, resume, and savings:
**Not demonstrated by this POC run.**

## Preconditions

- Complete provisioned A/B baselines first and retain the original configuration.
- Use the same database, schema/data, workload hashes, app image/one-replica
  settings, network, region, storage and monitoring.
- Verify starting dataset equivalence. Mixed writes require an explicitly
  approved guarded synthetic reset before each comparable run; identical seed
  values alone are insufficient. Preserve fingerprints/mutation counters and
  use fresh idempotency namespaces. Without reset or verified read-only
  equivalence, label the comparison non-equivalent.
- Preserve create-only initial/final snapshots and per-case reset receipts.
  The matrix's [reset option](test-matrix.md#optional-guarded-dataset-reset)
  remains explicit and resets every selected case; matching aggregate hashes
  are not an automated equivalence pass. Pre/post SQL observation occurs outside
  both the no-session idle interval and measured workload UTC window.
- Discover current capabilities for hardware, min/max vCores, memory, pause delay,
  zone redundancy, and backup options. Reject unsupported combinations and record
  any explicitly approved substitutions.
- Record requested and observed serverless min/max values and pause configuration.
- Ensure `app_cpu_percent`, `app_cpu_billed`, user CPU/I/O/workers/sessions,
  client percentiles and outcomes can be captured in the same UTC window.
- Determine which components hold SQL sessions: application pool, admin clients,
  readiness, background tasks, reporting, DMV/Query Store collectors.
- Use an execution environment with the current control-plane client's required
  Azure CLI and authorized identity. The baseline Python image does not include
  `az`; HTTP/Blob smoke success alone does not validate C2 or matrix execution.

## C1: autoscaling without resume

```powershell
.\.venv\Scripts\python.exe -m src.operations.cli switch-compute-tier --config <local-config-path> --compute-tier Serverless --min-vcores 0.5 --max-vcores 4 --auto-pause-delay -1 --confirm-poc
.\.venv\Scripts\python.exe -m src.experiments.runner --profile expected --host <base-url> --product-count <observed-product-count> --observe-dataset-state
.\.venv\Scripts\python.exe -m src.experiments.runner --profile variable-demand --host <base-url> --product-count <observed-product-count> --observe-dataset-state
.\.venv\Scripts\python.exe -m src.experiments.runner --profile spike-1-minute --host <base-url> --product-count <observed-product-count> --observe-dataset-state
```

These are separate run windows with explicit warm-up/recovery, not a single
combined result. Observe low→moderate→high→low→idle/near-idle cycles and sustained
peak where useful. Record utilization response time and uncertainty from sample
granularity; do not infer actual allocated vCore history solely from CPU%.
Compare maximum-relative `app_cpu_percent` separately from user-pool CPU.

For time near ceiling, declare an analysis threshold before the run, such as
app CPU at or above a configurable threshold. Label it a **utilization proxy**,
state interval length and missing coverage, and avoid claiming it proves
allocated maximum compute. Report client latency, throughput, retries, timeouts,
errors, pool waits, workers and sessions alongside it.

## C2: genuine idle, auto-pause, and resume

Current Microsoft guidance permits a minimum auto-pause delay of 15 minutes;
validate current selected-region capabilities rather than hard-coding an obsolete
minimum. Choose an approved delay locally and record it. Never run the
`idle-resume` test with pause disabled.

1. Switch the same database to C2 using the approved supported pause delay.
   Confirm online state and execute a short warm workload.
2. Record last business request UTC. Stop workloads, background jobs and
   SQL-connected diagnostics. Dispose/close application pools and administration
   sessions; stopping a load generator alone may leave pooled sessions.
3. Keep `/healthz` process-only. Disable periodic SQL readiness calls and any
   external synthetic probe that touches the database for this experiment.
4. Observe state with **control-plane** resource status/Activity Log, not SQL
   queries. Wait beyond the configured delay with a documented bounded margin.
5. Require observed `Paused` state and supported pause evidence. If no pause
   occurs, do not fabricate one: record sessions/features/probes checked and
   **Not demonstrated by this POC run.**
6. Prepare the API process without issuing SQL or readiness first. The designated
   trigger is exactly one timed API operation. Capture client start, each attempt,
   retry delay, final status, and total elapsed time; the first request may fail
   within its deadline before the database finishes resuming.
   Preserve its normalized outcome and fixed-allowlisted `native_outcome`.
   HTTP 504 or a server `client_timeout` header is not proof of a client Timeout
   exception; missing/unrecognized outcome metadata remains `Unknown`.
7. Observe control-plane resume events/state and then a controlled subsequent
   request stream. Separate first-request, recovery-period, and stable-state
   latency distributions.
8. Validate writes by readback/idempotency where applicable. Collect Query Store
   and DMVs only **after** the idle/resume observation window.
9. Repeat the trial where feasible; one first request is not a measured p99.
   Restore original configuration and monitoring behavior.

```powershell
.\.venv\Scripts\python.exe -m src.experiments.runner --profile idle-resume --host <base-url> --product-count <observed-product-count> --config <local-config-path> --allow-host <base-url> --allow-unsafe-test --confirm-poc --confirm-no-other-sql-clients --pause-timeout <wait-seconds>
```

Use the runner's actual `--help` and profile to configure idle duration and
eligibility controls; a scripted wait alone is not proof of pause. C2
business-hours-plus-idle testing needs real idle time, not merely a compressed
zero-rate phase shorter than the pause delay.

`--pause-timeout` must exceed the observed configured pause delay plus the
runner's platform slack (default 600 seconds); tune the bound deliberately.
`--pause-interval` controls control-plane observation frequency. Protected
maintenance/metrics endpoints require the optional private control-token setup
described in [workloads](workload-guide.md#controlled-internal-endpoints).
The runner verifies pool disposal and process-only readiness before waiting.
The confirmed maintenance `idle` action drains/disposes the pool, suspends SQL
readiness and rejects application work until confirmed `resume`. Verify the same
process `instance_id` throughout. Plain metadata reads are process-only; never
request `refresh_database=true` during the idle interval. Resuming maintenance
must not issue a SQL readiness probe before the designated first timed request.
Metadata SELECTs can warm SQL caches. Excluding them from measured UTC bounds
does not remove this effect; defer post-idle state refresh until after the
designated first-request/resume observations and disclose its warm-up influence.
Successful disposal reports idle state, pool disposal, process-only readiness,
suspended admission and the instance identity. In-flight database/readiness work
must drain first; a drain timeout is a failed precondition, not successful idle.
Admission remains suspended after a failed drain: investigate and explicitly
resume only when safe. Do not start the pause timer on a timeout response.
During confirmed idle, `/readyz`, plain metadata and metric snapshots are
process-only; explicit database metadata refresh is blocked. Resume does not
open SQL—the designated first API request does. Independent SQL sessions can
still prevent pause, even when this process correctly drained.
The evidence collector attempts SQL by default when configuration is supplied.
During idle observation use its explicit `--skip-sql` or postpone collection;
an Online state check does not prevent a diagnostic query from resetting the
pause timer. See [bounded SQL diagnostics](evidence-guide.md#bounded-sql-diagnostics).
For Test 13 use `business-hours` with `--idle-after` and the same approval,
configuration and no-other-clients flags.

## Reasons pause may not occur

Auto-pause requires zero user sessions and zero user-workload CPU throughout the
pause delay. Connection pooling, readiness, diagnostics, reporting, scheduled
tasks, and external monitoring can prevent it. Geo-replication/failover groups,
long-term backup retention, and SQL DNS aliases are documented blockers. Check
the current full exclusion list and resource state. C2 must not silently disable
required availability/retention features just to obtain a cost-saving result.

## Collection worksheet

| Field | Evidence or required value |
| --- | --- |
| Run/profile/hash, UTC, versions, region, storage, backup, zone settings | Private run manifest |
| Observed min/max vCores, min memory, pause delay and feature exclusions | Configuration and capability snapshot |
| User/app CPU, memory if exposed, I/O, workers/sessions | Full time series with units, aggregation, coverage |
| `app_cpu_billed` | Total vCore-seconds over nonoverlapping exact intervals |
| Time near ceiling | Declared threshold, source, interval and coverage; proxy limitation |
| Pause/resume event timestamps and state | Control-plane evidence, not inferred from no requests |
| Active / idle / observed paused durations | Distinct intervals with coverage and definition |
| First request / subsequent p50,p95,p99 / stable p50,p95,p99 | Client samples, including outcome and retries |
| Retry/error/timeout rates | Defined logical-operation denominator plus attempt amplification |
| Compute/storage/monitoring/hosting/network price inputs | [Cost worksheet](cost-guide.md), dated regional currency inputs |
| Customer acceptance | TBD until customer approves; do not retrofit thresholds |
| Result when any necessary field is absent | Not demonstrated by this POC run. |

The documented 0.5–4 GP example has 2.1 GB minimum memory, which gives an
**active minimum billed compute of 0.7 vCore** using memory/3. Storage and other
services remain billed while paused. There is no cost winner before observed
usage and current pricing are compared.

Sources: [overview](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview),
[pause/resume](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-auto-pause-resume),
[monitor](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-monitor),
[billing](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-billing).
