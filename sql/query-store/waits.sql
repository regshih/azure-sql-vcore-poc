-- Purpose/context: user database Query Store per-plan wait categories in a UTC run window.
-- Permissions: monitoring VIEW DATABASE STATE (or supported VIEW DATABASE PERFORMANCE STATE).
-- Output: query/plan IDs, wait categories, execution type and total query wait milliseconds.
-- Interpret: compare total wait distribution for matched workloads; not per-request latency.
-- Limitations: requires supported Query Store wait capture enabled by approved deployment.
-- Missing rows do not imply zero waits. Interval overlap and configured retention apply.
DECLARE @EndUtc datetimeoffset = SYSUTCDATETIME();
DECLARE @StartUtc datetimeoffset = DATEADD(HOUR, -1, @EndUtc);
SELECT
    p.query_id, w.plan_id, w.wait_category_desc, w.execution_type_desc,
    SUM(w.total_query_wait_time_ms) AS total_query_wait_time_ms
FROM sys.query_store_wait_stats AS w
INNER JOIN sys.query_store_runtime_stats_interval AS i
    ON w.runtime_stats_interval_id = i.runtime_stats_interval_id
INNER JOIN sys.query_store_plan AS p ON w.plan_id = p.plan_id
WHERE i.start_time < @EndUtc AND i.end_time > @StartUtc
GROUP BY p.query_id, w.plan_id, w.wait_category_desc, w.execution_type_desc
ORDER BY total_query_wait_time_ms DESC;
