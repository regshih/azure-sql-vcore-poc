# Scaling decision guide

Do not size from 10/100 users, daily volume, a single slow query, or one metric.
General Purpose provisioned 2 vCores is a **POC assumption, not a confirmed
customer requirement.** Required latency, peak demand, headroom, availability
and budget remain **TBD**. Production sizing: **Not demonstrated by this POC run.**

## Diagnostic decision table

| Correlated observation | Investigate before changing capacity | Controlled next experiment |
| --- | --- | --- |
| p95/p99 rise; CPU and I/O low | Network placement, runner limits, app queueing, pool acquisition, blocking, plan regressions, dependency latency | Split client/app/pool/SQL timings; fix one suspected cause and replay |
| CPU sustained high | Top CPU queries, execution count/fan-out, unnecessary reads, plans and indexes | Tune, repeat identical load; scale only if optimized workload still lacks needed headroom |
| Data I/O sustained high | Logical/physical reads, scans, returned rows, cache state, indexes, query shape | Index/query A/B; consider service tier only after evidence |
| Log I/O sustained high | Write rate, transaction size, batching, unnecessary indexes, long transactions | Reduce avoidable write work; validate durability/idempotency and replay |
| Workers pressured | Blocking, parallel queries, fan-out, long-running work, retry storms | Bound concurrency/retries and tune; compare waiting and completed throughput |
| Sessions/connections pressured | Pool reuse/lifetime/leaks, app instance/worker count, auth failures, retry amplification | Correct bounded pooling; compare connections/second and checkout wait |
| Serverless near max | Configured maximum is a ceiling; tune, remove unnecessary concurrency, evaluate cache | Compare a supported higher max or provisioned model; not proof serverless “failed” |
| Serverless usually near minimum | Possibly oversized minimum; memory floor; whether variable capacity has value | Lower supported minimum only if safe; compare latency, billed usage and operational simplicity |
| Auto-pause never occurs | Pools, health/readiness/monitoring queries, background reporting, scheduled work, feature exclusions | Genuine no-session idle trial; model C1 economics if required features prohibit pause |
| Resume latency unacceptable | First-request objective, deadline, retries, readiness schedule | Disable pause, pre-activate for planned usage with cost disclosure, or provisioned comparison |
| 4 vCores raise throughput but not individual-query latency | Single-query limits, query shape, locking, network and application overhead | Compare per-operation plans/timings at matched arrival rates |
| Storage rising toward 5-GB POC cap | Dataset generation, retention, allocated versus used bytes, index overhead | Stop growth before cap; reapprove POC scope rather than silently increasing cost |
| Business Critical proposed | Low-storage-latency, sustained I/O, transaction, read-scale or replica business requirement | Explicitly approved optional comparison after tuning and cost analysis |

## Evidence required for a scale recommendation

1. Customer objective and headroom target approved privately; otherwise TBD.
2. Reproducible baseline with achieved demand, percentiles, errors, retries,
   timeouts, CPU/I/O/workers/sessions, pool utilization/waits and query evidence.
3. Query/index/pooling/concurrency fixes evaluated independently.
4. Same database, data, hardware/region, storage, app, workload hash/duration,
   monitoring and warm-up for the 2→4 comparison.
5. Operation start/end and application experience during scale, not just steady
   before/after measurements. Capture reconnections and recovery.
6. Repeated outcomes with uncertainty; throughput normalized for workload mix.
7. Updated total cost inputs and documented restoration to original settings.

Scaling changes resource limits, not just CPU; an improvement does not prove
CPU was the sole bottleneck. Query tuning and caching can reduce demand, but cache
freshness and write correctness remain acceptance criteria. Larger pools can make
worker pressure worse. Higher retries can turn a transient problem into overload.

Keep Business Critical opt-in; do not deploy it because the app has 100 users or
General Purpose was not tuned. Hyperscale is not the default for a sub-5-GB POC;
only revisit if material size/growth/read-scale/restore requirements change.

Use [results](results-template.md), [metrics](metrics-catalog.md),
[serverless decision](serverless-decision-guide.md), and
[cost](cost-guide.md) together. An incomplete comparison should recommend the
next experiment, not a guessed production SKU.
