# Read-only SQL diagnostics

Run each script deliberately in a SQL editor, with a separate **monitoring** identity.
The runtime principal's application-object permissions are not a reason to grant it broad
monitoring visibility. None of these scripts changes user data, clears waits, forces plans,
or enables Query Store. The wait sampler only writes an in-session table variable.

| File | Connection | Signal and limits |
|---|---|---|
| [database-resource-stats.sql](database-resource-stats.sql) | POC user DB | 15-second samples, about one hour; percentages of current resource limits |
| [master-resource-stats.sql](master-resource-stats.sql) | Separate connection to logical-server `master` | Five-minute aggregates, about 14 days; includes server database names |
| [active-requests.sql](active-requests.sql) | POC user DB | Current visible sessions, waits, blockers and lock state; no raw SQL text |
| [wait-deltas.sql](wait-deltas.sql) | POC user DB | Five-second deltas, reset/new-type indicator; do not compare lifetime totals |
| [storage.sql](storage.sql) | POC user DB | Data/log allocation, used MB, objective, automatic tuning state; save timestamped snapshots for growth |
| [indexes.sql](indexes.sql) | POC user DB | Per-index approximate rows and storage; no expensive rebuild operation |
| [missing-indexes.sql](missing-indexes.sql) | POC user DB | Optimizer estimates only; validate with measured tuning experiments |
| [master-connections.sql](master-connections.sql) | Separate `master` connection | Five-minute aggregates/events; up to 30 days, potentially delayed up to 24 hours or incomplete |
| [Query Store queries](../query-store/README.md) | POC user DB | UTC interval/plan-based CPU, duration, reads, regressions and waits |
| [Restore validation](../restore-validation/README.md) | Source, then restored DB | Exact counts, marker and integrity comparison; no invented expected values |

Permission requirements differ by view, database edition, and engine generation.
Start with `VIEW DATABASE STATE` on **only the POC user database** for its monitoring identity.
Where the individual view supports/requires newer granular permissions, use
`VIEW DATABASE PERFORMANCE STATE`; index metadata may also need `VIEW DEFINITION` or
`VIEW SECURITY DEFINITION`. Some Azure SQL service tiers restrict cross-session DMVs further.
Inspect the linked view documentation and grant only the required permissions; a denied DMV
is **not** grounds to grant the runtime identity server administrator.
Master-only views need a separately authorized master connection and cannot be assumed to work
from a contained user database connection. Never assume the two connections share privileges.

Raw resource names, IDs, metadata, error details, and optional query text are private evidence.
Sanitize separately before sharing. No diagnostic was executed against a live database during
offline validation. SQLFluff checks T-SQL syntax, not view existence, permissions or performance.

## Microsoft references

- [Current resource stats and permissions](https://learn.microsoft.com/sql/relational-databases/system-dynamic-management-views/sys-dm-db-resource-stats-azure-sql-database)
- [Historical resource stats](https://learn.microsoft.com/sql/relational-databases/system-catalog-views/sys-resource-stats-azure-sql-database)
- [Database connection stats and retention](https://learn.microsoft.com/sql/relational-databases/system-catalog-views/sys-database-connection-stats-azure-sql-database)
- [Event log and visibility](https://learn.microsoft.com/sql/relational-databases/system-catalog-views/sys-event-log-azure-sql-database)
- [Database wait stats](https://learn.microsoft.com/sql/relational-databases/system-dynamic-management-views/sys-dm-db-wait-stats-azure-sql-database)
- [Partition statistics permissions](https://learn.microsoft.com/sql/relational-databases/system-dynamic-management-views/sys-dm-db-partition-stats-transact-sql)
