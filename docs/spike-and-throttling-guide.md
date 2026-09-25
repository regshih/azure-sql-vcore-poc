# Spikes, resource pressure, and request outcomes

Azure SQL does not have one universal overload response. More demand may cause
longer execution, queueing, pool waiting, worker/session pressure, connection
failure, timeout, SQL error, retry, load shedding, circuit rejection, deadlock,
blocking, or reduced throughput. None is proven merely by high latency.
Live throttling: **Not demonstrated by this POC run.**

Serverless automatically varies compute within supported configured bounds. It
is not traditional burst credits, unlimited compute, or instantaneous expansion.
The maximum remains a ceiling. Provisioned and serverless both require
application-side overload controls.

## Safe spike procedure

1. Confirm the disposable POC scope, cost budget, stop conditions and permissions.
   Stop thresholds are a **POC assumption, not a confirmed customer requirement.**
   Customer accepted error/latency objectives remain **TBD**.
2. Establish a normal baseline, then rapid ramp, configured 1/5/15-minute spike,
   ramp-down, and recovery. Use identical profile hashes against 2 vCores,
   4 vCores, and C1 serverless; label C2 after idle as a separate experiment.
3. Fix app instances/workers, pool sizes, concurrency, retry policy, cache state,
   query/index state, dataset and instrumentation. Separate runner saturation
   from service saturation.
4. Collect per-request timing, classified failures, attempt numbers, queue/pool
   waits, dependency spans, SQL CPU/I/O/workers/sessions, plans/waits, and activity.
5. Stop the load if agreed safety limits are breached. Do not disable timeout,
   concurrency, network, or retry bounds to “complete” a test.
6. Observe return to stable operation and whether queued/retried work prolongs
   recovery. Preserve failure samples, including failed requests excluded from
   a particular successful-request percentile.

## Outcome taxonomy and attribution

| Required outcome | Minimum distinguishing evidence | Do not infer from |
| --- | --- | --- |
| Completed normally | Final success, one attempt, validation where applicable | Status alone without business-write validation |
| Completed after retry | Correlated attempts followed by success | Extra dependency spans without attempt metadata |
| Client-side timeout | Runner deadline/timeout at client boundary | Missing server response alone |
| API timeout | API request deadline exceeded with classified outcome | Every gateway error |
| Database command timeout | Driver/command timeout category and elapsed context | Slow API response |
| Database transient error | Sanitized SQL code classified by reviewed transient policy | Any database exception |
| Database nontransient error | Known nonretryable SQL error classification | Retry exhaustion alone |
| Connection-pool timeout | Bounded checkout wait expired before SQL execution | High SQL sessions alone |
| API load-shed response | Explicit admission-control reason and response | Every rejected HTTP request |
| Circuit-breaker rejection | Circuit open/half-open policy denies attempt | Database unavailable assumption |
| Deadlock victim | Sanitized SQL deadlock-victim signal; safe correlated diagnostics | Blocking or lock waits |
| Cancelled request | Explicit cancellation/disconnect signal and propagation record | Assuming SQL stopped when client left |
| Unknown and requiring investigation | Incomplete/unrecognized signal retained as unknown | Guessing a more convenient category |

Each failed or retried operation needs run ID, correlation ID, operation,
UTC timestamp, attempt number, error category, sanitized error code, retry
decision/delay, final outcome, total elapsed time, and target role where known.
Absence of any field is a coverage limitation. Never log tokens, passwords,
authentication headers, full connection configuration, SQL parameter values,
personal information, or raw driver errors containing environment identifiers.

### Runner outcome normalization

The runner separates HTTP status/retry observations from its final outcome
taxonomy. A missing or unrecognized `X-POC-Outcome` is **`Unknown`**, regardless
of status code or retry headers, unless the client actually measured a timeout
exception. HTTP 200 does not supply a missing success classification; HTTP 504
does not supply a client-timeout classification.

| Signal | Normalized treatment |
| --- | --- |
| Recognized `completed_after_retry` | Preserve the completed-after-retry final category |
| Recognized `database_connection_timeout` | Database transient error; retain the allowlisted native subtype |
| `invalid_request`, `not_found`, `business_failure` | `Unknown` in the required taxonomy, with the allowlisted native subtype retained |
| Missing/unknown outcome header, including a server `client_timeout` alias | `Unknown`; neither HTTP status nor retry count repairs the missing classification |
| Actual measured client Timeout exception | Client-side timeout, based on the client boundary rather than a response-header claim |

Locust request records and the idle first-request record preserve `native_outcome`
only through the fixed native allowlist. Unrecognized header text must not be
copied into that field or published. Keep the normalized category and permitted
native subtype separate; neither establishes SQL throttling without corroborating
SQL/resource evidence. Report HTTP error counts separately when their definition
differs from these outcome counts.

## Retry classification and limits

| Error class | Default decision principle |
| --- | --- |
| Service-recognized transient unavailability/resource errors | Retry only allowlisted codes within deadline, maximum attempts, budget and circuit policy |
| Authentication/authorization | Do not retry blindly; repair identity, grants or configuration without logging token |
| Invalid query/schema/constraint/business validation | No automatic retry; fix caller or deployment; conflicts need domain handling |
| Deadlock victim | A bounded retry can be appropriate for an idempotent/replay-safe entire transaction |
| Command timeout | Not inherently transient; evaluate cancellation, uncertain write outcome and remaining budget |
| Connection timeout | Classify networking versus service transient state; bounded retry only if policy permits |
| Application cancellation | Stop new attempts; propagate cancellation where supported |
| Unknown error | Do not silently classify as transient; preserve sanitized context for investigation |

Exponential backoff plus randomized jitter prevents synchronized retries only
when **bounded**. A retry budget limits amplification across requests. Do not
reset the full request deadline for each attempt. Pool limits are per process;
all workers, replicas and jobs contribute to total connections. Increase neither
pool capacity nor concurrency without measuring the effect.

Retry/budget/circuit settings are environment-only in the current application;
there is no dynamic retry-storm configuration endpoint. Any approved configuration
change/restart begins a separate controlled run and invalidates process-lifetime
counter subtraction across that restart.

For writes, a stable idempotency key must represent the same logical operation.
Verify duplicate-request handling with the same key and payload, conflict handling
for changed payloads, and readback of committed state after an uncertain outcome.
Do not treat a returned success or a unit test as proof of real failover-safe
transactions.

## Diagnose, then mitigate

- High CPU: top CPU queries and execution count, query/index tuning, then
  supported scale-up if optimized workload still lacks headroom.
- High data/log I/O: scans, rows, cache state, batching, writes and transaction
  shape before changing service tier.
- High workers: blocking, parallelism, fan-out and retry storms.
- High sessions/pool waits: reuse, leaks, per-instance pool cap, long operations.
- Low SQL utilization but slow API: runner/network/app queue/dependency/locking.
- Serverless near ceiling: tune, bound concurrency, consider appropriate cache,
  higher supported maximum or provisioned fit; do not declare serverless failure.

Choose evidence-backed mitigations from [scaling decisions](scaling-decision-guide.md).
Report both benefits and tradeoffs: load shedding sacrifices accepted throughput,
caching can reduce freshness, retries increase latency/demand, and more capacity
costs more. [Metrics](metrics-catalog.md) defines sources and common pitfalls.

References: [SQL resource management](https://learn.microsoft.com/azure/azure-sql/database/resource-limits-logical-server),
[connectivity and transient errors](https://learn.microsoft.com/azure/azure-sql/database/troubleshoot-common-connectivity-issues),
[serverless overview](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview).
