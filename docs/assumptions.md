# Assumptions and unknowns

Every default below is a **POC assumption, not a confirmed customer requirement.**
Use the [customer worksheet](customer-workshop.md) to replace assumptions with
approved requirements in private configuration.

| Item | POC starting point | Customer requirement |
| --- | --- | --- |
| Database | Azure SQL Database, vCore model, General Purpose | Specified POC technology, not production sizing approval |
| Fixed compute | Standard-series (Gen5), provisioned 2 vCores | TBD |
| Scale comparison | Same database at 4 vCores, then restore original configuration | TBD |
| Serverless comparison | Gen5, minimum 0.5 / maximum 4 vCores, subject to capabilities validation | TBD |
| Serverless C1 | Auto-pause disabled (`-1`) | TBD |
| Serverless C2 | Auto-pause enabled; configurable delay validated against regional capabilities | TBD |
| Storage | Modest configurable allocation; dataset must stay below 5 GB | Customer data growth TBD |
| SQL authentication | Microsoft Entra tokens; managed identity when deployed | Organizational identity policy TBD |
| Regional choice | Operator-selected supported region; never a residency recommendation | TBD |
| Backups | Configurable storage redundancy and retention | RPO and retention TBD |
| Zone redundancy | Configurable, supported-SKU validation required | Availability objective TBD |
| DR | Optional, disabled by default | RTO / RPO TBD |
| Business Critical | Optional extension, disabled by default | Requires evidence and explicit enablement |
| Hyperscale | Not deployed | Future option only if requirements materially change |
| Cache | Off by default; local memory only for development | Staleness tolerance TBD |
| Dataset | Deterministic synthetic records with reproducible seed and skew | Production representativeness TBD |
| Acceptance thresholds | No invented customer pass/fail targets | TBD |
| Paid capacity | Deploy baseline first; run other configurations explicitly | Budget TBD |

## Boundaries

- User count and daily read volume do not size a database by themselves.
- Acceleration compresses time, changing concurrency, cache lifetimes, memory
  residency, autoscaling, idle behavior, and maintenance interactions. It is not
  a replay of an entire production day.
- Unit tests of fault injection, scaling decisions, or command construction do
  not demonstrate live Azure scaling, saturation, HA, or DR.
- Local repository tests do not validate Azure SQL query plans, permissions,
  token acquisition, or SQL Server transaction semantics.
- A missed performance target is not automatically throttling. Attribute an
  outcome only when correlated measurements support it.
- Serverless is bounded autoscaling, not burst credits or unlimited capacity.
  Its billed compute can reflect memory usage as well as CPU.
- Auto-pause requires no user sessions and no user workload CPU. Pool connections,
  readiness probes, diagnostics, reporting, and background jobs can prevent it.
  Geo-replication and failover groups prevent auto-pause.
- Availability is not cross-region disaster recovery. Database failover does not
  recreate a lost application tier, network, identity, or DNS configuration.
- SQL logical-server failover groups do not implement multi-primary writes.
- A retail estimate is not a bill. No cost winner exists until the measured
  usage and all applicable pricing inputs are available.

Use the exact statement **"Not demonstrated by this POC run."** wherever required
evidence is absent. Keep measurements, estimates, documentation, guidance,
recommendations, and unknowns in separate report sections.

## Product guidance verification

Guidance checked on 2026-09-25:

- [Serverless overview](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-overview?view=azuresql)
- [Serverless resource limits](https://learn.microsoft.com/azure/azure-sql/database/resource-limits-vcore-single-databases?view=azuresql)
- [Serverless billing, including memory-related minimums](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-billing?view=azuresql)
- [Auto-pause prerequisites and resume behavior](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-auto-pause-resume?view=azuresql)
- [Failover group topology](https://learn.microsoft.com/azure/azure-sql/database/failover-group-sql-db?view=azuresql)
- [Azure Cache for Redis updates and retirement](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-whats-new)

Azure Cache for Redis remains an optional compatibility target, not a new
deployment default. Current guidance recommends Azure Managed Redis. Creation
eligibility and retirement dates must be checked before provisioning a legacy
cache; do not silently substitute a different paid service.
