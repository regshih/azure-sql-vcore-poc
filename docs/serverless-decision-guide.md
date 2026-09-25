# Serverless decision report and guide

Use after [C1/C2 tests](serverless-test-guide.md), the
[matrix](test-matrix.md), and [cost analysis](cost-guide.md). This blank report
does not select a winner. Customer criteria remain **TBD**; configurable starting
settings are a **POC assumption, not a confirmed customer requirement.**

## Required findings

| Decision question | Evidence needed | Current finding |
| --- | --- | --- |
| Are idle periods meaningful? | Real source schedule plus measured no-demand/paused intervals, not just acceleration | Not demonstrated by this POC run. |
| Did auto-pause occur? | Control-plane Paused state and pause event/time | Not demonstrated by this POC run. |
| What is resume latency? | First operation end-to-end incl. retries, subsequent stream, repeated trials | Not demonstrated by this POC run. |
| Is resume latency acceptable? | Approved objective TBD; compare failures/deadlines as well as successful requests | Not demonstrated by this POC run. |
| How often/how long near maximum? | Declared maximum-relative utilization threshold, interval and coverage | Not demonstrated by this POC run. |
| Do latency spikes correlate with changing compute demand? | Synchronized app/SQL/pool/control time series; avoid causal inference from correlation alone | Not demonstrated by this POC run. |
| Are retries/timeouts/errors acceptable? | Logical-operation rates and attempt amplification against objectives TBD | Not demonstrated by this POC run. |
| Is estimated compute usage lower? | Total `app_cpu_billed` and exact price meter versus matched provisioned duration | Not demonstrated by this POC run. |
| Which costs remain while paused? | Storage, backups, app, registry, monitoring, endpoints/network inputs | Not demonstrated by this POC run. |
| Is performance less predictable? | Repeated matched runs; p95/p99 distributions and variability by phase | Not demonstrated by this POC run. |
| Is a higher minimum necessary? | Controlled minimum change and latency/memory/billing effects | Not demonstrated by this POC run. |
| Does a higher minimum remove the benefit? | Updated active floor and modeled usage with sensitivity range | Not demonstrated by this POC run. |
| What prevents pause? | Pools, readiness, diagnostics, scheduled tasks, feature exclusions | Not demonstrated by this POC run. |
| Is provisioned operationally simpler? | Actual runbooks, readiness/resume handling, alert noise, maintenance effort | Not demonstrated by this POC run. |
| Which model fits the measured pattern? | All above plus availability/DR requirements and comparable controls | Not demonstrated by this POC run. |

## Decision paths

- **Provisioned** is a candidate for steady active demand, tight first-request
  requirements, repeatedly near-ceiling demand, or simpler operations—only when
  measured performance and total modeled cost support it.
- **Serverless C1** is a candidate for variable active demand where pause is
  ineligible/unacceptable, if the configured bounds, memory-related billing and
  predictability still fit.
- **Serverless C2** is a candidate for genuine pause-eligible idle periods where
  measured resume latency and feature tradeoffs are acceptable.
- **More testing required** is the correct choice for missing pricing, unmatched
  workloads, absent pause proof, inadequate repetitions, unknown objectives or
  incomplete telemetry.

Do not choose serverless just because traffic is “spiky,” or provisioned just
because a unit rate looks lower. A 0.5-vCore minimum is not necessarily the active
billing minimum: documented GP 0.5–4 with 2.1 GB minimum memory bills at least
0.7 vCore while active. `app_cpu_billed` is the observed billing input; CPU% is not.

## Report structure

1. **Measured results:** run IDs, exact configurations, windows, comparable controls,
   coverage, outcomes and variability.
2. **Estimated cost:** current regional/currency meters, active/idle/paused usage,
   total vCore-seconds, remaining services, discounts modeled separately.
3. **Product documentation:** dated current references, no substitution for
   measured behavior.
4. **General guidance:** bounded autoscaling, pause eligibility, client resilience.
5. **Recommendation:** candidate above, reason, tradeoffs and confidence;
   customer approval still required.
6. **Unknowns:** TBD inputs, missing evidence, next experiment and rollback.

Current recommendation: **More testing required**.

References: [serverless billing](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-billing),
[auto-pause](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-auto-pause-resume),
[monitoring](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-monitor).
