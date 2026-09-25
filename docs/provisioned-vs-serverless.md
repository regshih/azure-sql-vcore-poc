# Provisioned versus serverless

The question is workload fit, not a universal winner. Starting settings are a
**POC assumption, not a confirmed customer requirement.** Customer latency, idle
schedule, budget, and availability requirements are **TBD**. Comparative
performance and cost: **Not demonstrated by this POC run.**

| Dimension | Provisioned A/B | Serverless C1 | Serverless C2 |
| --- | --- | --- | --- |
| Question | Predictable continuously available capacity; effect of 2 versus 4 vCores | Behavior of bounded variable compute without pause | Real idle eligibility, resume experience, and usage-based cost |
| Capacity control | Explicit fixed vCore setting | Validated minimum and maximum | Same bounds plus supported auto-pause delay |
| Suggested POC setting | GP Gen5 2, then 4 vCores | GP Gen5 0.5–4, pause disabled | Same with approved delay |
| Idle compute | Remains provisioned | Active minimum billing remains | Compute billing stops only while paused |
| First request | No intentional auto-pause resume | No intentional auto-pause resume | Resume can delay/fail first attempts; measure end-to-end |
| Spike | Limited by fixed capacity and other limits | Limited by maximum and scale response | May include both resume and scale response |
| Storage/other services | Still billed | Still billed | Still billed during pause |
| HA/DR fit | Validate selected configuration | Validate selected configuration | Geo-replication/failover groups, LTR, DNS aliases can prevent pause |

Serverless is a compute tier inside the vCore purchasing model. It is not a
separate service tier, traditional burst-credit system, unlimited compute, or
instant burst capacity. Both choices need query tuning, bounded pools,
backpressure, timeouts, safe retries, caching where appropriate, and monitoring.

## Fair experiment

Use the same database and identical workload/hash, schema/data, region/hardware
where supported, storage, app image/one-replica settings, instrumentation,
warm-up, and measurement windows. Capture scale/tier-switch periods separately.
Run A expected/business-hours/peak/spike, B identical peak/spike, then C1
expected/variable-demand/spike. C2 adds a genuine idle/resume window; it is not
comparable to steady-state query latency unless reported separately.

Report configured capacity, utilization, billed compute, active/idle duration,
near-ceiling observations, percentiles, errors, retries, timeouts, pool waits,
and variability. `app_cpu_percent` is relative to configured maximum; it is not a
direct history of actual allocated vCores. A high percentage supports pressure
analysis but does not alone establish the allocation trajectory.

## Billing matters

Use **Total `app_cpu_billed` vCore-seconds**, not average CPU percentage, for
observed serverless compute usage. Billing uses the per-second maximum of CPU,
configured minimum CPU, memory converted at 3 GB/vCore, and configured minimum
memory converted similarly. The documented GP 0.5 minimum / 4 maximum example
has 2.1 GB minimum memory and therefore an **active billing floor of 0.7 vCore**,
not 0.5. Revalidate the actual configuration.

The minimum, active hours, memory retention, non-pausable features, background
queries, retries, price meter, and remaining services may eliminate an apparent
idle-cost benefit. A continuously provisioned rate or the possibility of pause
does not by itself establish a winner. Use [cost inputs](cost-guide.md) and
[serverless decisions](serverless-decision-guide.md); “more testing required”
is a valid recommendation.

References: [overview](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview),
[billing](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-billing),
[monitoring](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-monitor),
[pause/resume](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-auto-pause-resume).
