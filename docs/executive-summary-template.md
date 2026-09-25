# Executive summary template

This is an unpopulated decision template, not a benchmark or customer conclusion.

## Objective

Evaluate Azure SQL Database vCore cost, performance, availability and operations
for an internal read-heavy scenario. Approximately 10 initial / 100 future users,
50,000 daily reads and sub-5-GB POC data are context, not capacity proof.
Approved response-time, availability, RTO/RPO, budget and idle requirements:
**TBD**.

## What was compared

General Purpose provisioned 2 vCores, same database at 4 vCores, query/index and
cache changes, serverless C1 without pause and C2 with supported auto-pause.
Settings are a **POC assumption, not a confirmed customer requirement.**
Optional HA/DR/restore operations require separate approval.

Actual executed configurations and comparable run references:
**Not demonstrated by this POC run.**

## Findings

| Question | Finding |
| --- | --- |
| Can baseline support the agreed workload with headroom? | Not demonstrated by this POC run. |
| Does 4-vCore scaling improve client experience? | Not demonstrated by this POC run. |
| Can tuning or appropriate caching avoid scaling? | Not demonstrated by this POC run. |
| What happens during spikes and how does the app recover? | Not demonstrated by this POC run. |
| Does serverless match variable demand and genuine idle time? | Not demonstrated by this POC run. |
| Are resume latency and operational tradeoffs acceptable? | Not demonstrated by this POC run. |
| What HA/DR/restore behavior was observed? | Not demonstrated by this POC run. |
| Which configuration has lower modeled total cost? | Not demonstrated by this POC run. |

## Recommendation and next decision

**More testing required.** Replace only after linking approved objectives and
sanitized evidence. Do not force a provisioned/serverless winner. Identify the
next controlled experiment, owner placeholder, required input, safety gate,
expected decision and rollback.

## Cost and limitations

Retail estimates require current regional/currency meters and actual usage;
serverless memory/minimums and noncompute costs remain relevant.
**Retail estimates are planning inputs and are not the customer’s final contracted
price.**

Product documentation, local tests and management-operation completion are not
proof of production capacity, zero interruption or RTO/RPO. Attach
[the full report](results-template.md) for controls, missing telemetry,
uncertainty, unexecuted validations and production-readiness work.
