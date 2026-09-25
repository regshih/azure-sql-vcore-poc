-- Purpose/context: user database Query Store CPU/duration/read/execution ranking per plan.
-- Permissions: monitoring VIEW DATABASE STATE (or supported VIEW DATABASE PERFORMANCE STATE).
-- Output: query/plan IDs, executions, weighted mean/total metrics and ranks; durations are ms.
-- Interpret: order by the relevant rank; weighted SUM(avg * count) / SUM(count), never AVG(avg).
-- Limitations: Query Store must be enabled/readable; UTC windows include overlapping intervals,
-- so boundary aggregates may include out-of-window executions. Retention is database-configured.
-- Adjust BOTH UTC boundaries to the run manifest. No SQL text or plans are returned by default.
DECLARE @EndUtc datetimeoffset = SYSUTCDATETIME();
DECLARE @StartUtc datetimeoffset = DATEADD(HOUR, -1, @EndUtc);
WITH totals AS (
    SELECT
        p.query_id, p.plan_id,
        SUM(rs.count_executions) AS executions,
        SUM(rs.avg_cpu_time * rs.count_executions) / 1000.0 AS total_cpu_ms,
        SUM(rs.avg_duration * rs.count_executions) / 1000.0 AS total_duration_ms,
        SUM(rs.avg_logical_io_reads * rs.count_executions) AS total_logical_reads
    FROM sys.query_store_runtime_stats AS rs
    INNER JOIN sys.query_store_runtime_stats_interval AS i
        ON rs.runtime_stats_interval_id = i.runtime_stats_interval_id
    INNER JOIN sys.query_store_plan AS p ON rs.plan_id = p.plan_id
    INNER JOIN sys.query_store_query AS q ON p.query_id = q.query_id
    WHERE i.start_time < @EndUtc AND i.end_time > @StartUtc
        AND rs.execution_type = 0
    GROUP BY p.query_id, p.plan_id
), metrics AS (
    SELECT *,
        total_cpu_ms / NULLIF(executions, 0) AS avg_cpu_ms,
        total_duration_ms / NULLIF(executions, 0) AS avg_duration_ms,
        total_logical_reads / NULLIF(executions, 0) AS avg_logical_reads
    FROM totals
), ranked AS (
SELECT *,
    DENSE_RANK() OVER (ORDER BY total_cpu_ms DESC) AS cpu_rank,
    DENSE_RANK() OVER (ORDER BY avg_duration_ms DESC) AS avg_duration_rank,
    DENSE_RANK() OVER (ORDER BY total_duration_ms DESC) AS total_duration_rank,
    DENSE_RANK() OVER (ORDER BY executions DESC) AS executions_rank,
    DENSE_RANK() OVER (ORDER BY total_logical_reads DESC) AS logical_reads_rank
FROM metrics
)
SELECT *
FROM ranked
WHERE cpu_rank <= 20 OR avg_duration_rank <= 20 OR total_duration_rank <= 20
    OR executions_rank <= 20 OR logical_reads_rank <= 20
ORDER BY cpu_rank;
