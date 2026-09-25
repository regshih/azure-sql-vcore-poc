# POC results template — no measured results supplied

Replace fields only from reviewed sanitized evidence. Unknown customer objectives
remain **TBD**. Default values are a **POC assumption, not a confirmed customer
requirement.** Missing metrics/results must remain exactly
**Not demonstrated by this POC run.**

## 1. Scope and configuration

| Field | Value |
| --- | --- |
| Report version / sanitized run references | TBD |
| Objective and customer acceptance criteria | TBD |
| Run ID, UTC start/end and source artifacts | TBD |
| Service/compute tier and hardware | TBD |
| Provisioned vCores or serverless min/max/memory | TBD |
| Auto-pause setting and actual eligibility | TBD |
| Region, storage cap/used bytes, zone and backup redundancy | TBD; use approved generalized labels publicly |
| DR topology/listener role, if any | TBD |
| API image/version, replica/worker settings and resilience config | TBD |
| Schema/dataset versions, actual size, seed and skew | TBD |
| Verified SQL adapter and dataset_size counts/source | Not demonstrated by this POC run. |
| Before/after dataset fingerprints and mutation counter deltas | Not demonstrated by this POC run. |
| Fingerprint scope and content-equivalence limitation | Aggregate state only; not proof of identical row contents |
| Approved synthetic reset provenance or verified read-only equivalence | Not demonstrated by this POC run. |
| Create-only initial/final snapshots and per-case reset receipt references | Not demonstrated by this POC run. |
| Final snapshot digest verification and reset's non-restored data-loss acknowledgement | Not demonstrated by this POC run. |
| Automated comparison status and independently reviewed validity | Not demonstrated by this POC run. |
| Azure Monitor/SQL-observer coverage, skips and retail-price provenance | Not demonstrated by this POC run. |
| SQL-backed smoke and job-side versus operator-independent archive verification | Not demonstrated by this POC run. |
| Run-specific idempotency namespace and replay handling | TBD |
| Workload hash, phases, duration, rates/concurrency and acceleration | TBD |
| Reference run and single changed variable | TBD |
| Warm-up/cache state, repetition count, sampling/coverage | TBD |
| SQL cache-warming influence of pre/post metadata SELECTs | Not demonstrated by this POC run. |

Do not insert real endpoints, resource names/IDs, personal data or local paths.
Equal seeds/hashes do not establish equal data after mixed writes. Without
verified equivalent starting state, mark the comparison non-equivalent and do
not attribute differences solely to vCore count or compute tier.
The matrix defaults to `non-equivalent-or-unverified`; matching profile hashes
or aggregate fingerprints must not be presented as an automated fairness pass.
Use preserved initial/final snapshots and reset receipts rather than only the
mutable enriched manifest when reviewing what was actually known at each boundary.

## 2. Measured results

| Measure | Result | Evidence reference / definition |
| --- | --- | --- |
| Attempted/completed/successful/failed requests | Not demonstrated by this POC run. | TBD |
| Read/write operations and SQL statement count | Not demonstrated by this POC run. | TBD |
| Achieved throughput / p50 / p95 / p99 | Not demonstrated by this POC run. | TBD |
| Retry rate, attempt amplification, timeout rate | Not demonstrated by this POC run. | TBD |
| Outcome categories, shed count, circuit transitions | Not demonstrated by this POC run. | TBD |
| Queue/active requests/pool wait/utilization | Not demonstrated by this POC run. | TBD |
| Dependency latency and failures | Not demonstrated by this POC run. | TBD |
| CPU/data I/O/log I/O/workers/sessions | Not demonstrated by this POC run. | TBD |
| Failed connections/deadlocks/storage trend | Not demonstrated by this POC run. | TBD |
| Query plans, CPU/duration/reads/waits before and after tuning | Not demonstrated by this POC run. | TBD |
| Scale operation duration and application experience | Not demonstrated by this POC run. | TBD |
| Cache hit/miss/calls avoided/stale-data behavior | Not demonstrated by this POC run. | TBD |
| Serverless app CPU/memory, near-ceiling proxy and coverage | Not demonstrated by this POC run. | TBD |
| Serverless Total billed vCore-seconds | Not demonstrated by this POC run. | TBD |
| Active/idle/paused time and pause/resume events | Not demonstrated by this POC run. | TBD |
| First-request / subsequent / steady resume latency | Not demonstrated by this POC run. | TBD |
| Availability client recovery and write integrity | Not demonstrated by this POC run. | TBD |
| DR role/listener/lag/loss/client recovery/failback | Not demonstrated by this POC run. | TBD |
| Restore validation and recovered data boundary | Not demonstrated by this POC run. | TBD |

Do not average percentiles, conflate attempts with operations, or infer allocated
vCores from `app_cpu_percent` alone. Missing coverage is not zero.

### Application experience and bottlenecks

Observed symptoms: **Not demonstrated by this POC run.**

Correlated signals supporting each hypothesis: **Not demonstrated by this POC run.**

Alternative explanations, runner effects and unresolved anomalies: **TBD**.

Query/index versus capacity versus connection/concurrency effects:
**Not demonstrated by this POC run.**

## 3. Estimated cost — not measured performance

Use [the cost worksheet](cost-guide.md): region, currency, retrieval date, exact
meter/SKU/unit, vCore settings, active/idle/paused hours, billed usage, storage,
backup/zone/DR, monitoring, hosting/cache/network, licensing/reservations and
assumptions. Report sensitivity and missing inputs.

Comparative cost outcome: **Not demonstrated by this POC run.**

**Retail estimates are planning inputs and are not the customer’s final contracted
price.**

## 4. Product documentation

List current official Microsoft URLs, retrieval dates, exact claims and which
configuration they apply to. Product documentation is not measured POC behavior.
Serverless billing considers memory/minimums; failover groups are single-writer
with asynchronous replication; availability differs from DR.

## 5. General guidance

Explain bounded pools/retries/deadlines, query tuning, safe load shedding,
consistency-aware caching, private networking, identity and operational limits.
Label general guidance as such rather than attributing it to unexecuted tests.

## 6. Recommendation

Current decision: **More testing required**.

Candidate: provisioned / C1 serverless / C2 serverless / further experiments.
Tie each recommendation to an approved objective and specific evidence; report
tradeoffs, confidence, cost, rollback and remaining production validation. Do not
claim 10 or 100 users proves capacity or choose Business Critical without evidence.

## 7. Unknowns and next experiment

- Customer SLO/availability/RTO/RPO, budget, idle schedule and staleness: **TBD**.
- Missing/blocked test evidence: **Not demonstrated by this POC run.**
- Hypothesis, controlled change, expected evidence, safety gate and owner: **TBD**.
- Unexecuted local/cloud validation commands and prerequisites: **TBD**.
- Restoration/cleanup/publication approval evidence:
  **Not demonstrated by this POC run.**

Attach [matrix status](test-matrix.md), [serverless report](serverless-decision-guide.md)
and the sanitized manifest. Keep raw artifacts private.
