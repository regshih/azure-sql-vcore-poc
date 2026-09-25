# Query Store run-window analysis

Use the POC user database with the separate monitoring identity described in
[SQL diagnostics](../diagnostics/README.md). Adjust the declared UTC bounds to match the
experiment manifest; the default window is the last hour, not a specific recorded run.

- [top-queries.sql](top-queries.sql) returns the union of top-20 rankings by CPU, mean duration,
  total duration, executions, and logical reads. All averages are execution-weighted:
  `SUM(avg_metric * count_executions) / SUM(count_executions)`.
  CPU/duration are converted from microseconds to milliseconds. Logical reads are 8-KB pages.
- [regressions.sql](regressions.sql) compares before/after weighted durations by query and
  plan. Edit start/middle/end bounds to equal-duration windows. Only fully contained intervals
  are included. Sparse plans, different parameters, concurrency or cache state can explain a
  candidate regression; a changed plan alone does not establish causality.
- [waits.sql](waits.sql) aggregates captured Query Store wait categories by plan and execution
  type. The approved deployment must enable supported wait capture; the diagnostic never
  performs `ALTER DATABASE`.
- [query-text-opt-in.sql](query-text-opt-in.sql) returns **no rows by default**. Both the flag
  and a measured query ID must be edited locally. Text can reveal sensitive literals; do not
  publish it and do not execute unknown stored text.

Query Store retention and interval length are database settings, not the DMV's one-hour
retention. Runtime rows for the active interval can exist in memory and on disk; aggregate
all matching rows. Top-query/wait windows include overlapping intervals and can include
executions just outside the requested window. The regression query excludes straddling
intervals rather than misclassifying their counts. Align windows to Query Store interval
boundaries for comparisons; missing rows mean unobserved, not zero.

Plan forcing is an optional DBA-controlled experiment, **not a default fix**. First inspect
measured query/plan IDs, approval, compatibility and automatic-tuning state, record a baseline,
and plan an unforce rollback. These files do not force/unforce plans or clear Query Store.

Sources: [runtime stats units and active-interval aggregation](https://learn.microsoft.com/sql/relational-databases/system-catalog-views/sys-query-store-runtime-stats-transact-sql),
[Query Store best practices](https://learn.microsoft.com/sql/relational-databases/performance/best-practice-with-the-query-store),
[Query Store wait statistics](https://learn.microsoft.com/sql/relational-databases/system-catalog-views/sys-query-store-wait-stats-transact-sql).
