-- Purpose/context: candidate plan regressions across two equal adjacent UTC windows.
-- Permissions: monitoring VIEW DATABASE STATE (or supported VIEW DATABASE PERFORMANCE STATE).
-- Output: query ID, old/new plan IDs, counts, weighted means (ms), ratio and same-plan flag.
-- Interpret: slower mean is a candidate, not proof of plan causality; compare parameters/load.
-- Limitations: only fully contained intervals are used to avoid assigning a boundary interval
-- to both periods. Low-volume/absent plans do not establish regression; retention is configured.
-- Five executions is a POC investigation heuristic, not a customer requirement.
-- No plan forcing/unforcing or Query Store clearing occurs. Query text is not exposed.
DECLARE @EndUtc datetimeoffset = SYSUTCDATETIME();
DECLARE @MiddleUtc datetimeoffset = DATEADD(HOUR, -1, @EndUtc);
DECLARE @StartUtc datetimeoffset = DATEADD(HOUR, -2, @EndUtc);
WITH windows AS (
    SELECT
        p.query_id, p.plan_id,
        CASE WHEN i.end_time <= @MiddleUtc THEN 'before' ELSE 'after' END AS period,
        SUM(rs.count_executions) AS executions,
        SUM(rs.avg_duration * rs.count_executions)
            / NULLIF(SUM(rs.count_executions), 0) / 1000.0 AS avg_duration_ms
    FROM sys.query_store_runtime_stats AS rs
    INNER JOIN sys.query_store_runtime_stats_interval AS i
        ON rs.runtime_stats_interval_id = i.runtime_stats_interval_id
    INNER JOIN sys.query_store_plan AS p ON rs.plan_id = p.plan_id
    WHERE i.start_time >= @StartUtc AND i.end_time <= @EndUtc
        AND (i.end_time <= @MiddleUtc OR i.start_time >= @MiddleUtc)
        AND rs.execution_type = 0
    GROUP BY p.query_id, p.plan_id,
        CASE WHEN i.end_time <= @MiddleUtc THEN 'before' ELSE 'after' END
)
SELECT TOP (100)
    b.query_id, b.plan_id AS before_plan_id, a.plan_id AS after_plan_id,
    b.executions AS before_executions, a.executions AS after_executions,
    b.avg_duration_ms AS before_avg_ms, a.avg_duration_ms AS after_avg_ms,
    a.avg_duration_ms / NULLIF(b.avg_duration_ms, 0) AS duration_ratio,
    CASE WHEN a.plan_id = b.plan_id THEN 1 ELSE 0 END AS same_plan
FROM windows AS b
INNER JOIN windows AS a ON b.query_id = a.query_id
WHERE b.period = 'before' AND a.period = 'after'
    AND b.executions >= 5 AND a.executions >= 5
    AND a.avg_duration_ms > b.avg_duration_ms
ORDER BY duration_ratio DESC;
