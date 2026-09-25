# Customer workshop worksheet

Do not put completed customer worksheets in this public repository. Store them in
an approved, private location. All unknowns below are deliberately **TBD**.

| Input | Supplied scenario or customer answer |
| --- | --- |
| Business objective | Evaluate Azure SQL Database vCore cost, performance, availability, and operations |
| Initial / future users | Approximately 10 / 100; not a sizing rule |
| Critical API operations | TBD |
| Usage schedule | TBD |
| Expected daily reads | Approximately 50,000 |
| Peak requests per second | TBD |
| Peak concurrency | TBD |
| Burst duration and frequency | TBD |
| Read/write ratio | Read-heavy; exact ratio TBD |
| Query types and complexity | TBD |
| Rows examined / returned | TBD |
| Logical reads and indexing effectiveness | TBD |
| Response-time objective, including p95 and p99 | TBD |
| Availability objective | TBD |
| Recovery time objective (RTO) | TBD |
| Recovery point objective (RPO) | TBD |
| Data size | Expected to remain below 5 GB during the POC |
| Data growth | TBD |
| Data / backup retention | TBD |
| Geographic and latency requirements | TBD |
| Security and identity requirements | TBD |
| Network and private connectivity requirements | TBD |
| Azure region | TBD |
| Budget and currency | TBD |
| Azure Hybrid Benefit eligibility | TBD |
| Reservation preferences | TBD |
| Expected active / idle hours | TBD |
| Auto-pause acceptability | TBD |
| Acceptable first-request resume latency | TBD |
| Read-after-write consistency | TBD |
| Acceptable cache staleness | TBD |
| Background jobs and reporting workload | TBD |
| Transaction duration and blocking | TBD |
| Connection pool size across all app instances | TBD |
| Retry limits and acceptable retry amplification | TBD |
| Customer-owned alert/runbook contacts | TBD |
| Remaining unknowns | TBD |

50,000 / 86,400 is about 0.579 reads/second averaged over 24 hours.
50,000 / 28,800 is about 1.736 reads/second over eight hours. Neither number is
a peak rate or a concurrency specification. One REST call can execute multiple
SQL statements, and a cache hit can execute none. Record API requests, SQL
operations, and SQL statements separately rather than assuming a 1:1 mapping.

## Workshop evidence checklist

For each experiment, record the hypothesis, identical workload profile hash,
schema and dataset versions, app version, UTC window, changed variable,
warm-up policy, measurements, missing evidence, and next experiment. Establish
customer acceptance thresholds before deciding whether a configuration passes.
Do not retrofit acceptance thresholds to make a run look successful.
